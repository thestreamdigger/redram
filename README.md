# RedRam

**CD-to-RAM Player** for **Raspberry Pi OS**.

Real-time CD playback cannot guarantee bit-perfect accuracy—read errors and timing constraints prevent proper correction. Offline extraction with cdparanoia allows re-reads and C2 error correction to produce verified data. Playback from RAM delivers this exact PCM stream to the DAC.

> **Optimized for Raspberry Pi OS** - native ALSA, direct hardware access.

## Features

- **Bit Perfect**: Playback identical to original CD, no alterations to PCM data
- **RAM-based**: Entire CD loaded into memory (eliminates read errors during playback)
- **Gapless Playback**: Seamless transitions between tracks with zero audio gaps
- **CD-Text Support**: Automatic metadata extraction (artist, album, track titles)
- **Classic CD Player Features**: Repeat (off/track/all), Shuffle, Quick CD Scan
- **Flexible Playback**: Streaming mode (instant) or RAM mode (error-corrected)
- **Complete Control**: Terminal interface + GPIO support (physical buttons)
- **HEAD Display**: MCUB Protocol v2.0.0 compatible displays (Arduino/ESP32)
- **LED Status**: Visual feedback with Neopixel WS2812 (loading monitoring)

---

## Requirements

### Hardware
- **Raspberry Pi**
- **USB CD/DVD Drive**

### Software
- cdparanoia (error-corrected extraction)
- mpv (streaming playback)
- *Optional*: libcdio-utils for CD-Text, rpi-ws281x for LED, sg3-utils for SuperDrive

---

## Quick Installation

```bash
# Basic installation
sudo ./install.sh

# Start playing
./run.sh
```

**That's it!** Insert CD, type `load`, then `play`.

**Options:**
- `--install-superdrive-udev` - Apple SuperDrive support
- `--help` - Show all options

---

## Hardware Setup

### GPIO Pin Mapping

```
Play:     GPIO 17 (Pin 11) → Button → GND
Pause:    GPIO 26 (Pin 37) → Button → GND
Stop:     GPIO 27 (Pin 13) → Button → GND
Next:     GPIO 22 (Pin 15) → Button → GND
Previous: GPIO 23 (Pin 16) → Button → GND
Eject:    GPIO 24 (Pin 18) → Button → GND
Load:     GPIO 25 (Pin 22) → Button → GND
LED:      GPIO 18 (Pin 12) → [470Ω] → WS2812 DIN
```

**Notes:**
- All buttons use internal pull-up, **no external resistors needed**
- WS2812 LED requires 5V power, but accepts 3.3V data signal
- 470Ω resistor protects GPIO, 1000µF capacitor (optional) reduces flickering

### Apple SuperDrive

Install udev rule for automatic initialization:
```bash
sudo ./install.sh --install-superdrive-udev
```

After installation, SuperDrive works like any other CD drive when connected via USB.

---

## Basic Usage

### Commands

```
scan      - Scan CD (check if disc present, show track info, ~2s)
load [N]  - Load CD to RAM (extraction level 0-3, default: 1)
            0=fast (no correction), 1=standard, 2=precise, 3=rescue

play      - Toggle play/pause
pause     - Pause/resume playback
stop      - Stop playback
next      - Next track
prev      - Previous track
goto N    - Go to track N
seek N    - Jump to N seconds

repeat    - Cycle repeat mode (off/track/all)
shuffle   - Toggle shuffle on/off

tracks    - List all tracks
verify    - Verify bit perfect configuration
eject     - Eject CD
help      - Show help
quit      - Exit
```

### Example Session

```bash
> scan          # Quick check - shows track count, durations (~2s)
> load          # Load CD to RAM (~2-5 min, LED blinks yellow)
> play          # Start playback (LED pulses green)
> next          # Next track (seamless)
> repeat        # Cycle: off → track → all → off
> shuffle       # Toggle shuffle on/off
> goto 5        # Jump to track 5
> eject         # Eject CD
```

---

## Classic CD Player Features

### Repeat Modes

| Mode | Behavior | Indicator |
|------|----------|-----------|
| **OFF** | Plays disc once, stops at end | (none) |
| **TRACK** | Repeats current track infinitely | ⟳1 |
| **ALL** | Loops entire disc continuously | ⟳ |

Command: `repeat` - cycles through OFF → TRACK → ALL → OFF

### Shuffle Mode

- Generates shuffled track order using Fisher-Yates algorithm
- Next/prev buttons respect shuffle order
- Compatible with repeat all (re-shuffles at end)
- Indicator: ⤮ (when active)
- Command: `shuffle` - toggles on/off

### Extraction Levels

| Level | Tool | Speed | Use Case |
|-------|------|-------|----------|
| **0** (streaming) | cdparanoia | instant | Quick listen, no RAM loading |
| **1** (standard) | cdparanoia | ~2-4x | Default, balanced |
| **2** (precise) | cdparanoia | ~1-2x | High quality, full verification |
| **3** (rescue) | cdparanoia | ~0.1-1x | Scratched/damaged CDs |

---

## LED Visual States

| Status | Color | Behavior | Description |
|--------|-------|----------|-------------|
| `OFF` | Black | Solid | LED off |
| `READY` | Blue | Solid | No CD, ready to receive |
| `LOADING` | Orange/Yellow | Blinking (500ms) | Loading CD (detecting, reading TOC, extracting) |
| `LOADED` | Green | Solid | CD loaded in memory |
| `PLAYING` | Green | Smooth pulsing | Playing audio |
| `PAUSED` | Dim green | Solid | Playback paused |
| `ERROR` | Red | Fast blinking | Error detected |

---

## Configuration

Edit `src/config.py`:

```python
# CD Device
CD_DEVICE = '/dev/sr0'

# ALSA Device (auto-detects, prioritizes hw:0,0 for bit perfect)
ALSA_DEVICE = detect_audio_device()

# RAM Path
RAM_PATH = '/mnt/cdram'
RAM_SIZE = '1G'  # tmpfs size

# GPIO Buttons (set GPIO_ENABLED = True)
GPIO_PINS = {
    'play': 17, 'pause': 26, 'stop': 27,
    'next': 22, 'prev': 23, 'eject': 24, 'load': 25
}

# LED (set LED_ENABLED = True)
LED_PIN = 18  # GPIO 18 (Pin 12) - must support PWM
LED_BRIGHTNESS = 50  # 0-255
```

---

## Gapless Playback

Guaranteed gapless transitions using double-buffer architecture:

1. **Pre-loading**: Next track automatically pre-loaded into memory
2. **Seamless Transition**: Instant buffer swap at track end without stopping ALSA stream
3. **Zero Gap**: No silence or clicks between tracks

**Performance**: <1ms transition latency, ~50MB extra RAM for buffer.

---

## Playback Modes

RedRam supports two playback modes:

### Streaming Mode (`load 0`)
- **Instant playback** - no waiting for CD extraction
- Audio streams directly from CD via mpv
- Fast track switching (~5ms) using chapter navigation
- Minimal RAM usage (~10MB)
- Full controls: play/pause/stop/next/prev, double-stop reset
- Suitable for: quick listening, testing CDs, low-RAM systems

### RAM Mode (`load 1-3`)
- **Error-corrected** - perfect audio quality
- Entire CD loaded to RAM before playback
- Instant track switching, zero read errors
- Gapless playback, shuffle, repeat modes
- Drive only spins during loading
- Suitable for: archival, critical listening, best quality

**Quick comparison:**

| Feature | Streaming (load 0) | RAM (load 1-3) |
|---------|-------------------|----------------|
| Load Time | Instant | 2-5 minutes |
| Playback Start | Instant | Instant after load |
| Read Errors | Possible | None (corrected) |
| Track Switch | ~5ms | Instant |
| Gapless | No | Yes |
| RAM Usage | ~10MB | ~700MB |
| Use Case | Quick listen | Best quality |

---

## Bit Perfect Verification

Run verification:
```bash
python3 src/main.py --verify
```

**Requirements:**
1. Direct ALSA device: `hw:0,0` (project default)
2. Volume at 100%: `amixer sset 'PCM' 100%`
3. Correct sample rate: 44.1kHz (CD standard)

**Verify during playback:**
```bash
cat /proc/asound/card0/pcm0p/sub0/hw_params
```

Should show:
```
format: S16_LE
rate: 44100 (44100/1)
channels: 2
```

---

## System Architecture

```
┌────────────────────────────────────────┐
│              src/main.py               │
│             (Entry point)              │
└───────────────────┬────────────────────┘
                    │
         ┌──────────┴──────────┐
         │                     │
    ┌────▼─────┐        ┌──────▼─────┐
    │ Terminal │        │    GPIO    │
    │    UI    │        │ Controller │
    └────┬─────┘        └──────┬─────┘
         │                     │
         └──────────┬──────────┘
                    │
            ┌───────▼────────┐
            │ CD Controller  │
            │ (Orchestrator) │
            └───────┬────────┘
                    │
         ┌──────────┴─────────┐
         │                    │
    ┌────▼──────┐      ┌──────▼──────┐
    │           │      │  CD Player  │
    │ CD Ripper │      │ (Playback)  │
    │           │      │  + Gapless  │
    └───────────┘      └─────────────┘
         │                    │
    [cdparanoia]          [ALSA hw]
         │                    │
     [CD Drive] ──────► [DAC/Audio Out]
```

**Main Modules:**
- `main.py`: Entry point, dependency checking
- `cd_controller.py`: Main orchestrator
- `cd_ripper.py`: CD extraction
- `cd_player.py`: Bit perfect playback via ALSA with gapless
- `terminal_ui.py`: Interactive interface
- `gpio_controller.py`: Physical button control
- `led_controller.py`: Visual feedback
- `head_controller.py`: MCUB Protocol display support
- `config.py`: Centralized configuration

---

## Troubleshooting

### CD not detected
```bash
lsblk | grep sr
cdparanoia -d /dev/sr0 -Q
ls -l /dev/sr0
sudo usermod -a -G cdrom $USER  # Fix permissions
```

### No ALSA device
```bash
aplay -l  # List devices
# Adjust src/config.py with correct device (e.g., hw:0,0 or hw:1,0)
```

### Low/distorted volume
```bash
alsamixer
amixer sset 'PCM' 100%
```

### LED doesn't work
1. Check connections (VCC, GND, DIN)
2. Verify `LED_ENABLED = True` in config.py
3. Install: `sudo pip3 install rpi-ws281x`
4. Permissions: `sudo usermod -a -G gpio $USER`

### GPIO buttons unresponsive
1. Check connections (GPIO → Button → GND)
2. Verify `GPIO_ENABLED = True` in config.py
3. Check: `pip3 list | grep gpiozero`

### SuperDrive not detected
```bash
lsusb | grep -i apple
lsmod | grep sr_mod
sudo modprobe sr_mod  # If necessary
ls -l /etc/udev/rules.d/99-apple-superdrive.rules  # Verify rule

# Manual initialization (if needed)
sudo sg_raw /dev/sr0 EA 00 00 00 00 00 01
```

---

## Why RAM?

### Advantages
1. **Eliminates read errors during playback**: CD read once with correction, then everything in RAM
2. **Instant seek**: Jumping between tracks is immediate
3. **Less wear**: CD motor doesn't spin constantly
4. **Infinite buffer**: No underruns or stuttering
5. **Visual feedback**: LED shows loading progress

### Disadvantages
- Requires ~700MB RAM per CD
- Initial load time (~2-5 minutes)
- CD must be loaded manually

### How It Works
1. Insert CD → 2. `scan` (optional, ~2s) → 3. `load` (LED blinks yellow) → 4. System extracts all tracks to RAM → 5. CD loaded (LED solid green) → 6. Playback ready (LED pulses green during play)

---

## Performance

| Metric | Value |
|---------|-------|
| RAM Usage | ~700MB per CD |
| Load Time | 2-5 min |
| Playback Latency | <10ms (direct ALSA) |
| Seek Time | <1ms (RAM) |
| CPU Usage | <5% (playback) |
| Gapless Transition | <1ms (buffer swap) |
| LED Update Rate | 20 FPS (50ms) |
| GPIO Response | <10ms (debounce) |

---

## License

This project is provided "as is" for educational and personal use.

---

## Acknowledgments

- **cdparanoia** - CD read error correction
- **ALSA** - Linux audio system
- **Raspberry Pi** community
- **rpi-ws281x** library

---

**Made for audiophiles who use Python**

*"Because every bit matters - and every gap doesn't"*
