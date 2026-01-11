# Changelog

All notable changes to this project will be documented in this file.

## [0.6.0] - CD-Text and Protocol Update

### Added
- **CD-Text Support**: Automatic metadata extraction (artist, album, track titles) via libcdio-utils
- **MCUB Protocol v2.0.0**: Backwards compatible update with `ver` field and `modes` validation
- **Extraction Retry**: Failed tracks automatically retry (max 2 attempts) before aborting

### Changed
- HEAD commands now pass `parameters` dict to callback for v2.0.0 compliance
- All log messages in English following CLAUDE.md style

### Fixed
- Streaming mode first play: track index now correctly starts at 1
- Exception handling: replaced 16 bare `except:` with `except Exception:`

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
