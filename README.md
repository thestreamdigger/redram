# RedRAM - CD-to-RAM Player

[![Version](https://img.shields.io/badge/version-0.8.0-blue.svg)](https://github.com/thestreamdigger/redram)
[![License](https://img.shields.io/badge/license-GPL%20v3-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/status-stable-brightgreen.svg)]()
[![Raspberry Pi](https://img.shields.io/badge/platform-Raspberry%20Pi-C51A4A.svg)](https://www.raspberrypi.org/)
[![moOde](https://img.shields.io/badge/works%20with-moOde%20audio-orange.svg)](https://moodeaudio.org/)

Bit-perfect CD player for Raspberry Pi. Extracts audio to RAM with error correction via cdparanoia, then plays directly through ALSA. Eliminates read errors during playback.

## Features

- **Bit Perfect Playback**: Direct ALSA output, no alterations to PCM data
- **RAM-based**: Entire CD loaded to memory (eliminates read errors)
- **Gapless**: Seamless track transitions with double-buffer architecture
- **CD-Text**: Automatic metadata extraction (artist, album, track titles)
- **Streaming Mode**: Instant playback without RAM loading
- **Classic Controls**: Repeat (off/track/all), Shuffle, Quick Scan
- **HEAD Display**: MCUB Protocol v2.0.0 compatible (Arduino/ESP32)
- **Hardware**: GPIO buttons + WS2812 LED status indicator

## Requirements

### Hardware
- Raspberry Pi (tested on Pi 4)
- USB CD/DVD Drive

### Software
- cdparanoia (extraction)
- mpv (streaming mode)
- *Optional*: libcdio-utils (CD-Text), rpi-ws281x (LED), sg3-utils (SuperDrive)

## Quick Installation

```bash
git clone https://github.com/thestreamdigger/redram.git
cd redram
sudo ./install.sh
```

**That's it!** Start with `./run.sh`, insert CD, type `load`, then `play`.

### Installation Options

```bash
# Full installation
sudo ./install.sh

# With Apple SuperDrive support
sudo ./install.sh --install-superdrive-udev

# Show help
./install.sh --help
```

## Usage

### Commands

```
scan      - Quick CD check (~2s)
load [N]  - Load CD (0=streaming, 1=standard, 2=precise, 3=rescue)

play      - Play/pause toggle
pause     - Pause/resume
stop      - Stop playback
next/prev - Track navigation
goto N    - Jump to track N

repeat    - Cycle: off → track → all
shuffle   - Toggle shuffle

tracks    - List all tracks
eject     - Eject CD
quit      - Exit
```

### Example Session

```bash
> scan          # Quick check (~2s)
> load          # Load to RAM (~2-5 min)
> play          # Start playback
> next          # Next track (gapless)
> repeat        # Enable repeat
> eject         # Eject CD
```

## Playback Modes

| Feature | Streaming (`load 0`) | RAM (`load 1-3`) |
|---------|---------------------|------------------|
| Load Time | Instant | 2-5 minutes |
| Read Errors | Possible | Corrected |
| Track Switch | ~5ms | Instant |
| Gapless | No | Yes |
| RAM Usage | ~10MB | ~700MB |

## Hardware Setup

### GPIO Buttons

```
Play:     GPIO 17 (Pin 11) → GND
Pause:    GPIO 26 (Pin 37) → GND
Stop:     GPIO 27 (Pin 13) → GND
Next:     GPIO 22 (Pin 15) → GND
Previous: GPIO 23 (Pin 16) → GND
Eject:    GPIO 24 (Pin 18) → GND
Load:     GPIO 25 (Pin 22) → GND
```

Internal pull-up enabled - no external resistors needed.

### LED Status (WS2812)

```
LED: GPIO 18 (Pin 12) → [470Ω] → WS2812 DIN
```

| Status | Color | Behavior |
|--------|-------|----------|
| Ready | Blue | Solid |
| Loading | Yellow | Blinking |
| Loaded | Green | Solid |
| Playing | Green | Pulsing |
| Paused | Dim Green | Solid |
| Error | Red | Fast blink |

## Configuration

Defaults in `src/config.py`. User overrides in `config/settings.json`:

```json
{
    "autoplay_on_load": {"0": true},
    "led_enabled": true,
    "gpio_enabled": true
}
```

Keys match `config.py` constants (lowercase in JSON). Only include what you want to override.

### Defaults

```python
CD_DEVICE = '/dev/sr0'
ALSA_DEVICE = detect_audio_device()  # Auto-detects
RAM_PATH = '/mnt/cdram'
RAM_SIZE = '1G'
AUTOPLAY_ON_LOAD = {0: True}  # Autoplay per level, or True/False for all

GPIO_ENABLED = False  # Set True for buttons
LED_ENABLED = False   # Set True for WS2812
```

## Mode Indicators

| Mode | Indicator |
|------|-----------|
| Repeat Track | ⟳1 |
| Repeat All | ⟳ |
| Shuffle | ⤮ |

## Performance

| Metric | Value |
|--------|-------|
| RAM Usage | ~700MB per CD |
| Load Time | 2-5 min |
| Playback Latency | <10ms |
| Gapless Transition | <1ms |
| CPU Usage | <5% |

## Troubleshooting

### CD not detected
```bash
lsblk | grep sr
cdparanoia -d /dev/sr0 -Q
sudo usermod -a -G cdrom $USER
```

### No audio
```bash
aplay -l                      # List devices
amixer sset 'PCM' 100%        # Set volume
```

### SuperDrive not working
```bash
sudo ./install.sh --install-superdrive-udev
# Or manual: sudo sg_raw /dev/sr0 EA 00 00 00 00 00 01
```

## License

This project is licensed under the GPL v3 License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [cdparanoia](https://xiph.org/paranoia/) - CD extraction with error correction
- [ALSA](https://alsa-project.org/) - Linux audio system
- [moOde audio](https://moodeaudio.org/) - Audiophile music player
