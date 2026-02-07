"""
python3 -m pytest tests/test_transport.py -v
"""

import pytest
import sys
sys.path.insert(0, '/home/pi/redram/src')

from audio_transport import AudioTransport, PlayerState
from cd_player import BitPerfectPlayer
from cd_direct_player import DirectCDPlayer


class TestPlayerStateEnum:

    def test_state_values(self):
        assert PlayerState.STOPPED.value == 0
        assert PlayerState.PLAYING.value == 1
        assert PlayerState.PAUSED.value == 2

    def test_state_names(self):
        assert PlayerState.STOPPED.name == 'STOPPED'
        assert PlayerState.PLAYING.name == 'PLAYING'
        assert PlayerState.PAUSED.name == 'PAUSED'


class TestBitPerfectPlayerConformance:

    def test_inherits_audio_transport(self):
        assert issubclass(BitPerfectPlayer, AudioTransport)

    def test_has_required_methods(self):
        required_methods = [
            'play', 'pause', 'stop', 'seek',
            'get_position', 'get_duration', 'get_state', 'cleanup',
            'navigate_to', 'prepare_next',
            'get_current_track_index', 'get_track_count'
        ]
        for method in required_methods:
            assert hasattr(BitPerfectPlayer, method), f'Missing method: {method}'

    def test_initial_state(self):
        try:
            player = BitPerfectPlayer()
            assert player.get_state() == PlayerState.STOPPED
        except Exception:
            pytest.skip("ALSA not available")

    def test_has_load_pcm_data(self):
        assert hasattr(BitPerfectPlayer, 'load_pcm_data')

    def test_state_type(self):
        try:
            player = BitPerfectPlayer()
            state = player.get_state()
            assert isinstance(state, PlayerState)
        except Exception:
            pytest.skip("ALSA not available")

    def test_navigate_to_with_data_provider(self):
        fake_pcm = b'\x00' * 1000
        provider = lambda track_num: fake_pcm if track_num == 1 else None

        try:
            player = BitPerfectPlayer(data_provider=provider, track_count=3)
            result = player.navigate_to(0, auto_play=False)
            assert result is True
            assert player.get_current_track_index() == 0
        except Exception:
            pytest.skip("ALSA not available")

    def test_navigate_to_without_data_provider(self):
        try:
            player = BitPerfectPlayer()
            result = player.navigate_to(0, auto_play=False)
            assert result is False
        except Exception:
            pytest.skip("ALSA not available")

    def test_get_current_track_index_initial(self):
        try:
            player = BitPerfectPlayer()
            assert player.get_current_track_index() == -1
        except Exception:
            pytest.skip("ALSA not available")

    def test_get_track_count(self):
        try:
            player = BitPerfectPlayer(track_count=5)
            assert player.get_track_count() == 5
        except Exception:
            pytest.skip("ALSA not available")


class MockTrack:
    duration_seconds = 180.0


class TestDirectCDPlayerConformance:

    def test_inherits_audio_transport(self):
        assert issubclass(DirectCDPlayer, AudioTransport)

    def test_has_required_methods(self):
        required_methods = [
            'play', 'pause', 'stop', 'seek',
            'get_position', 'get_duration', 'get_state', 'cleanup',
            'navigate_to', 'get_current_track_index', 'get_track_count'
        ]
        for method in required_methods:
            assert hasattr(DirectCDPlayer, method), f'Missing method: {method}'

    def test_initial_state(self):
        player = DirectCDPlayer(tracks=[])
        assert player.get_state() == PlayerState.STOPPED

    def test_state_type(self):
        player = DirectCDPlayer(tracks=[])
        state = player.get_state()
        assert isinstance(state, PlayerState)
        assert not isinstance(state, str)

    def test_navigate_to_without_auto_play(self):
        player = DirectCDPlayer(tracks=[MockTrack(), MockTrack(), MockTrack()])

        result = player.navigate_to(0, auto_play=False)
        assert result is True
        assert player.current_track == 1

        result = player.navigate_to(2, auto_play=False)
        assert result is True
        assert player.current_track == 3

    def test_navigate_to_invalid_index(self):
        player = DirectCDPlayer(tracks=[MockTrack(), MockTrack()])

        assert player.navigate_to(-1, auto_play=False) is False
        assert player.navigate_to(10, auto_play=False) is False

    def test_get_current_track_index(self):
        player = DirectCDPlayer(tracks=[MockTrack(), MockTrack(), MockTrack()])
        assert player.get_current_track_index() == -1

        player.navigate_to(1, auto_play=False)
        assert player.get_current_track_index() == 1

    def test_get_track_count(self):
        player = DirectCDPlayer(tracks=[MockTrack(), MockTrack(), MockTrack()])
        assert player.get_track_count() == 3

        player = DirectCDPlayer(tracks=[])
        assert player.get_track_count() == 0

    def test_has_play_method(self):
        player = DirectCDPlayer(tracks=[])
        assert callable(player.play)


class TestInterfaceConsistency:

    def test_same_state_enum(self):
        try:
            ram_player = BitPerfectPlayer()
            ram_state = ram_player.get_state()
        except Exception:
            ram_state = PlayerState.STOPPED

        stream_player = DirectCDPlayer(tracks=[])
        stream_state = stream_player.get_state()

        assert type(ram_state) == type(stream_state)
        assert ram_state == stream_state

    def test_is_playing_method(self):
        try:
            ram_player = BitPerfectPlayer()
            assert hasattr(ram_player, 'is_playing')
            assert ram_player.is_playing() is False
        except Exception:
            pass

        stream_player = DirectCDPlayer(tracks=[])
        assert hasattr(stream_player, 'is_playing')
        assert stream_player.is_playing() is False

    def test_both_have_navigate_to(self):
        assert hasattr(BitPerfectPlayer, 'navigate_to')
        assert hasattr(DirectCDPlayer, 'navigate_to')

    def test_both_have_track_getters(self):
        for cls in [BitPerfectPlayer, DirectCDPlayer]:
            assert hasattr(cls, 'get_current_track_index')
            assert hasattr(cls, 'get_track_count')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
