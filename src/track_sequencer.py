"""
Track Sequencer for RedRAM CD Player.

This module provides mode-independent track sequencing with shuffle and repeat
support. The TrackSequencer handles all navigation logic (next, prev, goto)
independently of the playback backend (RAM or streaming).

All indexing is 0-based internally. The controller converts to 1-based for display.
"""

import random
import logging
from enum import Enum
from typing import Optional, List

logger = logging.getLogger(__name__)


class RepeatMode(Enum):
    """
    Repeat mode for track sequencing.

    OFF: Stop at end of disc
    TRACK: Repeat current track infinitely
    ALL: Loop entire disc (or shuffle playlist) infinitely
    """
    OFF = 0
    TRACK = 1
    ALL = 2


class TrackSequencer:
    """
    Mode-independent track sequencing with shuffle and repeat support.

    Uses 0-based indexing internally. All public methods accept and return
    0-based indices. The controller converts to 1-based for display.

    Usage:
        sequencer = TrackSequencer()
        sequencer.set_total_tracks(12)  # CD with 12 tracks

        # Navigation
        next_idx = sequencer.next_track()  # Get next track (doesn't advance)
        sequencer.advance()  # Move to next and return new index

        # Modes
        sequencer.toggle_shuffle()  # Enable/disable shuffle
        sequencer.cycle_repeat()  # Cycle OFF -> TRACK -> ALL -> OFF
    """

    def __init__(self):
        self.repeat_mode: RepeatMode = RepeatMode.OFF
        self.shuffle_on: bool = False
        self._total_tracks: int = 0
        self._current_index: int = 0
        self._shuffle_playlist: List[int] = []
        self._shuffle_position: int = 0

    def set_total_tracks(self, count: int) -> None:
        """
        Initialize sequencer with track count.

        Resets all state: current position, shuffle playlist, modes.

        Args:
            count: Total number of tracks on disc.
        """
        self._total_tracks = count
        self._current_index = 0
        self._shuffle_playlist = []
        self._shuffle_position = 0
        self.shuffle_on = False
        self.repeat_mode = RepeatMode.OFF
        logger.debug(f"SEQUENCER: initialized with {count} tracks")

    @property
    def total_tracks(self) -> int:
        """Get total track count."""
        return self._total_tracks

    @property
    def current_index(self) -> int:
        """Get current track index (0-based)."""
        return self._current_index

    @current_index.setter
    def current_index(self, value: int) -> None:
        """
        Set current track index (0-based).

        Also updates shuffle position if shuffle is enabled.
        """
        if 0 <= value < self._total_tracks:
            self._current_index = value
            if self.shuffle_on and self._shuffle_playlist:
                try:
                    self._shuffle_position = self._shuffle_playlist.index(value)
                except ValueError:
                    pass
            logger.debug(f"SEQUENCER: current_index set to {value}")

    def next_track(self) -> Optional[int]:
        """
        Compute next track index based on current mode.

        Does NOT modify current_index - caller decides whether to apply.

        Returns:
            Next track index (0-based), or None if at end of sequence.
        """
        if self._total_tracks == 0:
            return None

        if self.repeat_mode == RepeatMode.TRACK:
            return self._current_index

        if self.shuffle_on:
            next_pos = self._shuffle_position + 1
            if next_pos >= len(self._shuffle_playlist):
                if self.repeat_mode == RepeatMode.ALL:
                    self._generate_shuffle_playlist()
                    return self._shuffle_playlist[0] if self._shuffle_playlist else None
                return None
            return self._shuffle_playlist[next_pos]
        else:
            next_idx = self._current_index + 1
            if next_idx >= self._total_tracks:
                if self.repeat_mode == RepeatMode.ALL:
                    return 0
                return None
            return next_idx

    def prev_track(self) -> Optional[int]:
        """
        Compute previous track index based on current mode.

        Does NOT modify current_index - caller decides whether to apply.

        Returns:
            Previous track index (0-based), or None if at beginning.
        """
        if self._total_tracks == 0:
            return None

        if self.shuffle_on and self._shuffle_playlist:
            if self._shuffle_position > 0:
                return self._shuffle_playlist[self._shuffle_position - 1]
            return None
        else:
            if self._current_index > 0:
                return self._current_index - 1
            return None

    def advance(self) -> Optional[int]:
        """
        Move to next track and return new index.

        Returns:
            New track index (0-based), or None if at end (disc_end).
        """
        next_idx = self.next_track()
        if next_idx is not None:
            self._current_index = next_idx
            if self.shuffle_on and self.repeat_mode != RepeatMode.TRACK:
                self._shuffle_position += 1
                if self._shuffle_position >= len(self._shuffle_playlist):
                    self._shuffle_position = 0
            logger.debug(f"SEQUENCER: advanced to track {next_idx + 1}")
        return next_idx

    def retreat(self) -> Optional[int]:
        """
        Move to previous track and return new index.

        Returns:
            New track index (0-based), or None if at beginning.
        """
        prev_idx = self.prev_track()
        if prev_idx is not None:
            self._current_index = prev_idx
            if self.shuffle_on:
                self._shuffle_position = max(0, self._shuffle_position - 1)
            logger.debug(f"SEQUENCER: retreated to track {prev_idx + 1}")
        return prev_idx

    def goto(self, index: int) -> bool:
        """
        Jump to specific track (0-based).

        Args:
            index: Target track index (0-based).

        Returns:
            True if jump successful, False if index invalid.
        """
        if 0 <= index < self._total_tracks:
            self._current_index = index
            if self.shuffle_on and self._shuffle_playlist:
                try:
                    self._shuffle_position = self._shuffle_playlist.index(index)
                except ValueError:
                    pass
            logger.debug(f"SEQUENCER: goto track {index + 1}")
            return True
        logger.warning(f"SEQUENCER: invalid track index {index}")
        return False

    def toggle_shuffle(self) -> bool:
        """
        Toggle shuffle mode.

        When enabling, generates new shuffle playlist and finds current track's
        position in the shuffled order.

        Returns:
            New shuffle state (True = enabled).
        """
        self.shuffle_on = not self.shuffle_on
        if self.shuffle_on:
            self._generate_shuffle_playlist()
            try:
                self._shuffle_position = self._shuffle_playlist.index(self._current_index)
            except ValueError:
                self._shuffle_position = 0
            logger.info(f"SEQUENCER: shuffle ON, playlist: {[i+1 for i in self._shuffle_playlist]}")
        else:
            self._shuffle_playlist = []
            self._shuffle_position = 0
            logger.info("SEQUENCER: shuffle OFF")
        return self.shuffle_on

    def cycle_repeat(self) -> RepeatMode:
        """
        Cycle through repeat modes: OFF -> TRACK -> ALL -> OFF.

        Returns:
            New repeat mode.
        """
        if self.repeat_mode == RepeatMode.OFF:
            self.repeat_mode = RepeatMode.TRACK
        elif self.repeat_mode == RepeatMode.TRACK:
            self.repeat_mode = RepeatMode.ALL
        else:
            self.repeat_mode = RepeatMode.OFF
        logger.info(f"SEQUENCER: repeat mode: {self.repeat_mode.name}")
        return self.repeat_mode

    def reset(self) -> None:
        """
        Reset to track 0.

        If shuffle is enabled, regenerates the shuffle playlist.
        """
        self._current_index = 0
        self._shuffle_position = 0
        if self.shuffle_on:
            self._generate_shuffle_playlist()
        logger.debug("SEQUENCER: reset to track 1")

    def get_next_for_preload(self) -> Optional[int]:
        """
        Get next track index for preloading (gapless playback).

        Similar to next_track() but specifically for preload logic.

        Returns:
            Track index to preload, or None if no preload needed.
        """
        if self.repeat_mode == RepeatMode.TRACK:
            return self._current_index

        if self.shuffle_on and self._shuffle_playlist:
            next_pos = self._shuffle_position + 1
            if next_pos < len(self._shuffle_playlist):
                return self._shuffle_playlist[next_pos]
            elif self.repeat_mode == RepeatMode.ALL:
                return self._shuffle_playlist[0]
            return None
        else:
            next_idx = self._current_index + 1
            if next_idx < self._total_tracks:
                return next_idx
            elif self.repeat_mode == RepeatMode.ALL:
                return 0
            return None

    def _generate_shuffle_playlist(self) -> None:
        """Generate new random ordering of all tracks."""
        if self._total_tracks == 0:
            self._shuffle_playlist = []
            return
        self._shuffle_playlist = list(range(self._total_tracks))
        random.shuffle(self._shuffle_playlist)
        self._shuffle_position = 0
