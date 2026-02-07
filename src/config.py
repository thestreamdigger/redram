import subprocess
import re
import os
import shutil
import logging

logger = logging.getLogger(__name__)


def _parse_aplay_output():
    devices = []
    try:
        result = subprocess.run(['aplay', '-l'],
                              capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if line.startswith('card'):
                    match = re.search(r'card (\d+).*\[(.*?)\].*device (\d+)', line)
                    if match:
                        card_num, card_name, dev_num = match.groups()
                        devices.append({
                            'device': f'hw:{card_num},{dev_num}',
                            'name': card_name,
                            'card': card_num
                        })
    except Exception:
        pass
    return devices


def detect_audio_device():
    devices = _parse_aplay_output()

    for d in devices:
        if 'hdmi' not in d['name'].lower() and 'loopback' not in d['name'].lower():
            return d['device']

    for d in devices:
        if 'hdmi' in d['name'].lower():
            return d['device']

    return 'hw:0,0'


def get_audio_device_name(hw_device: str = None) -> str:
    global _ALSA_DEVICE
    if hw_device is None:
        if _ALSA_DEVICE is None:
            _ALSA_DEVICE = detect_audio_device()
        hw_device = _ALSA_DEVICE
    devices = _parse_aplay_output()

    for d in devices:
        if d['device'] == hw_device:
            return d['name']
    return None


CD_DEVICE = '/dev/sr0'

_ALSA_DEVICE = None


def __getattr__(name):
    global _ALSA_DEVICE
    if name == 'ALSA_DEVICE':
        if _ALSA_DEVICE is None:
            _ALSA_DEVICE = detect_audio_device()
        return _ALSA_DEVICE
    raise AttributeError(f"module 'config' has no attribute {name}")


RAM_PATH = '/mnt/cdram'
RAM_SIZE = '1G'

SAMPLE_RATE = 44100
BIT_DEPTH = 16
CHANNELS = 2
AUDIO_FORMAT = 'S16_LE'

PERIOD_SIZE = 4096
BUFFER_SIZE = 16384

GPIO_ENABLED = False
GPIO_PINS = {
    'play': 17,
    'pause': 26,
    'stop': 27,
    'next': 22,
    'prev': 23,
    'eject': 24,
    'load': 25,
}
GPIO_BOUNCE_TIME = 200

LED_ENABLED = False
LED_COUNT = 1
LED_PIN = 18
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_INVERT = False
LED_BRIGHTNESS = 50
LED_CHANNEL = 0

CDPARANOIA_PATH = '/usr/bin/cdparanoia'
RIP_SPEED_LIMIT = None
CD_READ_OFFSET = 6

EXTRACTION_LEVELS = {
    0: {
        'name': 'streaming',
        'description': 'Direct playback via MPV (no RAM)',
        'flags': [],
        'timeout': 999999
    },
    1: {
        'name': 'standard',
        'description': 'Balanced speed and quality',
        'flags': ['-Y'],
        'timeout': 240
    },
    2: {
        'name': 'precise',
        'description': 'Full verification',
        'flags': [],
        'timeout': 300
    },
    3: {
        'name': 'rescue',
        'description': 'Damaged discs',
        'flags': ['-z', '100'],
        'timeout': 600
    }
}
DEFAULT_EXTRACTION_LEVEL = 1

LOG_LEVEL = 'DEBUG'
LOG_FILE = '/home/pi/redram/redram.log'

VERIFY_SAMPLE_RATE = True
VERIFY_VOLUME = True

RAM_SAFETY_MARGIN = 0.15


def get_available_ram_mb(ram_path: str = None) -> float:
    ram_path = ram_path or RAM_PATH
    try:
        if os.path.exists(ram_path):
            usage = shutil.disk_usage(ram_path)
            return usage.free / (1024 * 1024)
    except Exception:
        pass
    return 0.0


def estimate_cd_ram_usage_mb(duration_seconds: float) -> float:
    pcm_mb = (SAMPLE_RATE * CHANNELS * 2 * duration_seconds) / (1024 * 1024)
    gapless_mb = 50
    return pcm_mb + gapless_mb


def check_ram_availability(required_mb: float, ram_path: str = None) -> tuple[bool, float, str]:
    available_mb = get_available_ram_mb(ram_path)

    if available_mb == 0.0:
        return False, 0.0, "unable to check ram"

    required_with_margin = required_mb * (1 + RAM_SAFETY_MARGIN)

    if available_mb < required_with_margin:
        return False, available_mb, f"need {required_with_margin:.0f} mb, have {available_mb:.0f} mb"

    return True, available_mb, f"ok: {available_mb:.0f} mb available"
