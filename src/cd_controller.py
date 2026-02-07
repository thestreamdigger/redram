import logging
import time
from typing import Optional, Callable
from cd_ripper import CDRipper, CDTrack
from cd_player import BitPerfectPlayer
from audio_transport import PlayerState
from cd_direct_player import DirectCDPlayer
from superdrive import SuperDriveController
from track_sequencer import TrackSequencer, RepeatMode
import config

logger = logging.getLogger(__name__)


class CDPlayerController:

    def __init__(self):
        self.ripper = CDRipper()
        self.player = BitPerfectPlayer(
            data_provider=self.ripper.load_track_data
        )
        self.superdrive = SuperDriveController(config.CD_DEVICE)
        self.superdrive.detect()

        self.direct_player: Optional[DirectCDPlayer] = None
        self.is_direct_mode: bool = False

        self.sequencer = TrackSequencer()

        self.cd_loaded: bool = False
        self.last_stop_time: float = 0.0
        self.stop_count: int = 0

        self._track_change_listeners = []
        self._cd_loaded_listeners = []
        self._status_change_listeners = []
        self._loading_progress_listeners = []

        self.player.on_track_end = self._on_track_end

    def on(self, event, callback):
        getattr(self, f'_{event}_listeners').append(callback)

    def _fire(self, event, *args):
        for cb in getattr(self, f'_{event}_listeners'):
            try:
                cb(*args)
            except Exception as e:
                logger.error(f"listener error: {e}")

    @property
    def transport(self):
        if self.is_direct_mode and self.direct_player:
            return self.direct_player
        return self.player

    @property
    def repeat_mode(self) -> RepeatMode:
        return self.sequencer.repeat_mode

    @repeat_mode.setter
    def repeat_mode(self, value: RepeatMode):
        self.sequencer.repeat_mode = value

    @property
    def shuffle_on(self) -> bool:
        return self.sequencer.shuffle_on

    @shuffle_on.setter
    def shuffle_on(self, value: bool):
        self.sequencer.shuffle_on = value

    def _wake_transport(self, progress_callback: Optional[Callable] = None):
        if self.superdrive.is_superdrive and not self.superdrive.is_enabled:
            logger.info("waking SuperDrive")
            if progress_callback:
                progress_callback(0, 0, "waking")
            self._fire('loading_progress', 0, 0, "waking")
            self.superdrive.enable()

    def load(self, progress_callback: Optional[Callable] = None, extraction_level: int = None) -> tuple:

        level = extraction_level if extraction_level is not None else config.DEFAULT_EXTRACTION_LEVEL

        if level == 0:
            result = self._load_streaming_mode(progress_callback)
        else:
            result = self._load_ram_mode(progress_callback, level)

        if result[0] and config.should_autoplay(level):
            self.play()
            logger.info(f"autoplay level {level}")

        return result

    def _load_streaming_mode(self, progress_callback: Optional[Callable] = None) -> tuple:
        logger.info("streaming mode")

        self._wake_transport(progress_callback)

        if progress_callback:
            progress_callback(0, 0, "detecting")
        self._fire('loading_progress', 0, 0, "detecting")

        success, status = self.scan()
        if not success:
            return (False, status)

        tracks = self.get_scanned_tracks()
        logger.info(f"streaming: {len(tracks)} tracks")

        self.direct_player = DirectCDPlayer(tracks=tracks)
        self.direct_player.on_track_end = self._on_track_end
        self.is_direct_mode = True
        self.cd_loaded = True

        self.sequencer.set_total_tracks(len(tracks))

        self.transport.navigate_to(0, auto_play=False)

        logger.info("streaming ready")

        if progress_callback:
            progress_callback(len(tracks), len(tracks), "complete")
        self._fire('loading_progress', len(tracks), len(tracks), "complete")

        self._fire('cd_loaded', len(tracks))

        return (True, "streaming")

    def _load_ram_mode(self, progress_callback: Optional[Callable] = None, extraction_level: int = None) -> tuple:
        logger.info(f"RAM mode level {extraction_level}")

        if extraction_level is not None:
            self.ripper.set_extraction_level(extraction_level)

        self._wake_transport(progress_callback)

        if progress_callback:
            progress_callback(0, 0, "detecting")
        self._fire('loading_progress', 0, 0, "detecting")

        if not self.ripper.detect_cd():
            logger.info("no cd")
            return (False, "no_disc")

        logger.info("cd detected")

        if progress_callback:
            progress_callback(0, 0, "reading_toc")
        self._fire('loading_progress', 0, 0, "reading_toc")

        tracks = self.ripper.read_toc()
        if not tracks:
            logger.error("failed to read toc")
            return (False, "read_error")

        self.ripper.read_cdtext()
        logger.info(f"TOC: {len(tracks)} tracks")

        total_duration = sum(t.duration_seconds for t in tracks)
        required_ram = config.estimate_cd_ram_usage_mb(total_duration)
        ram_ok, available_ram, ram_msg = config.check_ram_availability(required_ram)

        if not ram_ok:
            logger.error(f"RAM err: {ram_msg}")
            if progress_callback:
                progress_callback(0, 0, "error")
            self._fire('loading_progress', 0, 0, "error")
            return (False, "ram_error")

        logger.debug(f"RAM: {required_ram:.0f} MB needed")

        if progress_callback:
            progress_callback(0, len(tracks), "extracting")
        self._fire('loading_progress', 0, len(tracks), "extracting")

        def combined_progress_cb(track_num, total_tracks, status):
            if progress_callback:
                progress_callback(track_num, total_tracks, status)
            self._fire('loading_progress', track_num, total_tracks, status)

        if not self.ripper.rip_to_ram(combined_progress_cb):
            logger.error("extraction failed")
            return (False, "extraction_error")

        logger.info("extraction done")

        if progress_callback:
            progress_callback(len(tracks), len(tracks), "complete")
        self._fire('loading_progress', len(tracks), len(tracks), "complete")

        self.cd_loaded = True
        self.is_direct_mode = False
        self.last_stop_time = 0.0
        self.stop_count = 0

        self.player = BitPerfectPlayer(
            data_provider=self.ripper.load_track_data,
            track_count=len(tracks)
        )
        self.player.on_track_end = self._on_track_end

        self.sequencer.set_total_tracks(len(tracks))

        self.transport.navigate_to(0, auto_play=False)
        self._preload_next()

        logger.info("cd loaded, ready")

        self._fire('cd_loaded', len(tracks))

        return (True, "ok")

    def _preload_next(self):
        next_idx = self.sequencer.get_next_for_preload()
        self.transport.prepare_next(next_idx if next_idx is not None else -1)

    def _on_track_end(self):
        new_idx = self.sequencer.advance()
        if new_idx is None:
            self.sequencer.goto(0)
            self.transport.navigate_to(0, auto_play=False)
            self._fire('status_change', 'disc_end')
            return

        if self.transport.get_current_track_index() == new_idx:
            logger.info(f"gapless → track {new_idx + 1}")
        else:
            self.transport.navigate_to(new_idx, auto_play=True)
            logger.info(f"redirect → track {new_idx + 1}")

        self._fire('track_change', new_idx + 1, self.get_total_tracks())
        self._preload_next()

    def play(self):
        if not self.cd_loaded:
            return
        self.transport.play()
        logger.info("[>] play")

    def pause(self):
        if self.transport.get_state() == PlayerState.PLAYING:
            self.transport.pause()
            logger.info("[||] pause")

    def stop(self):
        current_time = time.time()

        if current_time - self.last_stop_time < 3.0:
            self.stop_count += 1
            if self.stop_count >= 2:
                self.sequencer.goto(0)
                self.stop_count = 0
                self.transport.navigate_to(0, auto_play=False)
                self.transport.stop()
                self._fire('track_change', 1, self.get_total_tracks())
                logger.info("[stop] reset to track 1")
                return
        else:
            self.stop_count = 1

        self.last_stop_time = current_time

        self.transport.stop()
        logger.info("[stop]")

    def next(self):
        if not self.cd_loaded:
            return

        new_idx = self.sequencer.advance()
        if new_idx is None:
            return

        was_playing = self.transport.is_playing()
        self.transport.navigate_to(new_idx, auto_play=was_playing)
        self._fire('track_change', new_idx + 1, self.get_total_tracks())
        self._preload_next()
        logger.info(f"[>>] track {new_idx + 1}/{self.get_total_tracks()}")

    def prev(self):
        if not self.cd_loaded:
            return

        if self.transport.get_position() <= 2.0:
            prev_idx = self.sequencer.retreat()
            if prev_idx is not None:
                was_playing = self.transport.is_playing()
                self.transport.navigate_to(prev_idx, auto_play=was_playing)
                self._fire('track_change', prev_idx + 1, self.get_total_tracks())
                self._preload_next()
                logger.info(f"[<<] track {prev_idx + 1}/{self.get_total_tracks()}")
            else:
                self.transport.seek(0)
        else:
            self.transport.seek(0)

    def goto(self, track_num: int):
        if not self.cd_loaded:
            return

        total = self.get_total_tracks()
        if not (1 <= track_num <= total):
            return

        self.sequencer.goto(track_num - 1)
        was_playing = self.transport.is_playing()
        self.transport.navigate_to(track_num - 1, auto_play=was_playing)
        self._fire('track_change', track_num, total)
        self._preload_next()
        logger.info(f"[->] track {track_num}/{total}")

    def seek(self, position_seconds: float):
        self.transport.seek(position_seconds)

    def get_current_track_num(self) -> int:
        return self.sequencer.current_index + 1

    def get_total_tracks(self) -> int:
        return self.sequencer.total_tracks if self.cd_loaded else 0

    def get_track_info(self, track_num: int = None) -> Optional[CDTrack]:
        if not self.cd_loaded:
            return None
        if track_num is None:
            track_num = self.sequencer.current_index + 1
        return self.ripper.get_track_info(track_num)

    def get_disc_title(self) -> str:
        return self.ripper.disc_title if self.cd_loaded else ""

    def get_disc_artist(self) -> str:
        return self.ripper.disc_artist if self.cd_loaded else ""

    def get_current_track_title(self) -> str:
        track = self.get_track_info()
        return track.title if track and track.title else ""

    def get_current_track_artist(self) -> str:
        track = self.get_track_info()
        return track.artist if track and track.artist else ""

    def get_position(self) -> float:
        return self.transport.get_position()

    def get_duration(self) -> float:
        return self.transport.get_duration()

    def get_state(self) -> PlayerState:
        return self.transport.get_state()

    def is_cd_loaded(self) -> bool:
        return self.cd_loaded

    def get_all_tracks(self) -> list:
        return self.ripper.tracks if self.cd_loaded else []

    def get_total_duration(self) -> float:
        if not self.cd_loaded:
            return 0.0
        return sum(t.duration_seconds for t in self.ripper.tracks)

    def get_current_track_duration(self) -> float:
        track_info = self.get_track_info()
        if track_info:
            return track_info.duration_seconds
        return 0.0

    def get_track_remaining_time(self) -> float:
        duration = self.get_duration()
        position = self.get_position()
        remaining = duration - position
        return max(0.0, remaining)

    def get_disc_remaining_time(self) -> float:
        if not self.cd_loaded:
            return 0.0
        current_remaining = self.get_track_remaining_time()
        remaining_tracks_time = 0.0
        for i in range(self.sequencer.current_index + 1, len(self.ripper.tracks)):
            remaining_tracks_time += self.ripper.tracks[i].duration_seconds
        return current_remaining + remaining_tracks_time

    def get_disc_position(self) -> float:
        if not self.cd_loaded:
            return 0.0
        previous_tracks_time = sum(
            self.ripper.tracks[i].duration_seconds
            for i in range(self.sequencer.current_index)
        )
        current_position = self.get_position()
        return previous_tracks_time + current_position

    def get_ram_usage_mb(self) -> float:
        if not self.cd_loaded:
            return 0.0
        import os
        total_bytes = 0
        for track in self.ripper.tracks:
            filepath = self.ripper._get_track_filepath(track.number)
            if os.path.exists(filepath):
                total_bytes += os.path.getsize(filepath)
        return total_bytes / (1024 * 1024)

    def repeat(self) -> RepeatMode:
        mode = self.sequencer.cycle_repeat()
        return mode

    def shuffle(self) -> bool:
        if not self.cd_loaded:
            return False
        return self.sequencer.toggle_shuffle()

    def scan(self) -> tuple:
        self._wake_transport()

        tracks = self.ripper.read_toc()
        if not tracks:
            return (False, "no_disc")

        self.ripper.read_cdtext()
        logger.info(f"scan: {len(tracks)} tracks")
        return (True, "ok")

    def get_scanned_tracks(self) -> list:
        return self.ripper.tracks if self.ripper.tracks else []

    def verify_bit_perfect(self) -> dict:
        return self.player.verify_bit_perfect_config()

    def eject(self):
        self.transport.stop()

        if self.is_direct_mode and self.direct_player:
            self.direct_player.cleanup()
            self.direct_player = None
            self.is_direct_mode = False

        self.player.stop()
        self.ripper.cleanup()
        self.cd_loaded = False

        import subprocess
        try:
            subprocess.run(['eject', self.ripper.device], timeout=5)
        except Exception:
            logger.warning("eject failed")

        logger.info("ejected")

    def cleanup(self):
        if self.is_direct_mode and self.direct_player:
            self.direct_player.cleanup()
            self.direct_player = None
            self.is_direct_mode = False

        self.player.cleanup()
        self.ripper.cleanup()
        logger.debug("cleanup done")
