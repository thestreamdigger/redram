# Changelog

All notable changes to this project will be documented in this file.

## [0.8.0] - Polymorphic Transport

### Added
- **Autoplay on load**: Configurable per extraction level via `config/settings.json`
- **`config/settings.json`**: User settings file, overrides any config.py default
- **`navigate_to()`**: Unified track navigation on AudioTransport ABC
- **`prepare_next()`**: Gapless preload on AudioTransport ABC (no-op for streaming)
- **`get_current_track_index()`** / **`get_track_count()`**: Abstract getters on AudioTransport
- **Listener infrastructure**: `controller.on('event', callback)` replaces Optional[Callable] monkey-patching

### Changed
- **CDPlayerController**: `play()`, `next()`, `prev()`, `goto()`, `stop()`, `seek()` fully polymorphic — zero `if is_direct_mode` branches for navigation
- **Unified `_on_track_end`**: Single handler for both RAM and streaming, detects gapless via index comparison
- **`prev()` unified**: Both modes now restart track if position > 2s (was skip-only in streaming)
- **BitPerfectPlayer**: Constructor accepts `data_provider` callable — player fetches its own PCM data
- **Gapless index tracking**: `_current_track_index` updated during gapless swap in playback loop
- **LED setup**: Clean `controller.on()` registration, no more `original_on_cd_loaded` wrapper chains
- **Source of truth**: `sequencer.current_index` for current track, `sequencer.total_tracks` for count

### Removed
- `_load_and_preload()` — replaced by `transport.navigate_to()` + `_preload_next()`
- `_on_streaming_track_end()` — merged into unified `_on_track_end()`
- `load_track_by_index()` from AudioTransport ABC — replaced by `navigate_to()`
- `next_track()` / `prev_track()` from DirectCDPlayer — dead code, navigation via sequencer
- 14 `if is_direct_mode` behavioral branches from controller
- Verbose docstrings and comments across all modules (minimalist style)

## [0.7.0] - Sequencer Consolidation

### Fixed
- **Repeat-track gapless deadlock**: `_on_track_end` no longer calls `load_pcm_data()`/`stop()` from playback thread
- **Shuffle streaming**: `_on_streaming_track_end` now uses `sequencer.advance()` instead of linear `current + 1`
- **Repeat-track shuffle drift**: `advance()` no longer increments `_shuffle_position` in repeat-track mode
- **Double brightness on LED**: Removed manual scaling in `_set_color`/`_set_all_colors` (PixelStrip already handles brightness)
- **tempfile.mktemp race condition**: Replaced with `tempfile.mkdtemp()` + socket inside for mpv IPC
- **Error message**: `load` level validation now shows "use 0-3" instead of "use 1-3"

### Refactored
- **CDPlayerController**: Eliminated `current_track_idx` duplicated state, sequencer is single source of truth
- Removed `shuffle_playlist`, `shuffle_position` proxy properties
- Removed `_get_next_track_index()` and `_generate_shuffle_playlist()` (duplicated sequencer logic)
- Replaced `_load_current_track()` with `_load_and_preload()` + `_preload_next()` using `sequencer.get_next_for_preload()`
- Rewrote `next()`, `prev()`, `goto()`, `shuffle()` to delegate entirely to sequencer
- **config.py**: Lazy ALSA detection via module `__getattr__` (PEP 562), zero import-time side effects

### Removed
- `BitPerfectPlayer.is_playing()` override (identical to base `AudioTransport.is_playing()`)
- `config.PARANOIA_MODE` (unreferenced)
- Unused `current_time` variable in LED animation loop

## [0.6.0] - CD-Text and Protocol Update

### Added
- **CD-Text Support**: Automatic metadata extraction (artist, album, track titles) via libcdio-utils
- **MCUB Protocol v2.0.0**: Backwards compatible update with `ver` field and `modes` validation
- **Extraction Retry**: Failed tracks automatically retry (max 2 attempts) before aborting
- **goto() streaming mode**: Direct track jump now works in streaming mode

### Changed
- HEAD commands now pass `parameters` dict to callback for v2.0.0 compliance
- All log messages in English following CLAUDE.md style
- Streaming mode indicator changed from `[STREAM]` to `⚡` (yellow)
- Status icons now colored: ▸ (green), ▍▍ (yellow), ■ (red)
- Progress arrow → now blue instead of dim

### Fixed
- Streaming mode first play: track index now correctly starts at 1
- Exception handling: replaced 16 bare `except:` with `except Exception:`
- Streaming buffer increased to 2s to reduce audio interruptions
- Monitor thread now uses Event.wait() for faster command response (~1ms vs ~200ms)

### Refactored
- **AudioTransport ABC**: Unified interface for RAM and streaming players
- **TrackSequencer**: Extracted shuffle/repeat logic to standalone class
- **PlayerState enum**: Unified state representation (was string in streaming mode)
- **Polymorphic transport**: `transport` property for cleaner player access
- **Chapter starts cached**: O(1) lookup instead of O(n) calculation
- **Persistent IPC connection**: Reuses socket connection with automatic fallback
- Reduced `is_direct_mode` conditionals from 21 to 15
- Added 43 unit tests for sequencer and transport conformance

### Known Issues
- **Streaming mode (level 0)**: mpv cdda:// in idle mode may not work reliably (see mpv#7384). Use RAM mode (levels 1-3) for production.

### Dependencies
- Added: `libcdio-utils` (apt) for `cd-info` command

## [0.5.0] - Optimized Streaming

### Changed
- **Persistent MPV**: Single mpv instance with IPC control for instant track switching (~5ms)
- **Chapter navigation**: CD loaded once, tracks accessed as chapters
- **Double-stop**: Now works in streaming mode (returns to track 1)

### Fixed
- Track position display now shows time within track, not global CD position
- Track duration from TOC data instead of total CD duration
- Track end detection via chapter change monitoring

## [0.4.0] - Streaming Mode

### Added
- **Streaming Mode (`load 0`)**: Direct CD playback without RAM loading for instant playback
- New `DirectCDPlayer` class for real-time audio streaming from CD to ALSA
- Streaming mode indicator (⚡) in status display
- Basic playback controls in streaming mode: play/pause/stop/next/prev

### Changed
- Extraction level 0 repurposed from fast mode (cdda2wav) to streaming mode
- Updated help text and documentation to reflect new playback modes
- Enhanced `CDController` to route commands between RAM and streaming players

### Removed
- **cdda2wav support**: Removed fast extraction mode and all cdda2wav dependencies
- Simplified extraction to cdparanoia-only (levels 1-3)

## [0.3.0] - HEAD Display Integration

### Added
- **HEAD Display Support**: Integrated MCUB Protocol v1.5 compatible display with auto-detection on `/dev/ttyACM*`, bidirectional communication, and real-time status updates every 500ms
- Commands: `play_pause`, `play`, `pause`, `stop`, `next`, `previous`, `repeat`/`single`, `random`
- Status fields: state, timing (elapsed/total), track info, playlist position, repeat/single/random modes, and metadata (artist/title/album)

### Changed
- New `head_controller.py` with `HeadController` and `HeadStateBuilder` classes
- Added transition flags to prevent false STOPPED state during track changes
- Forced HEAD updates after commands for immediate feedback

## [0.2.0] - Classic CD Player Features

### Added
- **Repeat Mode**: Three modes (OFF/TRACK/ALL) with cycling support. Repeat Track loops current track infinitely, Repeat All continuously loops entire disc
- **Shuffle Mode**: Random playback using Fisher-Yates algorithm with intelligent playlist generation. Compatible with repeat all (re-shuffles at end)
- **Quick CD Scan**: Fast TOC reading without loading to RAM (~2s operation). Shows track count, durations, and total time
- Commands: `scan`, `repeat`, `shuffle`, `pause`

### Changed
- Status line now displays mode indicators (⟳1, ⟳, ⤮)
- Next/previous navigation respects shuffle order
- Enhanced track end handling with repeat/shuffle logic

## [0.1.0] - Initial Release

### Core Features
- Bit perfect CD playback via direct ALSA hardware access
- CD-to-RAM extraction using cdparanoia with error correction
- Gapless playback with double-buffer architecture
- Terminal-based UI with interactive commands

### Playback Controls
- Play/pause toggle, stop, next/previous track, direct track selection (goto), seek, and eject

### Hardware Support
- GPIO button control (play/pause, stop, next, prev, eject, load)
- Neopixel WS2812 LED status indicator
- Apple SuperDrive USB automatic initialization via udev

### Additional Features
- Multi-level extraction modes (fast, standard, precise, rescue)
- ALSA device auto-detection and configuration
- Bit perfect configuration verification
- Automated installation script with virtual environment setup
