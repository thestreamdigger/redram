# RedRAM + MCUB Protocol Integration

**Direct HEAD connection using MCUB Protocol v2.0.0**

Version: 3.0
Status: Implemented

---

## Overview

RedRAM connects **directly** to MCUB-compatible display devices via serial, without needing the MCUB bridge as intermediary. This approach is simpler and more efficient.

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        RedRAM                           │
│  ┌──────────────────┐    ┌──────────────────────────┐  │
│  │ CDPlayerController│───→│ HeadController           │──┼──→ Display
│  │  (player state)   │    │ (MCUB Protocol v2.0.0)   │  │    (Arduino/ESP32)
│  └──────────────────┘    │ - Serial 115200 baud     │  │
│                          │ - JSON messages          │  │
│                          │ - Bidirectional commands │  │
│                          └──────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Benefits

- **No dependencies** - RedRAM works standalone
- **Same displays** - Any MCUB-compatible device works
- **Direct connection** - No intermediate files or processes
- **Bidirectional** - Display buttons control RedRAM

---

## Protocol Implementation

### Message Format

All messages follow MCUB Protocol v2.0.0:

```json
{
  "t": "type",    // Message type
  "d": {...},     // Data (host → device)
  "c": {...}      // Command (device → host)
}
```

### Status Message (t: "m")

RedRAM sends player status every 500ms:

```json
{
  "t": "m",
  "d": {
    "state": "P",
    "elapsed": "02:15",
    "total": "04:32",
    "song_id": "3",
    "track_number": "3",
    "artist": "Audio CD",
    "title": "Track 03",
    "album": "Disc",
    "genre": "",
    "year": "",
    "file_type": "PCM",
    "repeat": "1",
    "random": "0",
    "single": "0",
    "consume": "0",
    "volume": "100",
    "playlist_length": "12",
    "playlist_total_time": "00:45:23",
    "playlist_position": "3"
  }
}
```

### State Mapping

| RedRAM State | MCUB `state` |
|--------------|--------------|
| PLAYING | `"P"` |
| PAUSED | `"U"` |
| STOPPED | `"S"` |

### Track Number Fields

RedRAM sends the current track number in multiple fields for compatibility:

| Field | Description | Example |
|-------|-------------|---------|
| `track_number` | Current track number (MCUB standard) | `"3"` |
| `song_id` | Track identifier | `"3"` |
| `playlist_position` | Position in playlist | `"3"` |
| `playlist_length` | Total tracks on CD | `"12"` |
| `title` | Track title with number | `"Track 03"` |

**Note**: For CD playback, `track_number`, `song_id`, and `playlist_position` are always equal.

### Repeat Mode Mapping

RedRAM uses 3 exclusive modes mapped to 2 MCUB flags:

| RedRAM Mode | MCUB `repeat` | MCUB `single` |
|-------------|---------------|---------------|
| OFF | `"0"` | `"0"` |
| TRACK | `"1"` | `"1"` |
| ALL | `"1"` | `"0"` |

### Commands (t: "cmd")

Display devices send commands to control RedRAM:

**Format v2.0.0:**
```json
{"t": "cmd", "c": {"action": "play_pause", "parameters": {}}}
```

**Format v1.5 (legacy, still supported):**
```json
{"t": "cmd", "c": {"action": "play_pause"}}
```

#### Supported Commands

| Command | Action |
|---------|--------|
| `play_pause` | Toggle play/pause |
| `play` | Start playback |
| `pause` | Pause playback |
| `stop` | Stop playback |
| `next` | Next track |
| `previous` | Previous track |
| `repeat` | Cycle: OFF → TRACK → ALL → OFF |
| `single` | Cycle: OFF → TRACK → ALL → OFF |
| `random` | Toggle shuffle |

Note: `repeat` and `single` both cycle through modes (CD player behavior differs from MPD).

#### Ignored Commands

These MPD commands are received but ignored (not applicable to CD):

- `consume` - No concept of consuming tracks on CD
- `volume_up`, `volume_down`, `set_volume` - Volume controlled by system/DAC

---

## Device Identification

RedRAM identifies displays using MCUB protocol:

**Request:**
```json
{"t": "id", "c": "identify"}
```

**Response v2.0.0:**
```json
{"t": "id", "d": {"name": "ht16k33_7seg_01", "ver": "2.0.0", "modes": ["mpd"]}}
```

**Response v1.5 (legacy, still supported):**
```json
{"t": "id", "d": {"name": "ht16k33_7seg_01", "type": "display", "protocol_version": "1.5.0"}}
```

RedRAM supports both formats for backward compatibility.

---

## Implementation Files

### RedRAM

| File | Purpose |
|------|---------|
| `src/head_controller.py` | Serial communication, MCUB protocol |
| `src/terminal_ui.py` | HEAD integration, command handling |

### Key Classes

**HeadController** - Serial connection and message handling:
- Auto-detects `/dev/ttyACM*` devices
- Sends status at 500ms intervals
- Receives and dispatches commands

**HeadStateBuilder** - Converts RedRAM state to MCUB format:
- Time formatting (MM:SS, HH:MM:SS)
- Repeat mode to flags conversion
- All required MCUB fields

### Event Integration

```python
# terminal_ui.py registers HEAD via listener pattern
controller.on('track_change', self._on_track_change)
controller.on('cd_loaded', self._on_cd_loaded)
```

HEAD uses pull-model (`get_state` callback) for 500ms polling — correct for serial devices.

---

## Configuration

HEAD is automatically detected on startup. No configuration needed.

Display shown on startup:
```
  audio ready  DAC-X6 (hw:1,0)  44100Hz/16bit
  head ready   ht16k33_7seg_01 (/dev/ttyACM0)
```

If no display found:
```
  head         headless mode
```

---

## Usage with MPD

The same display device can work with both RedRAM and MPD:

1. **Playing CDs** → RedRAM connects to display
2. **Playing music files** → MCUB bridge connects to display

Only one can connect at a time. Stop RedRAM before starting MPD (or vice versa).

---

## Troubleshooting

### Display not detected

1. Check USB connection: `ls /dev/ttyACM*`
2. Check permissions: `sudo usermod -a -G dialout $USER`
3. Check device responds: `tio /dev/ttyACM0`

### Commands not working

1. Check log: `grep HEAD /tmp/redram.log`
2. Verify command format in device firmware

### State not updating

1. Check HEAD is running: look for "head ready" on startup
2. Check serial connection: log shows TX messages

---

## References

- [MCUB Protocol v2.0.0](../mcub/docs/PROTOCOL.md)
- [MCUB Common Library](../mcub_common/)
