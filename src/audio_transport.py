"""
Audio transport interface — polymorphic playback backend
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Callable
import logging

logger = logging.getLogger(__name__)


class PlayerState(Enum):
    STOPPED = 0
    PLAYING = 1
    PAUSED = 2


class AudioTransport(ABC):

    on_track_end: Optional[Callable[[], None]] = None

    @abstractmethod
    def play(self) -> None: pass

    @abstractmethod
    def pause(self) -> None: pass

    @abstractmethod
    def stop(self) -> None: pass

    @abstractmethod
    def seek(self, position_seconds: float) -> None: pass

    @abstractmethod
    def get_position(self) -> float: pass

    @abstractmethod
    def get_duration(self) -> float: pass

    @abstractmethod
    def get_state(self) -> PlayerState: pass

    def is_playing(self) -> bool:
        return self.get_state() == PlayerState.PLAYING

    def navigate_to(self, track_index: int, auto_play: bool = True) -> bool:
        """Navigate to track (0-based). Loads and optionally starts playback."""
        return False

    def prepare_next(self, track_index: int) -> None:
        """Prepare next track for gapless. -1 to clear. No-op by default."""
        pass

    @abstractmethod
    def get_current_track_index(self) -> int:
        """Current track index (0-based), or -1 if none loaded."""
        pass

    @abstractmethod
    def get_track_count(self) -> int: pass

    @abstractmethod
    def cleanup(self) -> None: pass
