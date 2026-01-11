import alsaaudio
import threading
import logging
import time
from enum import Enum
from typing import Optional, Callable
import config

logger = logging.getLogger(__name__)


class PlayerState(Enum):
    STOPPED = 0
    PLAYING = 1
    PAUSED = 2


class BitPerfectPlayer:

    def __init__(self, device: str = None):
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

        logger.debug(f"PLAYER: initialized with device={self.device} (lazy ALSA)")

    def _ensure_alsa(self):
        if self._alsa_initialized and self.pcm:
            return True
        return self._init_alsa()

    def _init_alsa(self):
        try:
            logger.debug(f"PLAYER: opening ALSA device {self.device}")
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
            logger.info(f"PLAYER: ALSA initialized in {elapsed:.1f}ms - {self.device} @ {config.SAMPLE_RATE}Hz/{config.BIT_DEPTH}bit/{config.CHANNELS}ch")
            logger.debug(f"PLAYER: period_size={config.PERIOD_SIZE}, buffer_size={config.BUFFER_SIZE}")
            return True

        except alsaaudio.ALSAAudioError as e:
            self._alsa_initialized = False
            print(f"\n\033[0;31m✗\033[0m audio device unavailable \033[2m({self.device})\033[0m\n")
            print("\033[2mcheck audio configuration:\033[0m")
            print(f"  aplay -l")
            print(f"  python3 -c \"import alsaaudio; print(alsaaudio.pcms())\"\n")
            logger.error(f"PLAYER: ALSA init failed: {e}")
            raise alsaaudio.ALSAAudioError(f"Device {self.device} not available. Check your audio configuration.")

    def verify_bit_perfect_config(self) -> dict:
        checks = {
            'alsa_device': self.device.startswith('hw:'),
            'sample_rate': True,
            'volume': True
        }

        if not self.device.startswith('hw:'):
            logger.warning(f"PLAYER: device {self.device} is not direct ALSA! Use 'hw:X,Y' for bit perfect")
            checks['alsa_device'] = False

        if config.VERIFY_VOLUME:
            try:
                mixer = alsaaudio.Mixer('PCM')
                volume = mixer.getvolume()[0]
                if volume < 100:
                    logger.warning(f"PLAYER: PCM volume at {volume}%. For bit perfect, use 100%")
                    checks['volume'] = False
            except Exception:
                pass

        return checks

    def load_track(self, pcm_data: bytes):
        logger.debug(f"PLAYER: load_track called, data size={len(pcm_data)} bytes")
        start_time = time.time()

        self.stop()

        self.current_data = pcm_data
        self.current_position = 0
        self.total_size = len(pcm_data)

        duration = self.get_duration()
        elapsed = (time.time() - start_time) * 1000
        logger.info(f"PLAYER: track loaded in {elapsed:.1f}ms - {self.total_size} bytes ({duration:.1f}s)")

        if duration == 0:
            logger.warning(f"PLAYER: WARNING duration=0! total_size={self.total_size}")

    def preload_next_track(self, pcm_data: bytes):
        if pcm_data:
            self.next_track_data = pcm_data
            duration = len(pcm_data) / (config.SAMPLE_RATE * config.CHANNELS * 2)
            logger.debug(f"PLAYER: next track preloaded - {len(pcm_data)} bytes ({duration:.1f}s)")
        else:
            self.next_track_data = None
            logger.debug("PLAYER: next track cleared")

    def play(self):
        if not self.current_data:
            logger.warning("PLAYER: play() called but no track loaded")
            return

        if self.state == PlayerState.PLAYING:
            logger.debug("PLAYER: already playing, ignoring play()")
            return

        if self.state == PlayerState.PAUSED:
            self.pause_event.set()
            self.state = PlayerState.PLAYING
            logger.info("PLAYER: resumed from pause")
            return

        self._ensure_alsa()

        self.stop_event.clear()
        self.pause_event.set()
        self.state = PlayerState.PLAYING
        self._chunks_written = 0
        self._underruns = 0

        self.play_thread = threading.Thread(target=self._playback_loop, daemon=True, name="ALSA-Playback")
        self.play_thread.start()

        logger.info(f"PLAYER: playback started at position {self.get_position():.1f}s")

    def pause(self):
        if self.state == PlayerState.PLAYING:
            self.state = PlayerState.PAUSED
            self.pause_event.clear()
            logger.info(f"PLAYER: paused at {self.get_position():.1f}s (chunks={self._chunks_written})")

    def stop(self):
        if self.state == PlayerState.STOPPED:
            return

        logger.debug(f"PLAYER: stopping (was at {self.get_position():.1f}s, chunks={self._chunks_written})")

        self.state = PlayerState.STOPPED
        self.stop_event.set()
        self.pause_event.set()

        if self.play_thread and self.play_thread.is_alive():
            self.play_thread.join(timeout=2)
            if self.play_thread.is_alive():
                logger.warning("PLAYER: playback thread did not stop gracefully")

        self.current_position = 0

        try:
            if self.pcm:
                self.pcm.pause(1)
                self.pcm.pause(0)
        except Exception:
            pass

        logger.info(f"PLAYER: stopped (wrote {self._chunks_written} chunks, {self._underruns} underruns)")

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
            logger.info(f"PLAYER: seek to {position_seconds:.1f}s")

    def _playback_loop(self):
        logger.debug("PLAYER: playback loop started")
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
                        logger.info("PLAYER: gapless transition to next track")
                        self.current_data = self.next_track_data
                        self.current_position = 0
                        self.total_size = len(self.next_track_data)
                        self.next_track_data = None

                        if self.on_track_end:
                            self.on_track_end()
                        continue
                    else:
                        elapsed = time.time() - loop_start
                        logger.info(f"PLAYER: end of track (played {elapsed:.1f}s, {self._chunks_written} chunks)")
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
                        logger.warning(f"PLAYER: slow write #{self._chunks_written}: {write_time:.1f}ms")
                        self._underruns += 1

                    if self._chunks_written % 5000 == 0:
                        position = self.current_position / bytes_per_second
                        logger.debug(f"PLAYER: chunk #{self._chunks_written} at {position:.1f}s")

                except alsaaudio.ALSAAudioError as e:
                    logger.error(f"PLAYER: ALSA error at chunk #{self._chunks_written}: {e}")
                    self._underruns += 1
                    try:
                        self.pcm.close()
                        self._init_alsa()
                        self.pcm.write(data)
                        logger.info("PLAYER: recovered from ALSA error")
                    except Exception:
                        logger.error("PLAYER: failed to recover from ALSA error")
                        self.state = PlayerState.STOPPED
                        break

                self.current_position += len(data)

                if self.on_position_change:
                    self.on_position_change(self.get_position())

        except Exception as e:
            logger.error(f"PLAYER: exception in playback loop: {e}")
            self.state = PlayerState.STOPPED

        logger.debug(f"PLAYER: playback loop ended (chunks={self._chunks_written}, underruns={self._underruns})")

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

    def is_playing(self) -> bool:
        return self.state == PlayerState.PLAYING

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
        logger.debug("PLAYER: cleanup called")
        self.stop()
        if self.pcm:
            try:
                self.pcm.close()
            except Exception:
                pass
        logger.info(f"PLAYER: cleanup complete (total chunks={self._chunks_written}, underruns={self._underruns})")
