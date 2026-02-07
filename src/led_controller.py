"""
Neopixel WS2812 LED controller
"""

import logging
import threading
import time
from typing import Optional, Tuple
import config

logger = logging.getLogger(__name__)

if config.LED_ENABLED:
    try:
        from rpi_ws281x import PixelStrip, Color
        LED_AVAILABLE = True
    except ImportError:
        logger.warning("rpi_ws281x not available. install: pip install rpi-ws281x")
        LED_AVAILABLE = False
else:
    LED_AVAILABLE = False


class LEDStatus:
    OFF = "off"
    READY = "ready"
    LOADING = "loading"
    LOADED = "loaded"
    PLAYING = "playing"
    PAUSED = "paused"
    ERROR = "error"


class NeopixelController:

    def __init__(self):
        self.enabled = config.LED_ENABLED and LED_AVAILABLE
        self.strip: Optional[PixelStrip] = None
        self.current_status = LEDStatus.OFF
        self.animation_thread: Optional[threading.Thread] = None
        self.running = False
        self.brightness = config.LED_BRIGHTNESS

        self.colors = {
            LEDStatus.OFF: (0, 0, 0),
            LEDStatus.READY: (0, 0, 255),
            LEDStatus.LOADING: (255, 165, 0),
            LEDStatus.LOADED: (0, 255, 0),
            LEDStatus.PLAYING: (0, 255, 0),
            LEDStatus.PAUSED: (0, 128, 0),
            LEDStatus.ERROR: (255, 0, 0),
        }

        if self.enabled:
            self._init_led()

    def _init_led(self):
        try:
            self.strip = PixelStrip(
                num=config.LED_COUNT,
                pin=config.LED_PIN,
                freq_hz=config.LED_FREQ_HZ,
                dma=config.LED_DMA,
                invert=config.LED_INVERT,
                brightness=self.brightness,
                channel=config.LED_CHANNEL
            )
            self.strip.begin()
            self.running = True
            self.animation_thread = threading.Thread(target=self._animation_loop, daemon=True)
            self.animation_thread.start()
            logger.info(f"[OK] LED ready: {config.LED_COUNT} leds, pin {config.LED_PIN}")
        except Exception as e:
            logger.error(f"error initializing led: {e}")
            self.enabled = False

    def _set_color(self, color: Tuple[int, int, int], led_index: int = 0):
        if not self.enabled or not self.strip:
            return

        try:
            r, g, b = color
            self.strip.setPixelColor(led_index, Color(r, g, b))
            self.strip.show()
        except Exception as e:
            logger.error(f"error setting led color: {e}")

    def _set_all_colors(self, color: Tuple[int, int, int]):
        if not self.enabled or not self.strip:
            return

        try:
            r, g, b = color
            for i in range(config.LED_COUNT):
                self.strip.setPixelColor(i, Color(r, g, b))
            self.strip.show()
        except Exception as e:
            logger.error(f"error setting colors: {e}")

    def _animation_loop(self):
        while self.running:
            try:
                if not self.enabled or not self.strip:
                    time.sleep(0.1)
                    continue

                status = self.current_status
                color = self.colors.get(status, (0, 0, 0))

                if status == LEDStatus.OFF:
                    self._set_all_colors((0, 0, 0))
                    time.sleep(0.5)
                elif status == LEDStatus.READY:
                    self._set_all_colors(color)
                    time.sleep(0.5)
                elif status == LEDStatus.LOADING:
                    current_time = time.time()
                    if int(current_time * 2) % 2 == 0:
                        self._set_all_colors(color)
                    else:
                        self._set_all_colors((0, 0, 0))
                    time.sleep(0.05)
                elif status == LEDStatus.LOADED:
                    self._set_all_colors(color)
                    time.sleep(0.5)
                elif status == LEDStatus.PLAYING:
                    pulse = int((time.time() * 2) % 2)
                    brightness_factor = 0.5 + (0.5 * abs(pulse - 0.5) * 2)
                    r = int(color[0] * brightness_factor)
                    g = int(color[1] * brightness_factor)
                    b = int(color[2] * brightness_factor)
                    self._set_all_colors((r, g, b))
                    time.sleep(0.05)
                elif status == LEDStatus.PAUSED:
                    self._set_all_colors(color)
                    time.sleep(0.5)
                elif status == LEDStatus.ERROR:
                    current_time = time.time()
                    if int(current_time * 4) % 2 == 0:
                        self._set_all_colors(color)
                    else:
                        self._set_all_colors((0, 0, 0))
                    time.sleep(0.05)

            except Exception as e:
                logger.error(f"error in animation loop: {e}")
                time.sleep(0.5)

    def set_status(self, status: str):
        if status in [LEDStatus.OFF, LEDStatus.READY, LEDStatus.LOADING,
                      LEDStatus.LOADED, LEDStatus.PLAYING, LEDStatus.PAUSED, LEDStatus.ERROR]:
            self.current_status = status
            logger.debug(f"LED status: {status}")
        else:
            logger.warning(f"invalid status: {status}")

    def on_loading_progress(self, track_num: int, total_tracks: int, status: str):
        if status in ("detecting", "reading_toc", "extracting"):
            self.set_status(LEDStatus.LOADING)
        elif status == "complete":
            self.set_status(LEDStatus.LOADED)

    def on_cd_loaded(self, total_tracks: int):
        self.set_status(LEDStatus.LOADED)
        logger.debug(f"LED: cd loaded, {total_tracks} tracks")

    def on_playback_state(self, is_playing: bool, is_paused: bool, cd_loaded: bool = False):
        if is_playing:
            self.set_status(LEDStatus.PLAYING)
        elif is_paused:
            self.set_status(LEDStatus.PAUSED)
        elif cd_loaded:
            self.set_status(LEDStatus.LOADED)
        else:
            self.set_status(LEDStatus.READY)

    def on_error(self):
        self.set_status(LEDStatus.ERROR)

    def on_no_cd(self):
        self.set_status(LEDStatus.READY)

    def is_enabled(self) -> bool:
        return self.enabled and self.strip is not None

    def cleanup(self):
        self.running = False
        if self.animation_thread:
            self.animation_thread.join(timeout=1)

        if self.strip:
            try:
                self._set_all_colors((0, 0, 0))
                self.strip.show()
            except Exception:
                pass

        logger.info("LED cleanup done")


def setup_led_controller(controller) -> Optional[NeopixelController]:
    import time
    from cd_player import PlayerState

    led = NeopixelController()

    if not led.is_enabled():
        logger.info("led disabled or not available")
        return None

    controller.on('loading_progress', led.on_loading_progress)
    controller.on('cd_loaded', lambda total: led.on_cd_loaded(total))
    controller.on('status_change', lambda s: led.on_no_cd() if s == "disc_end" else None)

    def monitor_playback():
        while led.running:
            try:
                state = controller.get_state()
                led.on_playback_state(
                    state == PlayerState.PLAYING,
                    state == PlayerState.PAUSED,
                    controller.is_cd_loaded()
                )
                time.sleep(0.5)
            except Exception:
                pass

    threading.Thread(target=monitor_playback, daemon=True).start()

    logger.info("[OK] LED connected to controller")
    return led
