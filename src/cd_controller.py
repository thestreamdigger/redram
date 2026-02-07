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
        self.player = BitPerfectPlayer()
        self.superdrive = SuperDriveController(config.CD_DEVICE)
        self.superdrive.detect()

        self.direct_player: Optional[DirectCDPlayer] = None
        self.is_direct_mode: bool = False

        self.sequencer = TrackSequencer()

        self.cd_loaded: bool = False
        self.last_stop_time: float = 0.0
        self.stop_count: int = 0

        self.on_track_change: Optional[Callable] = None
        self.on_cd_loaded: Optional[Callable] = None
        self.on_status_change: Optional[Callable] = None
        self.on_loading_progress: Optional[Callable] = None

        self._transitioning: bool = False
        self._transition_was_playing: bool = False

        self.player.on_track_end = self._on_track_end

    @property
    def transport(self):
        """Get the active audio transport (BitPerfectPlayer or DirectCDPlayer)."""
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
            if self.on_loading_progress:
                self.on_loading_progress(0, 0, "waking")
            self.superdrive.enable()

    def load(self, progress_callback: Optional[Callable] = None, extraction_level: int = None) -> tuple:
        logger.info("starting cd load")

        level = extraction_level if extraction_level is not None else config.DEFAULT_EXTRACTION_LEVEL

        if level == 0:
            return self._load_streaming_mode(progress_callback)

        return self._load_ram_mode(progress_callback, level)

    def _load_streaming_mode(self, progress_callback: Optional[Callable] = None) -> tuple:
        logger.info("loading in streaming mode (level 0)")

        self._wake_transport(progress_callback)

        if progress_callback:
            progress_callback(0, 0, "detecting")
        if self.on_loading_progress:
            self.on_loading_progress(0, 0, "detecting")

        success, status = self.scan()
        if not success:
            return (False, status)

        tracks = self.get_scanned_tracks()
        logger.info(f"streaming mode: {len(tracks)} tracks detected")

        self.direct_player = DirectCDPlayer(tracks=tracks)
        self.direct_player.on_track_end = self._on_streaming_track_end
        self.is_direct_mode = True
        self.cd_loaded = True

        self.sequencer.set_total_tracks(len(tracks))

        logger.info("streaming mode: ready")

        if progress_callback:
            progress_callback(len(tracks), len(tracks), "complete")
        if self.on_loading_progress:
            self.on_loading_progress(len(tracks), len(tracks), "complete")

        if self.on_cd_loaded:
            self.on_cd_loaded(len(tracks))

        return (True, "streaming")

    def _load_ram_mode(self, progress_callback: Optional[Callable] = None, extraction_level: int = None) -> tuple:
        logger.info(f"loading in RAM mode (level {extraction_level})")

        if extraction_level is not None:
            self.ripper.set_extraction_level(extraction_level)

        self._wake_transport(progress_callback)

        if progress_callback:
            progress_callback(0, 0, "detecting")
        if self.on_loading_progress:
            self.on_loading_progress(0, 0, "detecting")

        if not self.ripper.detect_cd():
            logger.info("no cd")
            return (False, "no_disc")

        logger.info("cd detected")

        if progress_callback:
            progress_callback(0, 0, "reading_toc")
        if self.on_loading_progress:
            self.on_loading_progress(0, 0, "reading_toc")

        tracks = self.ripper.read_toc()
        if not tracks:
            logger.error("failed to read toc")
            return (False, "read_error")

        self.ripper.read_cdtext()
        logger.info(f"toc read: {len(tracks)} tracks")

        total_duration = sum(t.duration_seconds for t in tracks)
        required_ram = config.estimate_cd_ram_usage_mb(total_duration)
        ram_ok, available_ram, ram_msg = config.check_ram_availability(required_ram)

        if not ram_ok:
            logger.error(f"RAM check failed: {ram_msg}")
            if progress_callback:
                progress_callback(0, 0, "error")
            if self.on_loading_progress:
                self.on_loading_progress(0, 0, "error")
            return (False, "ram_error")

        logger.debug(f"RAM check OK: {required_ram:.0f} MB")

        if progress_callback:
            progress_callback(0, len(tracks), "extracting")
        if self.on_loading_progress:
            self.on_loading_progress(0, len(tracks), "extracting")

        def combined_progress_cb(track_num, total_tracks, status):
            if progress_callback:
                progress_callback(track_num, total_tracks, status)
            if self.on_loading_progress:
                self.on_loading_progress(track_num, total_tracks, status)

        if not self.ripper.rip_to_ram(combined_progress_cb):
            logger.error("extraction failed")
            return (False, "extraction_error")

        logger.info("extraction complete")

        if progress_callback:
            progress_callback(len(tracks), len(tracks), "complete")
        if self.on_loading_progress:
            self.on_loading_progress(len(tracks), len(tracks), "complete")

        self.cd_loaded = True
        self.is_direct_mode = False
        self.last_stop_time = 0.0
        self.stop_count = 0

        self.sequencer.set_total_tracks(len(tracks))

        self._load_and_preload()

        logger.info("cd loaded and ready")

        if self.on_cd_loaded:
            self.on_cd_loaded(len(tracks))

        return (True, "ok")

    def _load_and_preload(self):
        """Load current track into player and preload next per sequencer."""
        if not self.cd_loaded:
            return
        track_num = self.sequencer.current_index + 1
        pcm_data = self.ripper.load_track_data(track_num)
        if pcm_data:
            self.player.load_pcm_data(pcm_data)
            if self.on_track_change:
                self.on_track_change(track_num, self.get_total_tracks())
            self._preload_next()

    def _preload_next(self):
        """Preload next track per sequencer for gapless."""
        next_idx = self.sequencer.get_next_for_preload()
        if next_idx is not None:
            pcm_data = self.ripper.load_track_data(next_idx + 1)
            if pcm_data:
                self.player.preload_next_track(pcm_data)
        else:
            self.player.preload_next_track(None)

    def _on_track_end(self):
        logger.info("track finished")
        new_idx = self.sequencer.advance()
        if new_idx is None:
            self.sequencer.goto(0)
            if self.on_status_change:
                self.on_status_change("disc_end")
            return
        if self.on_track_change:
            self.on_track_change(new_idx + 1, self.get_total_tracks())
        self._preload_next()

    def _on_streaming_track_end(self):
        if not self.is_direct_mode or not self.direct_player:
            return
        self.sequencer.current_index = self.direct_player.get_current_track() - 1
        new_idx = self.sequencer.advance()
        if new_idx is None:
            self.sequencer.goto(0)
            if self.on_status_change:
                self.on_status_change("disc_end")
            return
        self.direct_player.play_track(new_idx + 1)
        if self.on_track_change:
            self.on_track_change(new_idx + 1, len(self.direct_player.tracks))

    def play(self):
        if not self.cd_loaded:
            logger.warning("cd not loaded")
            return

        if self.is_direct_mode:
            if self.direct_player:
                if self.direct_player.get_state() == PlayerState.PAUSED:
                    self.direct_player.resume()
                    logger.info("[>] play (resuming streaming)")
                else:
                    track_num = self.sequencer.current_index + 1
                    self.direct_player.play_track(track_num)
                    logger.info("[>] play (streaming)")
        else:
            if self.player.get_state() == PlayerState.PAUSED:
                self.player.play()
                logger.info("[>] play (resuming)")
            elif self.player.get_state() == PlayerState.STOPPED:
                self.player.play()
                logger.info("[>] play")
            else:
                logger.debug("already playing")

    def pause(self):
        if self.transport.get_state() == PlayerState.PLAYING:
            self.transport.pause()
            logger.info("[||] pause")
        else:
            logger.debug("already paused/stopped")

    def stop(self):
        current_time = time.time()

        if current_time - self.last_stop_time < 3.0:
            self.stop_count += 1
            if self.stop_count >= 2:
                self.sequencer.goto(0)
                self.stop_count = 0

                if self.is_direct_mode:
                    if self.direct_player:
                        self.direct_player.play_track(1)
                        self.direct_player.stop()
                        logger.info("[stop] double stop - returning to track 1 (streaming)")
                else:
                    self._load_and_preload()
                    self.player.stop()
                    logger.info("[stop] double stop - returning to track 1")

                if self.on_track_change:
                    self.on_track_change(1, self.get_total_tracks())
                return
        else:
            self.stop_count = 1

        self.last_stop_time = current_time

        self.transport.stop()
        logger.info("[stop] stop")

    def next(self):
        if not self.cd_loaded:
            return

        new_idx = self.sequencer.advance()
        if new_idx is None:
            logger.info("already at last track")
            return

        if self.is_direct_mode:
            if self.direct_player:
                self.direct_player.play_track(new_idx + 1)
                if self.on_track_change:
                    self.on_track_change(new_idx + 1, self.get_total_tracks())
                logger.info(f"[>>] track {new_idx + 1} (streaming)")
            return

        was_playing = self.player.is_playing()
        self.player.stop()
        self._load_and_preload()

        if was_playing:
            self.player.play()

        logger.info(f"[>>] track {new_idx + 1}")

    def prev(self):
        if not self.cd_loaded:
            return

        if self.is_direct_mode:
            if self.direct_player:
                prev_idx = self.sequencer.retreat()
                if prev_idx is not None:
                    self.direct_player.play_track(prev_idx + 1)
                    if self.on_track_change:
                        self.on_track_change(prev_idx + 1, self.get_total_tracks())
                    logger.info(f"[<<] track {prev_idx + 1} (streaming)")
            return

        current_position = self.player.get_position()

        if current_position <= 2.0:
            prev_idx = self.sequencer.retreat()
            if prev_idx is not None:
                was_playing = self.player.is_playing()
                self.player.stop()
                self._load_and_preload()
                if was_playing:
                    self.player.play()
                logger.info(f"[<<] track {prev_idx + 1}")
            else:
                logger.info("already at first track")
                self.player.seek(0)
        else:
            was_playing = self.player.is_playing()
            self.player.stop()
            self.player.seek(0)
            if was_playing:
                self.player.play()
            logger.info("[<<] restarting current track")

    def goto(self, track_num: int):
        if not self.cd_loaded:
            return

        total = self.get_total_tracks()
        if not (1 <= track_num <= total):
            logger.warning(f"track {track_num} invalid (1-{total})")
            return

        self.sequencer.goto(track_num - 1)

        if self.is_direct_mode and self.direct_player:
            self.direct_player.play_track(track_num)
            if self.on_track_change:
                self.on_track_change(track_num, total)
            logger.info(f"[->] track {track_num} (streaming)")
        else:
            was_playing = self.player.is_playing()
            self.player.stop()
            self._load_and_preload()

            if was_playing:
                self.player.play()

            logger.info(f"[->] track {track_num}")

    def seek(self, position_seconds: float):
        self.player.seek(position_seconds)

    def get_current_track_num(self) -> int:
        if self.is_direct_mode and self.direct_player:
            return self.direct_player.get_current_track()
        return self.sequencer.current_index + 1

    def get_total_tracks(self) -> int:
        if self.is_direct_mode and self.direct_player:
            return len(self.direct_player.tracks)
        return len(self.ripper.tracks) if self.cd_loaded else 0

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
        """Cycle through repeat modes: OFF -> TRACK -> ALL -> OFF."""
        mode = self.sequencer.cycle_repeat()
        return mode

    def shuffle(self) -> bool:
        """Toggle shuffle mode."""
        if not self.cd_loaded:
            logger.warning("no cd loaded - cannot enable shuffle")
            return False

        return self.sequencer.toggle_shuffle()

    def scan(self) -> tuple:
        logger.info("scanning cd (quick toc read)")
        self._wake_transport()

        tracks = self.ripper.read_toc()
        if not tracks:
            logger.info("no cd or read error")
            return (False, "no_disc")

        self.ripper.read_cdtext()
        logger.info(f"toc read: {len(tracks)} tracks")
        return (True, "ok")

    def get_scanned_tracks(self) -> list:
        return self.ripper.tracks if self.ripper.tracks else []

    def verify_bit_perfect(self) -> dict:
        return self.player.verify_bit_perfect_config()

    def eject(self):
        logger.info("ejecting cd...")

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
            logger.warning("could not eject automatically")

        logger.info("cd ejected")

    def cleanup(self):
        if self.is_direct_mode and self.direct_player:
            self.direct_player.cleanup()
            self.direct_player = None
            self.is_direct_mode = False

        self.player.cleanup()
        self.ripper.cleanup()
        logger.info("cleanup complete")
