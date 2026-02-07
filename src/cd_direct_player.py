import subprocess
import threading
import socket
import json
import time
import logging
import tempfile
import os
from typing import Optional, List, Callable
import config
from audio_transport import AudioTransport, PlayerState

logger = logging.getLogger(__name__)


class DirectCDPlayer(AudioTransport):

    def __init__(self, device: str = None, tracks: List = None):
        self.cd_device = config.CD_DEVICE
        self.alsa_device = device or config.ALSA_DEVICE
        self.tracks = tracks or []

        self.current_track = 0
        self.state = PlayerState.STOPPED

        self._process: Optional[subprocess.Popen] = None
        self._ipc_socket: Optional[str] = None
        self._ipc_conn: Optional[socket.socket] = None
        self._ipc_lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._pause_time: float = 0
        self._playback_started: bool = False
        self._cached_position: float = 0.0
        self._last_position_update: float = 0.0
        self._cd_loaded_in_mpv: bool = False

        self.on_track_end: Optional[Callable] = None

        # Pre-calculate chapter start times (O(1) lookup instead of O(n))
        self._chapter_starts: List[float] = self._build_chapter_starts()

        logger.debug(f"DirectCDPlayer initialized: cd={self.cd_device}, alsa={self.alsa_device}, tracks={len(self.tracks)}")

    def _ensure_mpv(self):
        if self._process and self._process.poll() is None:
            return True

        self._ipc_dir = tempfile.mkdtemp(prefix='mpv_')
        self._ipc_socket = os.path.join(self._ipc_dir, 'socket.sock')

        cmd = [
            'mpv',
            '--idle=yes',
            '--no-video',
            # Audio output (ALSA direct on Raspberry Pi OS)
            '--ao=alsa',
            f'--audio-device=alsa/{self.alsa_device}',
            # Bit-perfect: force CD format (44.1kHz/16bit/stereo)
            '--audio-samplerate=44100',
            '--audio-format=s16',
            '--audio-channels=stereo',
            # No processing (bit-perfect)
            '--audio-pitch-correction=no',
            '--audio-normalize-downmix=no',
            '--alsa-resample=no',
            '--replaygain=no',
            '--af=',
            '--audio-swresample-o=',
            # Volume
            '--volume=100',
            '--volume-max=100',
            # Gapless chapter transitions
            '--gapless-audio=weak',
            # Buffer: safe values for CD streaming on Raspberry Pi
            '--audio-buffer=2',
            '--demuxer-readahead-secs=5',
            # CD-specific
            '--cdda-paranoia=0',
            # IPC
            '--no-terminal',
            '--really-quiet',
            f'--input-ipc-server={self._ipc_socket}',
        ]

        logger.debug(f"DirectCDPlayer: starting persistent mpv")

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            for i in range(30):
                if os.path.exists(self._ipc_socket):
                    time.sleep(0.1)
                    logger.debug(f"DirectCDPlayer: mpv IPC ready after {(i+1)*0.1:.1f}s")
                    return True
                time.sleep(0.1)
            logger.warning("DirectCDPlayer: mpv IPC not ready after 3s")
            return True
        except Exception as e:
            logger.error(f"DirectCDPlayer: failed to start mpv: {e}")
            return False

    def _ensure_ipc_conn(self) -> bool:
        """Ensure persistent IPC connection is open."""
        if self._ipc_conn:
            return True
        if not self._ipc_socket:
            return False
        try:
            self._ipc_conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._ipc_conn.settimeout(0.1)
            self._ipc_conn.connect(self._ipc_socket)
            self._ipc_conn.setblocking(False)
            logger.debug("DirectCDPlayer: persistent IPC connection established")
            return True
        except Exception as e:
            logger.debug(f"DirectCDPlayer: failed to establish IPC connection: {e}")
            self._ipc_conn = None
            return False

    def _close_ipc_conn(self):
        """Close persistent IPC connection."""
        if self._ipc_conn:
            try:
                self._ipc_conn.close()
            except Exception:
                pass
            self._ipc_conn = None

    def _send_ipc(self, command: list) -> dict:
        if not self._ipc_socket:
            return {"error": "no socket"}

        with self._ipc_lock:
            # Try persistent connection first
            if self._ensure_ipc_conn():
                try:
                    msg = json.dumps({"command": command}) + "\n"
                    self._ipc_conn.setblocking(True)
                    self._ipc_conn.settimeout(0.1)
                    self._ipc_conn.send(msg.encode())
                    response = self._ipc_conn.recv(4096).decode('utf-8', errors='ignore')
                    self._ipc_conn.setblocking(False)
                    return json.loads(response.strip().split('\n')[0])
                except Exception as e:
                    logger.debug(f"DirectCDPlayer: persistent IPC failed, reconnecting: {e}")
                    self._close_ipc_conn()

            # Fallback: new connection
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(0.1)
                sock.connect(self._ipc_socket)
                msg = json.dumps({"command": command}) + "\n"
                sock.send(msg.encode())
                response = sock.recv(4096).decode('utf-8', errors='ignore')
                sock.close()
                return json.loads(response.strip().split('\n')[0])
            except Exception as e:
                logger.debug(f"DirectCDPlayer: IPC error: {e}")
                return {"error": str(e)}

    def _get_property(self, prop: str):
        result = self._send_ipc(["get_property", prop])
        return result.get("data")

    def _build_chapter_starts(self) -> List[float]:
        """Pre-calculate chapter start times for O(1) lookup."""
        starts = [0.0]  # Track 1 starts at 0
        cumulative = 0.0
        for track in self.tracks:
            if hasattr(track, 'duration_seconds'):
                cumulative += track.duration_seconds
            starts.append(cumulative)
        return starts

    def _get_chapter_start(self, track_num: int) -> float:
        """Get start time for track (1-indexed). O(1) lookup."""
        if 1 <= track_num <= len(self._chapter_starts):
            return self._chapter_starts[track_num - 1]
        return 0.0

    def _stop_monitor_thread(self):
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            if threading.current_thread() != self._monitor_thread:
                self._monitor_thread.join(timeout=0.2)

    def _handle_track_end(self, reason: str):
        if self.state == PlayerState.PLAYING:
            logger.info(f"DirectCDPlayer: track {self.current_track} ended ({reason})")
            self.state = PlayerState.STOPPED
            self._playback_started = False
            if self.on_track_end:
                threading.Thread(
                    target=self.on_track_end,
                    daemon=True,
                    name="TrackEndCallback"
                ).start()

    def _monitor_playback(self):
        logger.debug("DirectCDPlayer: monitor thread started")

        chapter_start = self._get_chapter_start(self.current_track)

        start_wait = time.time()
        while not self._stop_event.is_set():
            pos = self._get_property("time-pos")
            if pos is not None:
                track_pos = pos - chapter_start
                if track_pos > 0.1:
                    if not self._playback_started:
                        self._playback_started = True
                        logger.info(f"DirectCDPlayer: audio started for track {self.current_track} (pos={track_pos:.1f}s)")
                    break

            if time.time() - start_wait > 20:
                logger.warning("DirectCDPlayer: timeout waiting for audio")
                self._playback_started = True
                break

            # Use event.wait() instead of sleep() for quick response to stop
            if self._stop_event.wait(timeout=0.1):
                return  # Stop requested

        # Short delay before monitoring, but interruptible
        if self._stop_event.wait(timeout=0.2):
            return

        expected_chapter = self.current_track - 1
        while not self._stop_event.is_set():
            chapter = self._get_property("chapter")
            if chapter is not None and chapter != expected_chapter:
                self._handle_track_end(f"chapter changed to {chapter + 1}")
                break

            eof = self._get_property("eof-reached")
            if eof is True:
                self._handle_track_end("EOF")
                break

            # Use event.wait() for quick response to stop
            self._stop_event.wait(timeout=0.3)

        logger.debug("DirectCDPlayer: monitor thread stopped")

    def play_track(self, track_num: int) -> bool:
        if track_num < 1 or track_num > len(self.tracks):
            logger.warning(f"DirectCDPlayer: invalid track {track_num}")
            return False

        self._stop_monitor_thread()

        if not self._ensure_mpv():
            return False

        self._stop_event.clear()
        self.current_track = track_num
        self.state = PlayerState.PLAYING
        self._playback_started = False
        self._cached_position = 0.0
        self._last_position_update = 0.0

        if self._cd_loaded_in_mpv:
            # Fast path: CD already loaded, just switch chapter
            logger.debug(f"DirectCDPlayer: seeking to chapter {track_num - 1}")
            self._send_ipc(["set_property", "chapter", track_num - 1])
        else:
            # First load: need to load CD into mpv
            # NOTE: cdda:// has issues with mpv idle mode (see mpv#7384)
            # Streaming mode may not work reliably - use RAM mode for production
            cd_url = f'cdda://{self.cd_device}'
            result = self._send_ipc(["loadfile", cd_url, "replace"])
            if result.get("error") != "success":
                logger.error(f"DirectCDPlayer: loadfile failed: {result}")
                self.state = PlayerState.STOPPED
                return False

            self._cd_loaded_in_mpv = True

            if track_num > 1:
                time.sleep(0.3)
                self._send_ipc(["set_property", "chapter", track_num - 1])

        logger.info(f"DirectCDPlayer: playing track {track_num}")

        self._monitor_thread = threading.Thread(
            target=self._monitor_playback,
            daemon=True,
            name=f"MPV-Monitor-T{track_num}"
        )
        self._monitor_thread.start()

        return True

    def play(self):
        """Start or resume playback. Implements AudioTransport interface."""
        if self.state == PlayerState.PAUSED:
            self.resume()
        elif self.state == PlayerState.STOPPED and self.current_track > 0:
            self.play_track(self.current_track)

    def pause(self):
        if self.state == PlayerState.PLAYING:
            self._pause_time = self.get_position()
            self._send_ipc(["set_property", "pause", True])
            self.state = PlayerState.PAUSED
            logger.info(f"DirectCDPlayer: paused at {self._pause_time:.1f}s")

    def resume(self):
        if self.state == PlayerState.PAUSED:
            self._send_ipc(["set_property", "pause", False])
            self.state = PlayerState.PLAYING
            logger.info("DirectCDPlayer: resumed")

    def stop(self):
        self._stop_monitor_thread()

        if self._process:
            self._send_ipc(["stop"])

        self.state = PlayerState.STOPPED
        self._pause_time = 0
        self._playback_started = False
        logger.info("DirectCDPlayer: stopped")

    def next_track(self):
        if self.current_track < len(self.tracks):
            self.play_track(self.current_track + 1)
        else:
            logger.debug("DirectCDPlayer: already at last track")

    def prev_track(self):
        if self.current_track > 1:
            self.play_track(self.current_track - 1)
        else:
            logger.debug("DirectCDPlayer: already at first track")

    def get_state(self) -> PlayerState:
        return self.state

    def get_current_track(self) -> int:
        return self.current_track

    def get_position(self) -> float:
        if self.state == PlayerState.PLAYING:
            if not self._playback_started:
                return 0.0

            now = time.time()
            if now - self._last_position_update < 0.2:
                return self._cached_position

            pos = self._get_property("time-pos")
            if pos is not None:
                chapter_start = self._get_chapter_start(self.current_track)
                track_pos = pos - chapter_start
                if track_pos >= 0:
                    self._cached_position = track_pos
                    self._last_position_update = now
                    return track_pos

            return self._cached_position
        elif self.state == PlayerState.PAUSED:
            return self._pause_time
        return 0.0

    def get_duration(self) -> float:
        if self.current_track < 1 or self.current_track > len(self.tracks):
            return 0.0
        track_info = self.tracks[self.current_track - 1]
        if hasattr(track_info, 'duration_seconds'):
            return track_info.duration_seconds
        return 0.0

    def seek(self, position_seconds: float) -> None:
        """Seek within current track. Limited support via mpv chapter-relative seek."""
        if self.current_track < 1 or self.state == PlayerState.STOPPED:
            return
        chapter_start = self._get_chapter_start(self.current_track)
        absolute_pos = chapter_start + position_seconds
        self._send_ipc(["seek", absolute_pos, "absolute"])
        logger.info(f"DirectCDPlayer: seek to {position_seconds:.1f}s")

    def load_track_by_index(self, track_index: int) -> bool:
        """Load track by 0-based index. Implements AudioTransport interface."""
        track_num = track_index + 1  # Convert to 1-based
        if track_num < 1 or track_num > len(self.tracks):
            return False
        self.current_track = track_num
        return True

    def cleanup(self):
        logger.debug("DirectCDPlayer: cleanup called")
        self._stop_monitor_thread()

        if self._process:
            self._send_ipc(["quit"])
            self._close_ipc_conn()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                logger.warning("DirectCDPlayer: mpv not responding, terminating")
                self._process.terminate()
                try:
                    self._process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    logger.warning("DirectCDPlayer: force killing mpv")
                    self._process.kill()
                    self._process.wait()
            except Exception as e:
                logger.error(f"DirectCDPlayer: error stopping mpv: {e}")
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        if self._ipc_socket:
            try:
                os.unlink(self._ipc_socket)
            except Exception:
                pass
            self._ipc_socket = None

        if hasattr(self, '_ipc_dir') and self._ipc_dir:
            try:
                os.rmdir(self._ipc_dir)
            except Exception:
                pass
            self._ipc_dir = None

        self._cd_loaded_in_mpv = False
        logger.info("DirectCDPlayer: cleanup complete")
