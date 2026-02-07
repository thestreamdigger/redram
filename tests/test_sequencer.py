"""
Unit tests for TrackSequencer.

Run with: python3 -m pytest tests/test_sequencer.py -v
"""

import pytest
import sys
sys.path.insert(0, '/home/pi/redram')

from src.track_sequencer import TrackSequencer, RepeatMode


class TestSequencerBasic:
    """Test basic sequential navigation."""

    def test_initialization(self):
        s = TrackSequencer()
        assert s.total_tracks == 0
        assert s.current_index == 0
        assert s.repeat_mode == RepeatMode.OFF
        assert s.shuffle_on is False

    def test_set_total_tracks(self):
        s = TrackSequencer()
        s.set_total_tracks(10)
        assert s.total_tracks == 10
        assert s.current_index == 0

    def test_next_sequential(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        assert s.next_track() == 1
        s.current_index = 2
        assert s.next_track() == 3

    def test_next_at_end_no_repeat(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        s.current_index = 4  # Last track (0-indexed)
        assert s.next_track() is None

    def test_prev_sequential(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        s.current_index = 3
        assert s.prev_track() == 2

    def test_prev_at_start(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        s.current_index = 0
        assert s.prev_track() is None

    def test_advance(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        result = s.advance()
        assert result == 1
        assert s.current_index == 1

    def test_retreat(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        s.current_index = 3
        result = s.retreat()
        assert result == 2
        assert s.current_index == 2

    def test_goto_valid(self):
        s = TrackSequencer()
        s.set_total_tracks(10)
        assert s.goto(5) is True
        assert s.current_index == 5

    def test_goto_invalid(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        assert s.goto(10) is False
        assert s.goto(-1) is False


class TestRepeatModes:
    """Test repeat mode functionality."""

    def test_cycle_repeat(self):
        s = TrackSequencer()
        assert s.repeat_mode == RepeatMode.OFF
        s.cycle_repeat()
        assert s.repeat_mode == RepeatMode.TRACK
        s.cycle_repeat()
        assert s.repeat_mode == RepeatMode.ALL
        s.cycle_repeat()
        assert s.repeat_mode == RepeatMode.OFF

    def test_repeat_track(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        s.current_index = 2
        s.repeat_mode = RepeatMode.TRACK
        # next_track should return current track
        assert s.next_track() == 2

    def test_next_at_end_repeat_all(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        s.current_index = 4  # Last track
        s.repeat_mode = RepeatMode.ALL
        assert s.next_track() == 0  # Wraps to first


class TestShuffle:
    """Test shuffle functionality."""

    def test_toggle_shuffle(self):
        s = TrackSequencer()
        s.set_total_tracks(10)
        assert s.shuffle_on is False
        s.toggle_shuffle()
        assert s.shuffle_on is True
        s.toggle_shuffle()
        assert s.shuffle_on is False

    def test_shuffle_generates_all_tracks(self):
        s = TrackSequencer()
        s.set_total_tracks(10)
        s.toggle_shuffle()
        # Playlist should contain all tracks exactly once
        assert len(s._shuffle_playlist) == 10
        assert set(s._shuffle_playlist) == set(range(10))

    def test_shuffle_is_random(self):
        """Shuffle should produce different orderings (statistically)."""
        s = TrackSequencer()
        s.set_total_tracks(10)
        orderings = set()
        for _ in range(10):
            s.toggle_shuffle()  # Enable
            orderings.add(tuple(s._shuffle_playlist))
            s.toggle_shuffle()  # Disable
        # With 10 tracks, very unlikely to get same ordering 10 times
        assert len(orderings) > 1

    def test_shuffle_advance(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        s.toggle_shuffle()
        first = s._shuffle_playlist[0]
        second = s._shuffle_playlist[1]
        s.current_index = first
        s._shuffle_position = 0
        assert s.next_track() == second

    def test_shuffle_at_end_no_repeat(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        s.toggle_shuffle()
        s._shuffle_position = 4  # Last position
        s._current_index = s._shuffle_playlist[4]
        assert s.next_track() is None

    def test_shuffle_with_repeat_all(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        s.toggle_shuffle()
        s.repeat_mode = RepeatMode.ALL
        s._shuffle_position = 4  # Last position
        s._current_index = s._shuffle_playlist[4]
        # Should regenerate playlist and return first
        result = s.next_track()
        assert result is not None
        assert 0 <= result < 5

    def test_shuffle_preserves_current_position(self):
        """When enabling shuffle, current track should be findable in playlist."""
        s = TrackSequencer()
        s.set_total_tracks(10)
        s.current_index = 5
        s.toggle_shuffle()
        # Current track should be in the playlist
        assert 5 in s._shuffle_playlist


class TestPreload:
    """Test preload functionality for gapless playback."""

    def test_preload_sequential(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        s.current_index = 2
        assert s.get_next_for_preload() == 3

    def test_preload_at_end_no_repeat(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        s.current_index = 4
        assert s.get_next_for_preload() is None

    def test_preload_at_end_repeat_all(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        s.current_index = 4
        s.repeat_mode = RepeatMode.ALL
        assert s.get_next_for_preload() == 0

    def test_preload_repeat_track(self):
        s = TrackSequencer()
        s.set_total_tracks(5)
        s.current_index = 2
        s.repeat_mode = RepeatMode.TRACK
        assert s.get_next_for_preload() == 2


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_sequencer(self):
        s = TrackSequencer()
        assert s.next_track() is None
        assert s.prev_track() is None

    def test_single_track(self):
        s = TrackSequencer()
        s.set_total_tracks(1)
        assert s.next_track() is None
        s.repeat_mode = RepeatMode.ALL
        assert s.next_track() == 0

    def test_reset(self):
        s = TrackSequencer()
        s.set_total_tracks(10)
        s.current_index = 5
        s.toggle_shuffle()
        s.reset()
        assert s.current_index == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
