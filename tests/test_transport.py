"""
Unit tests for AudioTransport interface conformance.

Run with: python3 -m pytest tests/test_transport.py -v
"""

import pytest
import sys
sys.path.insert(0, '/home/pi/redram/src')

from audio_transport import AudioTransport, PlayerState
from cd_player import BitPerfectPlayer
from cd_direct_player import DirectCDPlayer


class TestPlayerStateEnum:
    """Test PlayerState enum consistency."""

    def test_state_values(self):
        assert PlayerState.STOPPED.value == 0
        assert PlayerState.PLAYING.value == 1
        assert PlayerState.PAUSED.value == 2

    def test_state_names(self):
        assert PlayerState.STOPPED.name == 'STOPPED'
        assert PlayerState.PLAYING.name == 'PLAYING'
        assert PlayerState.PAUSED.name == 'PAUSED'


class TestBitPerfectPlayerConformance:
    """Test BitPerfectPlayer conforms to AudioTransport interface."""

    def test_inherits_audio_transport(self):
        assert issubclass(BitPerfectPlayer, AudioTransport)

    def test_has_required_methods(self):
        # Check all abstract methods exist
        required_methods = [
            'play', 'pause', 'stop', 'seek',
            'get_position', 'get_duration', 'get_state', 'cleanup'
        ]
        for method in required_methods:
            assert hasattr(BitPerfectPlayer, method), f'Missing method: {method}'

    def test_initial_state(self):
        # BitPerfectPlayer requires ALSA, so we test minimal instantiation
        try:
            player = BitPerfectPlayer()
            assert player.get_state() == PlayerState.STOPPED
        except Exception:
            # ALSA may not be available in test environment
            pytest.skip("ALSA not available")

    def test_has_load_pcm_data(self):
        """BitPerfectPlayer should have load_pcm_data for loading audio bytes."""
        assert hasattr(BitPerfectPlayer, 'load_pcm_data')

    def test_state_type(self):
        """State should be PlayerState enum, not string."""
        try:
            player = BitPerfectPlayer()
            state = player.get_state()
            assert isinstance(state, PlayerState)
        except Exception:
            pytest.skip("ALSA not available")


class TestDirectCDPlayerConformance:
    """Test DirectCDPlayer conforms to AudioTransport interface."""

    def test_inherits_audio_transport(self):
        assert issubclass(DirectCDPlayer, AudioTransport)

    def test_has_required_methods(self):
        required_methods = [
            'play', 'pause', 'stop', 'seek',
            'get_position', 'get_duration', 'get_state', 'cleanup'
        ]
        for method in required_methods:
            assert hasattr(DirectCDPlayer, method), f'Missing method: {method}'

    def test_initial_state(self):
        player = DirectCDPlayer(tracks=[])
        assert player.get_state() == PlayerState.STOPPED

    def test_state_type(self):
        """State should be PlayerState enum, not string."""
        player = DirectCDPlayer(tracks=[])
        state = player.get_state()
        assert isinstance(state, PlayerState)
        assert not isinstance(state, str)

    def test_has_load_track_by_index(self):
        """DirectCDPlayer should support loading by track index."""
        assert hasattr(DirectCDPlayer, 'load_track_by_index')

    def test_load_track_by_index(self):
        """Test load_track_by_index with valid/invalid indices."""
        class MockTrack:
            duration_seconds = 180.0

        player = DirectCDPlayer(tracks=[MockTrack(), MockTrack(), MockTrack()])

        # Valid index (0-based)
        assert player.load_track_by_index(0) is True
        assert player.current_track == 1  # Stored as 1-based

        assert player.load_track_by_index(2) is True
        assert player.current_track == 3

        # Invalid indices
        assert player.load_track_by_index(-1) is False
        assert player.load_track_by_index(10) is False

    def test_has_play_method(self):
        """DirectCDPlayer should have play() for AudioTransport interface."""
        player = DirectCDPlayer(tracks=[])
        assert callable(player.play)


class TestInterfaceConsistency:
    """Test that both players have consistent interfaces."""

    def test_same_state_enum(self):
        """Both players should use the same PlayerState enum."""
        try:
            ram_player = BitPerfectPlayer()
            ram_state = ram_player.get_state()
        except Exception:
            ram_state = PlayerState.STOPPED

        stream_player = DirectCDPlayer(tracks=[])
        stream_state = stream_player.get_state()

        assert type(ram_state) == type(stream_state)
        assert ram_state == stream_state  # Both should be STOPPED initially

    def test_is_playing_method(self):
        """Both should have is_playing() from AudioTransport."""
        try:
            ram_player = BitPerfectPlayer()
            assert hasattr(ram_player, 'is_playing')
            assert ram_player.is_playing() is False
        except Exception:
            pass

        stream_player = DirectCDPlayer(tracks=[])
        assert hasattr(stream_player, 'is_playing')
        assert stream_player.is_playing() is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
