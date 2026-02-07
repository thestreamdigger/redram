"""
Audio Transport Interface for RedRAM CD Player.

This module defines the common interface (AudioTransport) that all playback
implementations must follow, enabling polymorphic transport selection without
conditional branching in the controller.

The PlayerState enum provides unified state representation across all transports.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Callable
import logging

logger = logging.getLogger(__name__)


class PlayerState(Enum):
    """
    Unified player state enum for all transport implementations.

    All transports must use this enum internally and return it from get_state().
    This eliminates the string vs enum inconsistency between implementations.
    """
    STOPPED = 0
    PLAYING = 1
    PAUSED = 2


class AudioTransport(ABC):
    """
    Abstract base class for audio playback transports.

    All implementations must:
    - Use PlayerState enum for state representation
    - Use 0-based track indexing internally
    - Implement all abstract methods
    - Call on_track_end callback when track playback completes

    The controller handles conversion to 1-based indexing for display.

    Implementations:
    - BitPerfectPlayer: ALSA-based RAM playback (cd_player.py)
    - DirectCDPlayer: MPV-based streaming playback (cd_direct_player.py)
    """

    on_track_end: Optional[Callable[[], None]] = None

    @abstractmethod
    def play(self) -> None:
        """
        Start or resume playback.

        If paused, resumes from current position.
        If stopped, starts from beginning of loaded track.
        """
        pass

    @abstractmethod
    def pause(self) -> None:
        """
        Pause playback, maintaining current position.

        Has no effect if already paused or stopped.
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """
        Stop playback and reset position to beginning.

        After stop(), get_position() should return 0.
        """
        pass

    @abstractmethod
    def seek(self, position_seconds: float) -> None:
        """
        Seek to absolute position within current track.

        Args:
            position_seconds: Target position in seconds from track start.

        Note: Some implementations may have limited seek support.
        """
        pass

    @abstractmethod
    def get_position(self) -> float:
        """
        Get current playback position in seconds.

        Returns:
            Position in seconds from start of current track.
            Returns 0.0 if stopped or no track loaded.
        """
        pass

    @abstractmethod
    def get_duration(self) -> float:
        """
        Get duration of current track in seconds.

        Returns:
            Duration in seconds, or 0.0 if no track loaded.
        """
        pass

    @abstractmethod
    def get_state(self) -> PlayerState:
        """
        Get current playback state.

        Returns:
            PlayerState enum value (STOPPED, PLAYING, or PAUSED).
        """
        pass

    def is_playing(self) -> bool:
        """
        Convenience check for playing state.

        Returns:
            True if currently playing, False otherwise.
        """
        return self.get_state() == PlayerState.PLAYING

    def load_track_by_index(self, track_index: int) -> bool:
        """
        Load track by 0-based index for playback.

        Args:
            track_index: 0-based track index.

        Returns:
            True if track loaded successfully, False otherwise.

        Note: This method is optional. Some transports (like BitPerfectPlayer)
              require PCM data to be provided externally via load_pcm_data().
              Default implementation returns False (not supported).
        """
        return False

    @abstractmethod
    def cleanup(self) -> None:
        """
        Release all resources held by the transport.

        Should be called before destroying the transport instance.
        After cleanup(), the transport should not be used.
        """
        pass
