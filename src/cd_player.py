import alsaaudio
import threading
import logging
import time
from typing import Optional, Callable
import config
from audio_transport import AudioTransport, PlayerState

logger = logging.getLogger(__name__)


class BitPerfectPlayer(AudioTransport):

    def __init__(self, device: str = None, data_provider=None, track_count: int = 0):
        self.device = device or config.ALSA_DEVICE
        self.state = PlayerState.STOPPED
        self.pcm: Optional[alsaaudio.PCM] = None
        self._alsa_initialized = False

        self.current_data: Optional[bytes] = None
        self.current_position: int = 0
        self.total_size: int = 0

        self.next_track_data: Optional[bytes] = None

        self.play_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()

        self.on_position_change: Optional[Callable] = None
        self.on_track_end: Optional[Callable] = None

        self._chunks_written = 0
        self._underruns = 0
        self._last_write_time = 0

        self._data_provider = data_provider
        self._current_track_index = -1
        self._track_count = track_count
        self._next_track_index = -1

        logger.debug(f"PLAYER: device={self.device}")

    def _ensure_alsa(self):
        if self._alsa_initialized and self.pcm:
            return True
        return self._init_alsa()

    def _init_alsa(self):
        try:
            start_time = time.time()

            self.pcm = alsaaudio.PCM(
                device=self.device,
                type=alsaaudio.PCM_PLAYBACK,
                mode=alsaaudio.PCM_NORMAL
            )

            self.pcm.setchannels(config.CHANNELS)
            self.pcm.setrate(config.SAMPLE_RATE)
            self.pcm.setformat(alsaaudio.PCM_FORMAT_S16_LE)
            self.pcm.setperiodsize(config.PERIOD_SIZE)

            self._alsa_initialized = True
            elapsed = (time.time() - start_time) * 1000
            logger.info(f"PLAYER: ALSA ready in {elapsed:.1f}ms ({self.device})")
            return True

        except alsaaudio.ALSAAudioError as e:
            self._alsa_initialized = False
            print(f"\n\033[0;31m✗\033[0m audio device unavailable \033[2m({self.device})\033[0m\n")
            print("\033[2mcheck audio configuration:\033[0m")
            print(f"  aplay -l")
            print(f"  python3 -c \"import alsaaudio; print(alsaaudio.pcms())\"\n")
            logger.error(f"PLAYER: ALSA err: {e}")
            raise alsaaudio.ALSAAudioError(f"Device {self.device} not available. Check your audio configuration.")

    def verify_bit_perfect_config(self) -> dict:
        checks = {
            'alsa_device': self.device.startswith('hw:'),
            'sample_rate': True,
            'volume': True
        }

        if not self.device.startswith('hw:'):
            logger.warning(f"PLAYER: not direct ALSA ({self.device}), use hw:X,Y")
            checks['alsa_device'] = False

        if config.VERIFY_VOLUME:
            try:
                mixer = alsaaudio.Mixer('PCM')
                volume = mixer.getvolume()[0]
                if volume < 100:
                    logger.warning(f"PLAYER: PCM volume {volume}%, should be 100%")
                    checks['volume'] = False
            except Exception:
                pass

        return checks

    def load_pcm_data(self, pcm_data: bytes):
        self.stop()
        self.current_data = pcm_data
        self.current_position = 0
        self.total_size = len(pcm_data)
        logger.debug(f"PLAYER: loaded {self.total_size} bytes ({self.get_duration():.1f}s)")

    def preload_next_track(self, pcm_data: bytes):
        self.next_track_data = pcm_data

    def play(self):
        if not self.current_data or self.state == PlayerState.PLAYING:
            return

        if self.state == PlayerState.PAUSED:
            self.pause_event.set()
            self.state = PlayerState.PLAYING
            return

        self._ensure_alsa()

        self.stop_event.clear()
        self.pause_event.set()
        self.state = PlayerState.PLAYING
        self._chunks_written = 0
        self._underruns = 0

        self.play_thread = threading.Thread(target=self._playback_loop, daemon=True, name="ALSA-Playback")
        self.play_thread.start()

    def pause(self):
        if self.state == PlayerState.PLAYING:
            self.state = PlayerState.PAUSED
            self.pause_event.clear()

    def stop(self):
        if self.state == PlayerState.STOPPED:
            return

        self.state = PlayerState.STOPPED
        self.stop_event.set()
        self.pause_event.set()

        if self.play_thread and self.play_thread.is_alive():
            self.play_thread.join(timeout=2)
            if self.play_thread.is_alive():
                logger.warning("PLAYER: thread stuck")

        self.current_position = 0

        try:
            if self.pcm:
                self.pcm.pause(1)
                self.pcm.pause(0)
        except Exception:
            pass

    def seek(self, position_seconds: float):
        if not self.current_data:
            return

        bytes_per_second = config.SAMPLE_RATE * config.CHANNELS * (config.BIT_DEPTH // 8)
        new_position = int(position_seconds * bytes_per_second)
        new_position = (new_position // 4) * 4

        if 0 <= new_position < self.total_size:
            was_playing = self.state == PlayerState.PLAYING
            self.stop()
            self.current_position = new_position
            if was_playing:
                self.play()
            logger.debug(f"PLAYER: seek to {position_seconds:.1f}s")

    def _playback_loop(self):
        loop_start = time.time()

        try:
            chunk_size = config.PERIOD_SIZE * 4
            bytes_per_second = config.SAMPLE_RATE * config.CHANNELS * 2

            while not self.stop_event.is_set():
                self.pause_event.wait()

                if self.stop_event.is_set():
                    break

                if self.current_position >= self.total_size:
                    if self.next_track_data:
                        self.current_data = self.next_track_data
                        self.current_position = 0
                        self.total_size = len(self.next_track_data)
                        self.next_track_data = None
                        self._current_track_index = self._next_track_index

                        if self.on_track_end:
                            self.on_track_end()
                        continue
                    else:
                        self.state = PlayerState.STOPPED
                        if self.on_track_end:
                            self.on_track_end()
                        break

                remaining = self.total_size - self.current_position
                chunk = min(chunk_size, remaining)
                data = self.current_data[self.current_position:self.current_position + chunk]

                try:
                    write_start = time.time()
                    frames_written = self.pcm.write(data)
                    write_time = (time.time() - write_start) * 1000

                    self._chunks_written += 1

                    if write_time > 200:
                        logger.warning(f"PLAYER: slow write {write_time:.1f}ms")
                        self._underruns += 1

                except alsaaudio.ALSAAudioError as e:
                    logger.error(f"PLAYER: ALSA err: {e}")
                    self._underruns += 1
                    try:
                        self.pcm.close()
                        self._init_alsa()
                        self.pcm.write(data)
                    except Exception:
                        logger.error("PLAYER: recovery failed")
                        self.state = PlayerState.STOPPED
                        break

                self.current_position += len(data)

                if self.on_position_change:
                    self.on_position_change(self.get_position())

        except Exception as e:
            logger.error(f"PLAYER: playback err: {e}")
            self.state = PlayerState.STOPPED

    def get_position(self) -> float:
        if not self.current_data:
            return 0.0
        bytes_per_second = config.SAMPLE_RATE * config.CHANNELS * (config.BIT_DEPTH // 8)
        return self.current_position / bytes_per_second

    def get_duration(self) -> float:
        if not self.current_data:
            return 0.0
        bytes_per_second = config.SAMPLE_RATE * config.CHANNELS * (config.BIT_DEPTH // 8)
        return self.total_size / bytes_per_second

    def get_state(self) -> PlayerState:
        return self.state

    def navigate_to(self, track_index, auto_play=True):
        if not self._data_provider:
            return False
        pcm_data = self._data_provider(track_index + 1)  # provider uses 1-based
        if not pcm_data:
            return False
        self.load_pcm_data(pcm_data)
        self._current_track_index = track_index
        if auto_play:
            self.play()
        return True

    def prepare_next(self, track_index):
        if not self._data_provider:
            return
        if track_index < 0:
            self.preload_next_track(None)
            self._next_track_index = -1
            return
        pcm_data = self._data_provider(track_index + 1)
        self.preload_next_track(pcm_data)
        self._next_track_index = track_index

    def get_current_track_index(self):
        return self._current_track_index

    def get_track_count(self):
        return self._track_count

    def get_stats(self) -> dict:
        return {
            'state': self.state.name,
            'position': self.get_position(),
            'duration': self.get_duration(),
            'chunks_written': self._chunks_written,
            'underruns': self._underruns,
            'has_next_track': self.next_track_data is not None
        }

    def cleanup(self):
        self.stop()
        if self.pcm:
            try:
                self.pcm.close()
            except Exception:
                pass
