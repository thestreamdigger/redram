import serial
import json
import time
import glob
import threading
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# MCUB Protocol version (for documentation/compatibility reference)
MCUB_PROTOCOL_VERSION = "2.0.0"


class HeadController:

    BAUDRATE = 115200
    TIMEOUT = 0.01
    IDENTIFICATION_TIMEOUT = 1.0
    UPDATE_INTERVAL = 0.5

    def __init__(self):
        self.ser: Optional[serial.Serial] = None
        self.device_path: Optional[str] = None
        self.device_info: dict = {}
        self.connected = False
        self.running = False

        self._update_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self.on_command: Optional[Callable[[str, dict], None]] = None
        self.get_state: Optional[Callable[[], dict]] = None

        self._messages_sent = 0
        self._messages_received = 0
        self._errors = 0

    def detect_and_connect(self) -> dict:
        acm_devices = sorted(glob.glob('/dev/ttyACM*'))
        logger.debug(f"HEAD scan: {acm_devices}")

        if not acm_devices:
            logger.debug("HEAD: no devices")
            return {}

        for device_path in acm_devices:
            logger.debug(f"HEAD: identifying {device_path}")
            info = self._try_identify(device_path)
            logger.debug(f"HEAD: {device_path} -> {info.get('identification_success')}")

            if info.get('identification_success'):
                self.device_path = device_path
                self.device_info = info
                self.connected = True
                device_data = info.get('device_info', {})
                device_protocol = device_data.get('ver', device_data.get('protocol_version', '?'))
                modes = device_data.get('modes', [])
                if modes and 'mpd' not in modes:
                    logger.warning(f"HEAD: device does not support mpd mode: {modes}")
                logger.info(f"HEAD connected: {device_path} (v{device_protocol})")
                return info

        logger.debug("HEAD: no compatible device")
        return {}

    def _try_identify(self, device_path: str) -> dict:
        result = {'identification_success': False, 'error': 'timeout'}

        def do_identify():
            nonlocal result
            try:
                logger.debug(f"HEAD: open {device_path}")
                with serial.Serial(device_path, self.BAUDRATE, timeout=0.5) as ser:
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                    time.sleep(0.2)

                    while ser.in_waiting > 0:
                        ser.read(ser.in_waiting)
                        time.sleep(0.02)

                    identify_cmd = json.dumps({'t': 'id', 'c': 'identify'}) + '\n'
                    logger.debug(f"HEAD TX: {identify_cmd.strip()}")
                    ser.write(identify_cmd.encode())
                    ser.flush()

                    start_time = time.time()
                    while time.time() - start_time < 0.8:
                        if ser.in_waiting > 0:
                            response = ser.readline().decode('utf-8', errors='ignore').strip()
                            logger.debug(f"HEAD RX: {response}")
                            if response:
                                try:
                                    data = json.loads(response)
                                    if data.get('t') == 'id' and 'd' in data:
                                        result = {
                                            'identification_success': True,
                                            'path': device_path,
                                            'device_info': data.get('d', {}),
                                            'raw_response': data
                                        }
                                except Exception:
                                    pass
                            return
                        time.sleep(0.01)
            except Exception as e:
                logger.debug(f"HEAD err: {device_path} {e}")
                result = {'identification_success': False, 'error': str(e)}

        thread = threading.Thread(target=do_identify, daemon=True)
        thread.start()
        thread.join(timeout=self.IDENTIFICATION_TIMEOUT)

        if thread.is_alive():
            logger.debug(f"HEAD: {device_path} timeout")
            return {'identification_success': False, 'error': 'timeout'}

        return result

    def get_device_name(self) -> str:
        if not self.device_info:
            return "unknown"
        info = self.device_info.get('device_info', {})
        name = info.get('name', info.get('device', 'unknown'))
        return name

    def get_device_id(self) -> str:
        if not self.device_info:
            return ""
        info = self.device_info.get('device_info', {})
        return info.get('id', info.get('device_id', ''))

    def start(self):
        if not self.connected or not self.device_path:
            logger.warning("HEAD: not connected")
            return False

        try:
            logger.debug(f"HEAD: serial open {self.device_path}")
            self.ser = serial.Serial(
                self.device_path,
                self.BAUDRATE,
                timeout=self.TIMEOUT
            )
            self.running = True
            self._stop_event.clear()

            self._update_thread = threading.Thread(
                target=self._update_loop,
                daemon=True,
                name="HEAD-UpdateLoop"
            )
            self._update_thread.start()
            logger.info(f"HEAD running: interval={self.UPDATE_INTERVAL}s")
            return True

        except serial.SerialException as e:
            logger.error(f"HEAD serial err: {e}")
            self.connected = False
            return False

    def stop(self):
        logger.debug("HEAD stopping")
        self.running = False
        self._stop_event.set()

        if self._update_thread and self._update_thread.is_alive():
            self._update_thread.join(timeout=2.0)

        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
                logger.debug("HEAD: serial closed")
            except Exception:
                pass
            self.ser = None

        logger.info(f"HEAD stopped: tx={self._messages_sent} rx={self._messages_received} err={self._errors}")

    def _update_loop(self):
        last_update = 0
        loop_count = 0

        while self.running and not self._stop_event.is_set():
            try:
                loop_count += 1

                now = time.time()
                if now - last_update >= self.UPDATE_INTERVAL:
                    self._send_status()
                    last_update = now

                self._process_commands()

                time.sleep(0.01)

            except serial.SerialException as e:
                logger.error(f"HEAD serial err: {e}")
                self._errors += 1
                self.connected = False
                break
            except Exception as e:
                logger.error(f"HEAD err: {e}")
                self._errors += 1
                time.sleep(0.1)

        logger.debug(f"HEAD: loop ended ({loop_count} iter)")

    def _send_status(self):
        if not self.ser or not self.ser.is_open:
            return

        if not self.get_state:
            return

        try:
            state = self.get_state()
            if state:
                message = {'t': 'm', 'd': state}
                data = json.dumps(message) + '\n'
                self.ser.write(data.encode())
                self.ser.flush()
                self._messages_sent += 1

                if self._messages_sent % 10 == 1:
                    logger.debug(f"HEAD TX #{self._messages_sent}: {data.strip()}")
        except Exception as e:
            logger.error(f"HEAD tx err: {e}")
            self._errors += 1

    def _process_commands(self):
        if not self.ser or not self.ser.is_open:
            return

        try:
            if self.ser.in_waiting > 0:
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    logger.debug(f"HEAD RX: {line}")
                    self._messages_received += 1
                    try:
                        data = json.loads(line)
                        if data.get('t') == 'cmd' and 'c' in data:
                            cmd = data['c']
                            if isinstance(cmd, dict):
                                action = cmd.get('action')
                                params = cmd.get('parameters', {})
                            else:
                                action = cmd
                                params = {}
                            logger.info(f"HEAD cmd: {action}")
                            if action and self.on_command:
                                self.on_command(action, params)
                    except json.JSONDecodeError:
                        logger.warning(f"HEAD: invalid JSON")
        except Exception as e:
            logger.error(f"HEAD rx err: {e}")
            self._errors += 1

    def send_message(self, msg_type: str, data: dict):
        if not self.ser or not self.ser.is_open:
            return False

        try:
            message = {'t': msg_type, 'd': data}
            line = json.dumps(message) + '\n'
            logger.debug(f"HEAD TX: {line.strip()}")
            self.ser.write(line.encode())
            self.ser.flush()
            self._messages_sent += 1
            return True
        except Exception as e:
            logger.error(f"HEAD tx err: {e}")
            self._errors += 1
            return False

    def get_stats(self) -> dict:
        return {
            'connected': self.connected,
            'running': self.running,
            'device_path': self.device_path,
            'messages_sent': self._messages_sent,
            'messages_received': self._messages_received,
            'errors': self._errors
        }


class HeadStateBuilder:

    @staticmethod
    def format_time(seconds: float) -> str:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

    @staticmethod
    def format_playlist_time(seconds: float) -> str:
        mins, secs = divmod(int(seconds), 60)
        hours, mins = divmod(mins, 60)
        return f"{hours:02d}:{mins:02d}:{secs:02d}"

    @staticmethod
    def build_state(controller) -> dict:
        from cd_player import PlayerState
        from cd_controller import RepeatMode

        state_map = {
            PlayerState.PLAYING: 'P',
            PlayerState.PAUSED: 'U',
            PlayerState.STOPPED: 'S'
        }

        if getattr(controller, '_transitioning', False):
            if getattr(controller, '_transition_was_playing', False):
                player_state = 'P'
            else:
                player_state = 'U'
        else:
            player_state = state_map.get(controller.get_state(), 'S')

        position = controller.get_position()
        duration = controller.get_duration()
        total_duration = controller.get_total_duration()

        repeat_mode = controller.repeat_mode
        repeat_flag = '1' if repeat_mode in [RepeatMode.TRACK, RepeatMode.ALL] else '0'
        single_flag = '1' if repeat_mode == RepeatMode.TRACK else '0'

        track_num = controller.get_current_track_num()
        total_tracks = controller.get_total_tracks()

        track_title = controller.get_current_track_title()
        track_artist = controller.get_current_track_artist()
        disc_title = controller.get_disc_title()
        disc_artist = controller.get_disc_artist()

        state = {
            'elapsed': HeadStateBuilder.format_time(position),
            'total': HeadStateBuilder.format_time(duration),
            'state': player_state,
            'song_id': str(track_num),
            'track_number': str(track_num),
            'artist': track_artist or disc_artist or 'Audio CD',
            'title': track_title or f'Track {track_num:02d}',
            'album': disc_title or 'Disc',
            'genre': '',
            'year': '',
            'file_type': 'PCM',
            'repeat': repeat_flag,
            'random': '1' if controller.shuffle_on else '0',
            'single': single_flag,
            'consume': '0',
            'volume': '100',
            'playlist_length': str(total_tracks),
            'playlist_total_time': HeadStateBuilder.format_playlist_time(total_duration),
            'playlist_position': str(track_num),
        }

        return state
