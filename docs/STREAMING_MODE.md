# Streaming Mode — DirectCDPlayer

## Overview

Streaming mode (`load 0`) plays directly from CD via mpv, no RAM extraction. Instant start, minimal memory.

## Architecture

```
CDPlayerController
  transport → DirectCDPlayer (when is_direct_mode)
  sequencer → TrackSequencer (shuffle/repeat)

DirectCDPlayer(AudioTransport)
  mpv process ← IPC Socket (Unix) ← _send_ipc()
       ↓
  ALSA Device (hw:X,Y)
```

## DirectCDPlayer

`src/cd_direct_player.py` — implements `AudioTransport` ABC.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `cd_device` | str | CD device (`/dev/sr0`) |
| `alsa_device` | str | ALSA device (`hw:1,0`) |
| `tracks` | List | Track list from TOC |
| `current_track` | int | Current track (1-based) |
| `state` | PlayerState | STOPPED, PLAYING, PAUSED |
| `on_track_end` | Callable | End-of-track callback |

### Public Methods

**`play_track(track_num) → bool`** — Play track (1-based). Starts mpv if needed, loads CD once, seeks to chapter.

**`play()`** — Resume if paused, replay if stopped.

**`pause()` / `resume()` / `stop()`** — Standard transport controls via mpv IPC.

**`seek(position_seconds)`** — Seek within track. Converts to absolute position: `chapter_start + position_seconds`.

**`navigate_to(track_index, auto_play=True) → bool`** — Unified navigation (0-based). Calls `play_track` if `auto_play`, otherwise just sets `current_track`.

**`get_current_track_index() → int`** — Current track (0-based), or -1 if none.

**`get_track_count() → int`** — Total tracks.

**`get_position() → float`** — Position in current track (seconds). Returns 0.0 during track transition until audio starts.

**`get_duration() → float`** — Track duration from TOC.

**`get_state() → PlayerState`** — Current state enum.

**`cleanup()`** — Quit mpv, remove IPC socket, cleanup temp dir.

### Internal Details

**mpv configuration** — Bit-perfect: direct ALSA, no resampling, no normalization, no DSP, volume 100%, gapless audio, 2s buffer for CD streaming on RPi.

**IPC** — Persistent Unix socket connection with automatic fallback to single-use sockets on failure.

**Monitor thread** — Two phases:
1. Wait for audio to start (`track_pos > 0.1s`, timeout 20s)
2. Watch for chapter changes (track advance) and EOF (disc end)

Calls `on_track_end` in separate thread to avoid blocking mpv monitor.

**Chapters vs tracks** — mpv treats CD tracks as chapters (0-indexed). Chapter starts are pre-computed from TOC durations.

## Controller Integration

```python
# _load_streaming_mode
self.direct_player = DirectCDPlayer(tracks=tracks)
self.direct_player.on_track_end = self._on_track_end  # same handler as RAM mode
self.transport.navigate_to(0, auto_play=False)

# polymorphic — controller doesn't know which backend
self.transport.play()
self.transport.navigate_to(new_idx, auto_play=was_playing)
```

### Unified _on_track_end

Single handler for both modes. Detects gapless by comparing `transport.get_current_track_index()` with sequencer's next index:
- Match → gapless transition already happened
- Mismatch → redirect needed (shuffle, repeat-track, etc.)

### Event Listeners

```python
controller.on('track_change', callback)
controller.on('cd_loaded', callback)
controller.on('status_change', callback)
controller.on('loading_progress', callback)
```

## AudioTransport Interface

```python
class AudioTransport(ABC):
    on_track_end: Optional[Callable[[], None]] = None

    # abstract
    play, pause, stop, seek, get_position, get_duration, get_state
    get_current_track_index, get_track_count, cleanup

    # default implementations
    is_playing() → bool
    navigate_to(track_index, auto_play=True) → bool  # returns False
    prepare_next(track_index) → None                  # no-op
```

Both `BitPerfectPlayer` and `DirectCDPlayer` implement this interface. The controller accesses them through `self.transport`.

## RAM vs Streaming

| Aspect | Streaming (`load 0`) | RAM (`load 1-3`) |
|--------|---------------------|------------------|
| Load time | Instant | 2-5 min |
| Read errors | Possible | Corrected |
| Track switch | ~5ms | Instant |
| Gapless | Via chapters | Native (double-buffer) |
| RAM usage | ~10MB | ~700MB |
| Backend | mpv | ALSA direct |

## Troubleshooting

### Time stuck at 00:00
- Check log for `STREAM: audio started`
- Verify mpv can access CD: `mpv cdda:///dev/sr0`

### Track doesn't advance
- Check log for `STREAM: chapter` or `STREAM: EOF`
- Verify monitor thread: `STREAM: monitor started`

### mpv won't start
- Check: `which mpv`
- Check log for `STREAM: mpv err`

## Known Issues

mpv idle mode + `cdda://` may not work reliably ([mpv#7384](https://github.com/mpv-player/mpv/issues/7384)). Use RAM mode (levels 1-3) for production.
