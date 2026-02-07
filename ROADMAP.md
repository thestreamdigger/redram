# Roadmap

## Done

- [x] CD-Text support (v0.6.0)
- [x] AudioTransport ABC for polymorphic player access (v0.6.0)
- [x] TrackSequencer for mode-independent shuffle/repeat (v0.6.0)
- [x] Sequencer as single source of truth, eliminate duplicated state (v0.7.0)
- [x] Gapless deadlock fix, shuffle streaming fix (v0.7.0)
- [x] Lazy ALSA detection via PEP 562 `__getattr__` (v0.7.0)
- [x] Polymorphic transport: `navigate_to()`, `prepare_next()`, track getters (v0.8.0)
- [x] Zero `if is_direct_mode` branches for navigation (v0.8.0)
- [x] Unified `_on_track_end` handler with gapless detection (v0.8.0)
- [x] Listener infrastructure: `controller.on('event', callback)` (v0.8.0)
- [x] `config/settings.json` user overrides, autoplay per extraction level (v0.8.0)

## Planned

- [ ] Integration with MusicBrainz (automatic CD identification)
- [ ] Program/Playlist support (custom track order)
- [ ] Export to FLAC/WAV
