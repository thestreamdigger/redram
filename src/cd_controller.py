import logging
import random
import time
from enum import Enum
from typing import Optional, Callable
from cd_ripper import CDRipper, CDTrack
from cd_player import BitPerfectPlayer, PlayerState
from cd_direct_player import DirectCDPlayer
from superdrive import SuperDriveController
import config

logger = logging.getLogger(__name__)


class RepeatMode(Enum):
    OFF = 0
    TRACK = 1
    ALL = 2


class CDPlayerController:

    def __init__(self):
        self.ripper = CDRipper()
        self.player = BitPerfectPlayer()
        self.superdrive = SuperDriveController(config.CD_DEVICE)
        self.superdrive.detect()

        self.direct_player: Optional[DirectCDPlayer] = None
        self.is_direct_mode: bool = False

        self.current_track_idx: int = 0
        self.cd_loaded: bool = False
        self.last_stop_time: float = 0.0
        self.stop_count: int = 0

        self.repeat_mode: RepeatMode = RepeatMode.OFF
        self.shuffle_on: bool = False
        self.shuffle_playlist: list = []
        self.shuffle_position: int = 0

        self.on_track_change: Optional[Callable] = None
        self.on_cd_loaded: Optional[Callable] = None
        self.on_status_change: Optional[Callable] = None
        self.on_loading_progress: Optional[Callable] = None

        self._transitioning: bool = False
        self._transition_was_playing: bool = False

        self.player.on_track_end = self._on_track_end

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
        self.current_track_idx = 0

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
        self.current_track_idx = 0
        self.last_stop_time = 0.0
        self.stop_count = 0

        self.shuffle_on = False
        self.shuffle_playlist = []
        self.shuffle_position = 0
        self.repeat_mode = RepeatMode.OFF

        self._load_current_track()

        logger.info("cd loaded and ready")

        if self.on_cd_loaded:
            self.on_cd_loaded(len(tracks))

        return (True, "ok")

    def _load_current_track(self):
        if not self.cd_loaded:
            return

        track_num = self.current_track_idx + 1
        pcm_data = self.ripper.load_track_data(track_num)

        if pcm_data:
            logger.info(f"track {track_num} PCM data: {len(pcm_data)} bytes")
            self.player.load_track(pcm_data)
            logger.info(f"track {track_num} loaded in player")
            if self.on_track_change:
                self.on_track_change(track_num, self.get_total_tracks())

            if self.current_track_idx < len(self.ripper.tracks) - 1:
                next_track_num = track_num + 1
                next_pcm_data = self.ripper.load_track_data(next_track_num)
                if next_pcm_data:
                    self.player.preload_next_track(next_pcm_data)
                    logger.info(f"preloaded track {next_track_num} for gapless")
        else:
            logger.error(f"ERROR: track {track_num} has no PCM data!")

    def _on_track_end(self):
        logger.info("track finished")

        if self.repeat_mode == RepeatMode.TRACK:
            logger.info("[repeat track] restarting current track")
            self._load_current_track()
            if self.on_track_change:
                self.on_track_change(self.current_track_idx + 1, self.get_total_tracks())
            return

        if self.shuffle_on:
            self.shuffle_position += 1
            if self.shuffle_position >= len(self.shuffle_playlist):
                if self.repeat_mode == RepeatMode.ALL:
                    logger.info("[shuffle + repeat all] re-shuffling playlist")
                    self._generate_shuffle_playlist()
                    self.shuffle_position = 0
                    self.current_track_idx = self.shuffle_playlist[self.shuffle_position]
                else:
                    logger.info("[shuffle] end of playlist - resetting to track 1")
                    self.shuffle_position = 0
                    self.current_track_idx = 0
                    self._load_current_track()
                    if self.on_status_change:
                        self.on_status_change("disc_end")
                    return
            else:
                self.current_track_idx = self.shuffle_playlist[self.shuffle_position]
        else:
            self.current_track_idx += 1

            if self.current_track_idx >= len(self.ripper.tracks):
                if self.repeat_mode == RepeatMode.ALL:
                    logger.info("[repeat all] restarting from track 1")
                    self.current_track_idx = 0
                else:
                    logger.info("end of disc reached - resetting to track 1")
                    self.current_track_idx = 0
                    self._load_current_track()
                    if self.on_status_change:
                        self.on_status_change("disc_end")
                    return

        logger.info(f"[>>] now playing track {self.current_track_idx + 1}")

        if self.on_track_change:
            self.on_track_change(self.current_track_idx + 1, self.get_total_tracks())

        next_idx = self._get_next_track_index()
        if next_idx is not None:
            next_track_num = next_idx + 1
            pcm_data = self.ripper.load_track_data(next_track_num)
            if pcm_data:
                self.player.preload_next_track(pcm_data)
                logger.info(f"preloaded track {next_track_num} for gapless")
        else:
            logger.info("last track playing - no next track to preload")
            if self.on_status_change:
                self.on_status_change("last_track")

    def _on_streaming_track_end(self):
        if not self.is_direct_mode or not self.direct_player:
            return

        current = self.direct_player.get_current_track()
        total = len(self.direct_player.tracks)

        logger.info(f"streaming: track {current} ended, total={total}")

        if self.repeat_mode == RepeatMode.TRACK:
            logger.info(f"streaming: repeating track {current}")
            self.direct_player.play_track(current)
            return

        if current < total:
            next_track = current + 1
            logger.info(f"streaming: auto-advancing to track {next_track}")
            self.current_track_idx = next_track - 1
            self.direct_player.play_track(next_track)

            if self.on_track_change:
                self.on_track_change(next_track, total)
        else:
            if self.repeat_mode == RepeatMode.ALL:
                logger.info("streaming: repeat all - restarting from track 1")
                self.current_track_idx = 0
                self.direct_player.play_track(1)
                if self.on_track_change:
                    self.on_track_change(1, total)
            else:
                logger.info("streaming: disc ended")
                self.current_track_idx = 0
                if self.on_status_change:
                    self.on_status_change("disc_end")

    def play(self):
        if not self.cd_loaded:
            logger.warning("cd not loaded")
            return

        if self.is_direct_mode:
            if self.direct_player:
                if self.direct_player.get_state() == 'paused':
                    self.direct_player.resume()
                    logger.info("[>] play (resuming streaming)")
                else:
                    track_num = self.current_track_idx + 1
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
        if self.is_direct_mode:
            if self.direct_player and self.direct_player.get_state() == 'playing':
                self.direct_player.pause()
                logger.info("[||] pause (streaming)")
        else:
            if self.player.get_state() == PlayerState.PLAYING:
                self.player.pause()
                logger.info("[||] pause")
            else:
                logger.debug("already paused/stopped")

    def stop(self):
        current_time = time.time()

        if current_time - self.last_stop_time < 3.0:
            self.stop_count += 1
            if self.stop_count >= 2:
                self.current_track_idx = 0
                self.stop_count = 0

                if self.is_direct_mode:
                    if self.direct_player:
                        self.direct_player.play_track(1)
                        self.direct_player.stop()
                        logger.info("[stop] double stop - returning to track 1 (streaming)")
                else:
                    self._load_current_track()
                    self.player.stop()
                    logger.info("[stop] double stop - returning to track 1")

                if self.on_track_change:
                    self.on_track_change(1, self.get_total_tracks())
                return
        else:
            self.stop_count = 1

        self.last_stop_time = current_time

        if self.is_direct_mode:
            if self.direct_player:
                self.direct_player.stop()
                logger.info("[stop] stop (streaming)")
        else:
            self.player.stop()
            logger.info("[stop] stop - at beginning of current track")

    def next(self):
        if not self.cd_loaded:
            return

        if self.is_direct_mode:
            if self.direct_player:
                self.direct_player.next_track()
                self.current_track_idx = self.direct_player.get_current_track() - 1
                if self.on_track_change:
                    self.on_track_change(self.current_track_idx + 1, self.get_total_tracks())
                logger.info(f"[>>] track {self.current_track_idx + 1} (streaming)")
            return

        was_playing = self.player.is_playing()

        self._transitioning = True
        self._transition_was_playing = was_playing

        self.player.stop()

        if self.shuffle_on:
            self.shuffle_position += 1
            if self.shuffle_position >= len(self.shuffle_playlist):
                if self.repeat_mode == RepeatMode.ALL:
                    self._generate_shuffle_playlist()
                    self.shuffle_position = 0
                else:
                    self.shuffle_position = len(self.shuffle_playlist) - 1
                    logger.info("already at end of shuffle playlist")
                    self._transitioning = False
                    return

            self.current_track_idx = self.shuffle_playlist[self.shuffle_position]
        else:
            if self.current_track_idx < len(self.ripper.tracks) - 1:
                self.current_track_idx += 1
            else:
                logger.info("already at last track")
                self._transitioning = False
                return

        self._load_current_track()

        if was_playing:
            self.player.play()

        self._transitioning = False
        logger.info(f"[>>] track {self.current_track_idx + 1}")

    def prev(self):
        if not self.cd_loaded:
            return

        if self.is_direct_mode:
            if self.direct_player:
                self.direct_player.prev_track()
                self.current_track_idx = self.direct_player.get_current_track() - 1
                if self.on_track_change:
                    self.on_track_change(self.current_track_idx + 1, self.get_total_tracks())
                logger.info(f"[<<] track {self.current_track_idx + 1} (streaming)")
            return

        current_position = self.player.get_position()

        if current_position <= 2.0:
            was_playing = self.player.is_playing()

            self._transitioning = True
            self._transition_was_playing = was_playing

            self.player.stop()

            if self.shuffle_on:
                if self.shuffle_position > 0:
                    self.shuffle_position -= 1
                    self.current_track_idx = self.shuffle_playlist[self.shuffle_position]
                    self._load_current_track()
                else:
                    logger.info("already at first track in shuffle playlist")
                    self.player.seek(0)
            else:
                if self.current_track_idx > 0:
                    self.current_track_idx -= 1
                    self._load_current_track()
                else:
                    logger.info("already at first track")
                    self.player.seek(0)

            if was_playing:
                self.player.play()

            self._transitioning = False
            logger.info(f"[<<] track {self.current_track_idx + 1}")
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

        if 1 <= track_num <= len(self.ripper.tracks):
            was_playing = self.player.is_playing()
            self.player.stop()

            self.current_track_idx = track_num - 1
            self._load_current_track()

            if was_playing:
                self.player.play()

            logger.info(f"[->] track {track_num}")
        else:
            logger.warning(f"track {track_num} invalid (1-{len(self.ripper.tracks)})")

    def seek(self, position_seconds: float):
        self.player.seek(position_seconds)

    def get_current_track_num(self) -> int:
        if self.is_direct_mode and self.direct_player:
            return self.direct_player.get_current_track()
        return self.current_track_idx + 1

    def get_total_tracks(self) -> int:
        if self.is_direct_mode and self.direct_player:
            return len(self.direct_player.tracks)
        return len(self.ripper.tracks) if self.cd_loaded else 0

    def get_track_info(self, track_num: int = None) -> Optional[CDTrack]:
        if not self.cd_loaded:
            return None
        if track_num is None:
            track_num = self.current_track_idx + 1
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
        if self.is_direct_mode and self.direct_player:
            return self.direct_player.get_position()
        return self.player.get_position()

    def get_duration(self) -> float:
        if self.is_direct_mode and self.direct_player:
            return self.direct_player.get_duration()
        return self.player.get_duration()

    def get_state(self) -> PlayerState:
        if self.is_direct_mode and self.direct_player:
            state = self.direct_player.get_state()
            if state == 'playing':
                return PlayerState.PLAYING
            elif state == 'paused':
                return PlayerState.PAUSED
            else:
                return PlayerState.STOPPED
        return self.player.get_state()

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
        for i in range(self.current_track_idx + 1, len(self.ripper.tracks)):
            remaining_tracks_time += self.ripper.tracks[i].duration_seconds
        return current_remaining + remaining_tracks_time

    def get_disc_position(self) -> float:
        if not self.cd_loaded:
            return 0.0
        previous_tracks_time = sum(
            self.ripper.tracks[i].duration_seconds
            for i in range(self.current_track_idx)
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

    def _get_next_track_index(self) -> Optional[int]:
        if self.repeat_mode == RepeatMode.TRACK:
            return self.current_track_idx

        if self.shuffle_on:
            next_pos = self.shuffle_position + 1
            if next_pos >= len(self.shuffle_playlist):
                if self.repeat_mode == RepeatMode.ALL:
                    return self.shuffle_playlist[0]
                else:
                    return None
            return self.shuffle_playlist[next_pos]
        else:
            next_idx = self.current_track_idx + 1
            if next_idx >= len(self.ripper.tracks):
                if self.repeat_mode == RepeatMode.ALL:
                    return 0
                else:
                    return None
            return next_idx

    def _generate_shuffle_playlist(self):
        if not self.cd_loaded:
            return
        self.shuffle_playlist = list(range(len(self.ripper.tracks)))
        random.shuffle(self.shuffle_playlist)
        self.shuffle_position = 0
        logger.info(f"shuffle playlist generated: {[i+1 for i in self.shuffle_playlist]}")

    def repeat(self) -> RepeatMode:
        if self.repeat_mode == RepeatMode.OFF:
            self.repeat_mode = RepeatMode.TRACK
        elif self.repeat_mode == RepeatMode.TRACK:
            self.repeat_mode = RepeatMode.ALL
        else:
            self.repeat_mode = RepeatMode.OFF
        logger.info(f"repeat mode: {self.repeat_mode.name}")
        return self.repeat_mode

    def shuffle(self) -> bool:
        if not self.cd_loaded:
            logger.warning("no cd loaded - cannot enable shuffle")
            return False

        self.shuffle_on = not self.shuffle_on

        if self.shuffle_on:
            self._generate_shuffle_playlist()
            try:
                self.shuffle_position = self.shuffle_playlist.index(self.current_track_idx)
            except ValueError:
                self.shuffle_position = 0
            logger.info(f"shuffle ON (current track at position {self.shuffle_position})")
        else:
            logger.info("shuffle OFF")
            self.shuffle_playlist = []
            self.shuffle_position = 0

        return self.shuffle_on

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
        self.current_track_idx = 0

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
