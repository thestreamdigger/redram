#!/usr/bin/env python3

import sys
import logging
import argparse
from terminal_ui import TerminalUI
import config


def setup_logging(debug: bool = False):
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    use_debug = debug or config.LOG_LEVEL == 'DEBUG'
    log_level = logging.DEBUG if use_debug else logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    root_logger.handlers.clear()

    if config.LOG_FILE:
        try:
            file_handler = logging.FileHandler(config.LOG_FILE)
            file_handler.setLevel(log_level)
            file_handler.setFormatter(logging.Formatter(log_format))
            root_logger.addHandler(file_handler)
        except Exception:
            pass

    if debug:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter(log_format))
        root_logger.addHandler(console_handler)


def check_dependencies():
    import shutil
    import os

    errors = []
    warnings = []

    if not shutil.which('cdparanoia'):
        errors.append("cdparanoia not found. install: sudo apt-get install cdparanoia")

    try:
        import alsaaudio
        devices = alsaaudio.pcms(alsaaudio.PCM_PLAYBACK)
        if not any(config.ALSA_DEVICE.split(':')[0] in d for d in devices):
            warnings.append(f"alsa device {config.ALSA_DEVICE} may not be available")
    except ImportError:
        errors.append("python-alsaaudio not found. install: sudo apt-get install python3-alsaaudio")
    except Exception:
        pass

    if not os.path.exists(config.RAM_PATH):
        warnings.append(f"ram path {config.RAM_PATH} does not exist. will be created automatically.")

    if config.GPIO_ENABLED:
        try:
            from gpiozero import Button
        except ImportError:
            warnings.append("gpio enabled but gpiozero not found")

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(
        description='redram - cd-to-ram player',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s                    start player
  %(prog)s --debug            enable debug logging
  %(prog)s --verify           verify bit perfect configuration
  %(prog)s --check            check dependencies
        """
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='enable debug logging'
    )

    parser.add_argument(
        '--verify',
        action='store_true',
        help='verify bit perfect configuration'
    )

    parser.add_argument(
        '--check',
        action='store_true',
        help='check system dependencies'
    )

    args = parser.parse_args()

    setup_logging(debug=args.debug)
    logger = logging.getLogger(__name__)

    errors, warnings = check_dependencies()

    if args.check:
        print("\n\033[2mdependency check\033[0m\n")
        if errors:
            print("\033[0;31m✗ errors\033[0m")
            for error in errors:
                print(f"\033[2m  →\033[0m {error}")
        if warnings:
            print("\n\033[1;33m~ warnings\033[0m")
            for warning in warnings:
                print(f"\033[2m  →\033[0m {warning}")
        if not errors and not warnings:
            print("\033[0;32m✓ all dependencies ok\033[0m")
        print()
        sys.exit(1 if errors else 0)

    if errors:
        print("\033[0;31m✗ missing dependencies\033[0m")
        for error in errors:
            print(f"\033[2m  →\033[0m {error}")
        print("\n\033[2mrun 'sudo ./scripts/install.sh' to install dependencies\033[0m\n")
        sys.exit(1)

    if warnings:
        print("\033[1;33m~ warnings\033[0m")
        for warning in warnings:
            print(f"\033[2m  →\033[0m {warning}")
        print()

    if args.verify:
        print("\n\033[2mbit perfect verification\033[0m\n")
        from cd_controller import CDPlayerController
        controller = CDPlayerController()
        checks = controller.verify_bit_perfect()

        for check, status in checks.items():
            symbol = "\033[0;32m✓\033[0m" if status else "\033[1;33m~\033[0m"
            status_text = "" if status else "\033[2mcheck settings\033[0m"
            print(f"{symbol} {check:<20} {status_text}")

        print()
        controller.cleanup()
        sys.exit(0)

    try:
        ui = TerminalUI()
        ui.run()
    except KeyboardInterrupt:
        print("\n\n\033[2minterrupted\033[0m\n")
        sys.exit(0)
    except ImportError as e:
        if 'alsaaudio' in str(e):
            print("\n\033[0;31m✗\033[0m alsaaudio not found\n")
            print("\033[2minstall:\033[0m")
            print("  sudo apt-get install python3-alsaaudio\n")
        else:
            print(f"\n\033[0;31m✗\033[0m import error: {e}\n")
        sys.exit(1)
    except Exception as e:
        if 'alsaaudio' in str(type(e).__name__).lower() or 'alsa' in str(e).lower():
            sys.exit(1)
        else:
            logger.exception(f"fatal error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
