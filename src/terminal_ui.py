import time
import threading
import config
from cd_controller import CDPlayerController
from cd_player import PlayerState
from head_controller import HeadController, HeadStateBuilder
import logging

logger = logging.getLogger(__name__)


class TerminalUI:

    def __init__(self):
        self.controller = CDPlayerController()
        self.running = False
        self.status_thread = None
        self.waiting_for_input = False

        self.head = HeadController()
        self.head_connected = False

        self.controller.on('track_change', self._on_track_change)
        self.controller.on('cd_loaded', self._on_cd_loaded)

    def _on_track_change(self, track_num, total_tracks):
        logger.info(f"TRACK: {track_num}/{total_tracks}")
        self._force_head_update()

    def _force_head_update(self):
        if self.head_connected and self.head.running:
            self.head._send_status()

    def _on_cd_loaded(self, total_tracks):
        print(f"\n\033[0;32m✓\033[0m cd ready \033[2m({total_tracks} tracks)\033[0m\n")

    def _progress_callback(self, track_num, total_tracks, status):
        if status == "waking":
            print("\033[0;34m→ wake\033[0m")
        elif status == "detecting":
            print("\033[0;34m→ detect\033[0m")
        elif status == "reading_toc":
            print("\033[0;34m→ read\033[0m")
        elif status == "error":
            print("\n\033[0;31m✗\033[0m insufficient ram\n")
        elif status == "extracting":
            if track_num > 0:
                print(f"\033[0;34m→ {track_num:02d}/{total_tracks:02d}\033[0m" + " " * 20, end='\r')
        elif status == "complete":
            print("\r" + " " * 50 + "\r", end='', flush=True)

    def display_status(self):
        if not self.controller.is_cd_loaded():
            return

        try:
            from cd_controller import RepeatMode
            state = self.controller.get_state()
            track_num = self.controller.get_current_track_num()
            total_tracks = self.controller.get_total_tracks()
            position = self.controller.get_position()

            state_symbol = {
                PlayerState.PLAYING: "\033[0;32m▸\033[0m",
                PlayerState.PAUSED: "\033[1;33m▍▍\033[0m",
                PlayerState.STOPPED: "\033[0;31m■\033[0m"
            }.get(state, "?")

            indicators = []
            if self.controller.repeat_mode == RepeatMode.TRACK:
                indicators.append("\033[0;36m⟳1\033[0m")
            elif self.controller.repeat_mode == RepeatMode.ALL:
                indicators.append("\033[0;36m⟳\033[0m")
            if self.controller.shuffle_on:
                indicators.append("\033[0;36m⤮\033[0m")

            indicator_str = " " + " ".join(indicators) if indicators else ""

            if state == PlayerState.STOPPED:
                total_duration = self.controller.get_total_duration()
                ram_usage = self.controller.get_ram_usage_mb()
                dur_min = int(total_duration // 60)
                dur_sec = int(total_duration % 60)

                status_line = (
                    f"{state_symbol}  "
                    f"{total_tracks} tracks  "
                    f"00:00 \033[2m/\033[0m {dur_min:02d}:{dur_sec:02d}  "
                    f"\033[2m{ram_usage:.0f} mb\033[0m"
                    f"{indicator_str}"
                )
            else:
                duration = self.controller.get_duration()
                pos_min = int(position // 60)
                pos_sec = int(position % 60)
                dur_min = int(duration // 60)
                dur_sec = int(duration % 60)

                mode_indicator = ""
                if self.controller.is_direct_mode:
                    mode_indicator = " \033[0;33m⚡\033[0m"

                status_line = (
                    f"{state_symbol}  "
                    f"track {track_num:02d}/{total_tracks:02d}  "
                    f"{pos_min:02d}:{pos_sec:02d} \033[2m/\033[0m {dur_min:02d}:{dur_sec:02d}"
                    f"{indicator_str}"
                    f"{mode_indicator}"
                )

            if self.waiting_for_input:
                print(f"\0337\033[1A\r{status_line}" + " " * 30 + "\0338", end='', flush=True)
            else:
                print(f"\r{status_line}" + " " * 20, end='', flush=True)
        except Exception as e:
            logger.error(f"error in display_status: {e}")
            if not self.waiting_for_input:
                print("\r\033[0;31m✗\033[0m status error" + " " * 40, end='', flush=True)

    def _status_update_loop(self):
        while self.running:
            self.display_status()
            time.sleep(0.5)

    def print_welcome(self):
        print("  \033[2mtype 'help' for commands\033[0m")
        print()

    def print_help(self):
        print()
        print("  \033[2mabout\033[0m")
        print()
        print("    cd-to-ram player for bit perfect playback")
        print("    instant track access, zero read errors")
        print()
        print("  \033[2mcommands\033[0m")
        print()
        print("    load [N]       load cd")
        for level, info in sorted(config.EXTRACTION_LEVELS.items()):
            marker = " \033[2m(default)\033[0m" if level == config.DEFAULT_EXTRACTION_LEVEL else ""
            print(f"                     {level}. {info['name']:<10} {info['description']}{marker}")
        print()
        print("    play           start/resume playback")
        print("    pause          pause playback")
        print("    stop           stop playback")
        print("    next           next track")
        print("    prev           previous track")
        print()
        print("    goto N         jump to track N")
        print("    seek N         seek to N seconds")
        print()
        print("    repeat         cycle (off/track/all)")
        print("    shuffle        toggle shuffle")
        print("    scan           quick cd scan")
        print()
        print("    tracks         list all tracks")
        print("    verify         verify bit perfect setup")
        print()
        print("    eject          eject cd")
        print("    help           show help")
        print("    quit           exit")
        print()
        print("  \033[2mbit perfect\033[0m")
        print()
        print("    alsa hw device, unaltered pcm (44.1khz/16bit)")
        print("    no resampling, no normalization, no dsp")
        print()

    def print_tracks(self):
        if not self.controller.is_cd_loaded():
            print("\033[0;31m✗\033[0m no cd loaded")
            return

        total_tracks = self.controller.get_total_tracks()
        total_duration = self.controller.get_total_duration()
        ram_usage = self.controller.get_ram_usage_mb()
        total_min = int(total_duration // 60)
        total_sec = int(total_duration % 60)

        print()
        print(f"  \033[2mcd\033[0m      {total_tracks} tracks   {total_min:02d}:{total_sec:02d}   \033[2m{ram_usage:.0f} mb in ram\033[0m")
        print()

        current = self.controller.get_current_track_num()
        for track in self.controller.get_all_tracks():
            marker = "\033[0;32m▸\033[0m" if track.number == current else " "
            mins = int(track.duration_seconds // 60)
            secs = int(track.duration_seconds % 60)
            print(f"  {marker} {track.number:02d}   {mins:02d}:{secs:02d}")

        print()

    def verify_bit_perfect(self):
        checks = self.controller.verify_bit_perfect()

        print("\n\033[2mbit perfect verification\033[0m\n")

        for check, status in checks.items():
            symbol = "\033[0;32m✓\033[0m" if status else "\033[1;33m~\033[0m"
            status_text = "" if status else "\033[2mcheck settings\033[0m"
            print(f"  {symbol} {check:<20} {status_text}")

        print()

    def _detect_transport(self):
        info = self.controller.superdrive.get_info()
        return {
            'ready': info.get('is_ready', False),
            'device': info.get('device', config.CD_DEVICE),
            'name': info.get('display_name', '')
        }

    def _detect_head(self):
        try:
            info = self.head.detect_and_connect()
            if info.get('identification_success'):
                self.head_connected = True

                self.head.get_state = self._get_head_state
                self.head.on_command = self._handle_head_command
                self.head.start()

                return {
                    'connected': True,
                    'name': self.head.get_device_name(),
                    'path': self.head.device_path
                }
            else:
                return {'connected': False}
        except Exception as e:
            logger.error(f"HEAD detection err: {e}")
            return {'connected': False}

    def _get_head_state(self) -> dict:
        if not self.controller.is_cd_loaded():
            return {
                'elapsed': '00:00',
                'total': '00:00',
                'state': 'S',
                'song_id': '0',
                'track_number': '0',
                'artist': '',
                'title': 'No Disc',
                'album': '',
                'genre': '',
                'year': '',
                'file_type': '',
                'repeat': '0',
                'random': '0',
                'single': '0',
                'consume': '0',
                'volume': '100',
                'playlist_length': '0',
                'playlist_total_time': '00:00:00',
                'playlist_position': '0',
            }
        return HeadStateBuilder.build_state(self.controller)

    def _handle_head_command(self, action: str, params: dict):
        logger.info(f"HEAD cmd: {action}")

        if action == 'stop':
            self.controller.stop()
            return

        if not self.controller.is_cd_loaded():
            return

        try:
            if action == 'play_pause':
                state = self.controller.get_state()
                if state == PlayerState.PLAYING:
                    self.controller.pause()
                else:
                    self.controller.play()
                self._force_head_update()

            elif action == 'play':
                self.controller.play()
                self._force_head_update()

            elif action == 'pause':
                self.controller.pause()
                self._force_head_update()

            elif action == 'next':
                self.controller.next()
                self._force_head_update()

            elif action == 'previous':
                self.controller.prev()
                self._force_head_update()

            elif action in ['repeat', 'single']:
                mode = self.controller.repeat()
                logger.info(f"repeat mode: {mode.name}")
                self._force_head_update()

            elif action == 'random':
                self.controller.shuffle()
                self._force_head_update()

            elif action in ['consume', 'volume_up', 'volume_down', 'set_volume']:
                pass

        except Exception as e:
            logger.error(f"HEAD cmd err: {e}")

    def _verify_alsa_status(self):
        try:
            import alsaaudio
            devices = alsaaudio.pcms(alsaaudio.PCM_PLAYBACK)
            device_available = any(config.ALSA_DEVICE.split(':')[0] in d for d in devices)

            if device_available:
                return {
                    'status': True,
                    'device': config.ALSA_DEVICE,
                    'device_name': config.get_audio_device_name(),
                    'config': f"{config.SAMPLE_RATE}Hz/{config.BIT_DEPTH}bit"
                }
            else:
                return {
                    'status': False,
                    'device': config.ALSA_DEVICE,
                    'device_name': None,
                    'config': ''
                }
        except Exception as e:
            logger.error(f"ALSA verification failed: {e}")
            return {
                'status': False,
                'device': 'unavailable',
                'device_name': None,
                'config': ''
            }

    def run(self):
        self.running = True

        print("\n\n")
        print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print()
        print("  redram")
        print("  \033[2mcd-to-ram player\033[0m")
        print()
        print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print()

        head_status = self._detect_head()
        if head_status['connected']:
            print(f"  head ready      \033[2m{head_status['name']} ({head_status['path']})\033[0m")
        else:
            print(f"  head            \033[2mheadless mode\033[0m")

        drive_status = self._detect_transport()
        if drive_status['ready']:
            print(f"  drive ready     \033[2m{drive_status['name']} ({drive_status['device']})\033[0m")
        else:
            print(f"  drive           \033[2munavailable ({drive_status['device']})\033[0m")

        alsa_status = self._verify_alsa_status()
        if alsa_status['status']:
            device_display = alsa_status['device']
            if alsa_status['device_name']:
                device_display = f"{alsa_status['device_name']} ({alsa_status['device']})"
            print(f"  output ready    \033[2m{device_display}  {alsa_status['config']}\033[0m")
        else:
            print(f"  output          \033[2munavailable ({alsa_status['device']})\033[0m")
        print()

        self.print_welcome()

        self.status_thread = threading.Thread(target=self._status_update_loop, daemon=True)
        self.status_thread.start()

        try:
            while self.running:
                try:
                    print("\r" + " " * 80 + "\r", end='', flush=True)

                    self.waiting_for_input = True

                    time.sleep(0.1)

                    cmd_input = input("> ").strip().lower()

                    self.waiting_for_input = False

                    if not cmd_input:
                        continue

                    parts = cmd_input.split()
                    cmd = parts[0]
                    args = parts[1:] if len(parts) > 1 else []

                    if cmd in ["load", "loadcd"]:
                        extraction_level = config.DEFAULT_EXTRACTION_LEVEL
                        if args:
                            try:
                                level = int(args[0])
                                if level in config.EXTRACTION_LEVELS:
                                    extraction_level = level
                                else:
                                    print(f"\n\033[0;31m✗\033[0m invalid level {level} (use 0-3)\n")
                                    continue
                            except ValueError:
                                print(f"\n\033[0;31m✗\033[0m invalid level '{args[0]}'\n")
                                continue

                        if self.controller.is_cd_loaded():
                            print(f"\n\033[1;33m~\033[0m already loaded \033[2m({self.controller.get_total_tracks()} tracks)\033[0m")
                            self.waiting_for_input = True
                            time.sleep(0.1)
                            response = input("  reload? (y/N): ").strip().lower()
                            self.waiting_for_input = False
                            if response not in ['y', 's']:
                                continue

                        level_info = config.EXTRACTION_LEVELS[extraction_level]
                        print(f"\n\033[0;34m→ loading (level {extraction_level}: {level_info['name']})\033[0m")
                        success, status = self.controller.load(self._progress_callback, extraction_level)
                        if not success:
                            if status == "no_disc":
                                print("\n\033[2m○\033[0m no cd\n")
                            elif status == "read_error":
                                print("\n\033[0;31m✗\033[0m failed to read cd\n")
                            elif status == "ram_error":
                                print("\n\033[0;31m✗\033[0m insufficient ram\n")
                            elif status == "extraction_error":
                                print("\n\033[0;31m✗\033[0m extraction failed\n")
                            else:
                                print("\n\033[0;31m✗\033[0m failed\n")

                    elif cmd == "play":
                        if not self.controller.is_cd_loaded():
                            print("\033[0;31m✗\033[0m no cd loaded")
                        else:
                            self.controller.play()

                    elif cmd == "pause":
                        if not self.controller.is_cd_loaded():
                            print("\033[0;31m✗\033[0m no cd loaded")
                        else:
                            self.controller.pause()

                    elif cmd == "stop":
                        if not self.controller.is_cd_loaded():
                            print("\033[0;31m✗\033[0m no cd loaded")
                        else:
                            self.controller.stop()

                    elif cmd == "next":
                        if not self.controller.is_cd_loaded():
                            print("\033[0;31m✗\033[0m no cd loaded")
                        else:
                            self.controller.next()

                    elif cmd == "prev":
                        if not self.controller.is_cd_loaded():
                            print("\033[0;31m✗\033[0m no cd loaded")
                        else:
                            self.controller.prev()

                    elif cmd == "goto":
                        if not self.controller.is_cd_loaded():
                            print("\033[0;31m✗\033[0m no cd loaded")
                        elif args:
                            try:
                                track_num = int(args[0])
                                self.controller.goto(track_num)
                            except ValueError:
                                print("\033[0;31m✗\033[0m invalid")
                        else:
                            print("\033[2mgoto N\033[0m")

                    elif cmd == "seek":
                        if not self.controller.is_cd_loaded():
                            print("\033[0;31m✗\033[0m no cd loaded")
                        elif args:
                            try:
                                seconds = float(args[0])
                                self.controller.seek(seconds)
                            except ValueError:
                                print("\033[0;31m✗\033[0m invalid")
                        else:
                            print("\033[2mseek N\033[0m")

                    elif cmd == "repeat":
                        if not self.controller.is_cd_loaded():
                            print("\033[0;31m✗\033[0m no cd loaded")
                        else:
                            from cd_controller import RepeatMode
                            mode = self.controller.repeat()
                            mode_display = {
                                RepeatMode.OFF: "off",
                                RepeatMode.TRACK: "track",
                                RepeatMode.ALL: "all"
                            }
                            print(f"\033[0;36mrepeat:\033[0m {mode_display[mode]}")

                    elif cmd == "shuffle":
                        if not self.controller.is_cd_loaded():
                            print("\033[0;31m✗\033[0m no cd loaded")
                        else:
                            shuffle_on = self.controller.shuffle()
                            status = "on" if shuffle_on else "off"
                            print(f"\033[0;36mshuffle:\033[0m {status}")

                    elif cmd == "scan":
                        print("\033[0;34m→ scanning cd\033[0m")
                        success, status = self.controller.scan()
                        if success:
                            tracks = self.controller.get_scanned_tracks()
                            total_duration = sum(t.duration_seconds for t in tracks)
                            total_min = int(total_duration // 60)
                            total_sec = int(total_duration % 60)

                            print()
                            print(f"  \033[2mcd info\033[0m    {len(tracks)} tracks   {total_min:02d}:{total_sec:02d}")
                            print()

                            for track in tracks:
                                mins = int(track.duration_seconds // 60)
                                secs = int(track.duration_seconds % 60)
                                print(f"    {track.number:02d}   {mins:02d}:{secs:02d}")

                            print()
                            print("\033[2muse 'load' to load cd to ram\033[0m")
                            print()
                        elif status == "no_disc":
                            print("\n\033[2m○\033[0m no cd\n")
                        else:
                            print("\n\033[0;31m✗\033[0m scan failed (read error)\n")

                    elif cmd == "tracks":
                        self.print_tracks()

                    elif cmd == "verify":
                        self.verify_bit_perfect()

                    elif cmd == "eject":
                        print("\r" + " " * 80 + "\r", end='', flush=True)
                        self.controller.eject()
                        print("\033[0;32m✓\033[0m ejected\n")

                    elif cmd == "help":
                        self.print_help()

                    elif cmd in ["quit", "exit", "q"]:
                        print("\n\033[2m—\033[0m")
                        self.running = False
                        break

                    else:
                        print(f"\033[0;31m✗\033[0m unknown \033[2m'{cmd}'\033[0m")

                except KeyboardInterrupt:
                    self.waiting_for_input = False
                    print("\n\n\033[2m(use 'quit' to exit)\033[0m")
                    continue
                except Exception as e:
                    self.waiting_for_input = False
                    logger.error(f"unexpected error: {e}")
                    print(f"\n\033[0;31m✗\033[0m {e}")
                    continue

        finally:
            self.cleanup()

    def cleanup(self):
        self.running = False
        if self.status_thread:
            self.status_thread.join(timeout=1)
        if self.head_connected:
            self.head.stop()
        self.controller.cleanup()
        print("\n\033[2m—\033[0m\n")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )

    ui = TerminalUI()
    ui.run()


if __name__ == "__main__":
    main()
