import random
import logging
from enum import Enum
from typing import Optional, List

logger = logging.getLogger(__name__)


class RepeatMode(Enum):
    OFF = 0
    TRACK = 1
    ALL = 2


class TrackSequencer:

    def __init__(self):
        self.repeat_mode: RepeatMode = RepeatMode.OFF
        self.shuffle_on: bool = False
        self._total_tracks: int = 0
        self._current_index: int = 0
        self._shuffle_playlist: List[int] = []
        self._shuffle_position: int = 0

    def set_total_tracks(self, count: int) -> None:
        self._total_tracks = count
        self._current_index = 0
        self._shuffle_playlist = []
        self._shuffle_position = 0
        self.shuffle_on = False
        self.repeat_mode = RepeatMode.OFF
        logger.debug(f"SEQ: {count} tracks")

    @property
    def total_tracks(self) -> int:
        return self._total_tracks

    @property
    def current_index(self) -> int:
        return self._current_index

    @current_index.setter
    def current_index(self, value: int) -> None:
        if 0 <= value < self._total_tracks:
            self._current_index = value
            if self.shuffle_on and self._shuffle_playlist:
                try:
                    self._shuffle_position = self._shuffle_playlist.index(value)
                except ValueError:
                    pass
            logger.debug(f"SEQ: index {value}")

    def next_track(self) -> Optional[int]:
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
        next_idx = self.next_track()
        if next_idx is not None:
            self._current_index = next_idx
            if self.shuffle_on and self.repeat_mode != RepeatMode.TRACK:
                self._shuffle_position += 1
                if self._shuffle_position >= len(self._shuffle_playlist):
                    self._shuffle_position = 0
            logger.debug(f"SEQ: → track {next_idx + 1}")
        return next_idx

    def retreat(self) -> Optional[int]:
        prev_idx = self.prev_track()
        if prev_idx is not None:
            self._current_index = prev_idx
            if self.shuffle_on:
                self._shuffle_position = max(0, self._shuffle_position - 1)
            logger.debug(f"SEQ: ← track {prev_idx + 1}")
        return prev_idx

    def goto(self, index: int) -> bool:
        if 0 <= index < self._total_tracks:
            self._current_index = index
            if self.shuffle_on and self._shuffle_playlist:
                try:
                    self._shuffle_position = self._shuffle_playlist.index(index)
                except ValueError:
                    pass
            logger.debug(f"SEQ: goto track {index + 1}")
            return True
        logger.warning(f"SEQ: invalid index {index}")
        return False

    def toggle_shuffle(self) -> bool:
        self.shuffle_on = not self.shuffle_on
        if self.shuffle_on:
            self._generate_shuffle_playlist()
            try:
                self._shuffle_position = self._shuffle_playlist.index(self._current_index)
            except ValueError:
                self._shuffle_position = 0
            logger.info(f"SEQ: shuffle ON {[i+1 for i in self._shuffle_playlist]}")
        else:
            self._shuffle_playlist = []
            self._shuffle_position = 0
            logger.info("SEQ: shuffle OFF")
        return self.shuffle_on

    def cycle_repeat(self) -> RepeatMode:
        if self.repeat_mode == RepeatMode.OFF:
            self.repeat_mode = RepeatMode.TRACK
        elif self.repeat_mode == RepeatMode.TRACK:
            self.repeat_mode = RepeatMode.ALL
        else:
            self.repeat_mode = RepeatMode.OFF
        logger.info(f"SEQ: repeat {self.repeat_mode.name}")
        return self.repeat_mode

    def reset(self) -> None:
        self._current_index = 0
        self._shuffle_position = 0
        if self.shuffle_on:
            self._generate_shuffle_playlist()
        logger.debug("SEQ: reset")

    def get_next_for_preload(self) -> Optional[int]:
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
        if self._total_tracks == 0:
            self._shuffle_playlist = []
            return
        self._shuffle_playlist = list(range(self._total_tracks))
        random.shuffle(self._shuffle_playlist)
        self._shuffle_position = 0
