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

logger = logging.getLogger(__name__)


class DirectCDPlayer:

    def __init__(self, device: str = None, tracks: List = None):
        self.cd_device = config.CD_DEVICE
        self.alsa_device = device or config.ALSA_DEVICE
        self.tracks = tracks or []

        self.current_track = 0
        self.state = 'stopped'

        self._process: Optional[subprocess.Popen] = None
        self._ipc_socket: Optional[str] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._pause_time: float = 0
        self._playback_started: bool = False
        self._cached_position: float = 0.0
        self._last_position_update: float = 0.0

        self.on_track_end: Optional[Callable] = None

        logger.debug(f"DirectCDPlayer initialized: cd={self.cd_device}, alsa={self.alsa_device}, tracks={len(self.tracks)}")

    def _ensure_mpv(self):
        if self._process and self._process.poll() is None:
            return True

        self._ipc_socket = tempfile.mktemp(prefix='mpv_', suffix='.sock')

        cmd = [
            'mpv',
            '--idle=yes',
            '--no-video',
            f'--ao=alsa',
            f'--audio-device=alsa/{self.alsa_device}',
            '--audio-pitch-correction=no',
            '--audio-normalize-downmix=no',
            '--replaygain=no',
            '--volume=100',
            '--volume-max=100',
            '--af=',
            '--audio-swresample-o=',
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

    def _send_ipc(self, command: list) -> dict:
        if not self._ipc_socket:
            return {"error": "no socket"}

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.3)
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

    def _get_chapter_start(self, track_num: int) -> float:
        start = 0.0
        for i in range(track_num - 1):
            if i < len(self.tracks) and hasattr(self.tracks[i], 'duration_seconds'):
                start += self.tracks[i].duration_seconds
        return start

    def _stop_monitor_thread(self):
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            if threading.current_thread() != self._monitor_thread:
                self._monitor_thread.join(timeout=1)

    def _handle_track_end(self, reason: str):
        if self.state == 'playing':
            logger.info(f"DirectCDPlayer: track {self.current_track} ended ({reason})")
            self.state = 'stopped'
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

            time.sleep(0.1)

        time.sleep(0.3)

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

            time.sleep(0.3)

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
        self.state = 'playing'
        self._playback_started = False
        self._cached_position = 0.0
        self._last_position_update = 0.0

        idle = self._get_property("core-idle")
        path = self._get_property("path")
        cd_url = f'cdda://{self.cd_device}'

        if path == cd_url and idle is not True:
            logger.debug(f"DirectCDPlayer: seeking to chapter {track_num - 1}")
            self._send_ipc(["set_property", "chapter", track_num - 1])
        else:
            result = self._send_ipc(["loadfile", cd_url, "replace"])
            if result.get("error") != "success":
                logger.error(f"DirectCDPlayer: loadfile failed: {result}")
                self.state = 'stopped'
                return False

            if track_num > 1:
                time.sleep(0.5)
                self._send_ipc(["set_property", "chapter", track_num - 1])

        logger.info(f"DirectCDPlayer: playing track {track_num}")

        self._monitor_thread = threading.Thread(
            target=self._monitor_playback,
            daemon=True,
            name=f"MPV-Monitor-T{track_num}"
        )
        self._monitor_thread.start()

        return True

    def pause(self):
        if self.state == 'playing':
            self._pause_time = self.get_position()
            self._send_ipc(["set_property", "pause", True])
            self.state = 'paused'
            logger.info(f"DirectCDPlayer: paused at {self._pause_time:.1f}s")

    def resume(self):
        if self.state == 'paused':
            self._send_ipc(["set_property", "pause", False])
            self.state = 'playing'
            logger.info("DirectCDPlayer: resumed")

    def stop(self):
        self._stop_monitor_thread()

        if self._process:
            self._send_ipc(["stop"])

        self.state = 'stopped'
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

    def get_state(self) -> str:
        return self.state

    def get_current_track(self) -> int:
        return self.current_track

    def get_position(self) -> float:
        if self.state == 'playing':
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
        elif self.state == 'paused':
            return self._pause_time
        return 0.0

    def get_duration(self) -> float:
        if self.current_track < 1 or self.current_track > len(self.tracks):
            return 0.0
        track_info = self.tracks[self.current_track - 1]
        if hasattr(track_info, 'duration_seconds'):
            return track_info.duration_seconds
        return 0.0

    def cleanup(self):
        logger.debug("DirectCDPlayer: cleanup called")
        self._stop_monitor_thread()

        if self._process:
            self._send_ipc(["quit"])
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

        logger.info("DirectCDPlayer: cleanup complete")
