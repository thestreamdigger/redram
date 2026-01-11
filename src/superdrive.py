import subprocess
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class SuperDriveController:

    def __init__(self, device: str = '/dev/sr0'):
        self.device = device
        self.is_superdrive = False
        self.is_enabled = False
        self.is_ready = False
        self.vendor = None
        self.model = None

    def detect(self) -> bool:
        import os
        if not os.path.exists(self.device):
            logger.debug(f"device {self.device} not found")
            return False

        try:
            result = subprocess.run(
                ['udevadm', 'info', '--query=property', f'--name={self.device}'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                return False

            for line in result.stdout.split('\n'):
                if line.startswith('ID_VENDOR='):
                    self.vendor = line.split('=', 1)[1]
                elif line.startswith('ID_MODEL='):
                    self.model = line.split('=', 1)[1]

            if self.model:
                self.is_ready = True
                self._check_if_superdrive(result.stdout)
                drive_type = "Apple SuperDrive" if self.is_superdrive else "optical drive"
                logger.info(f"{drive_type} detected: {self._get_display_name()}")
                return True

            return False

        except Exception as e:
            logger.error(f"error detecting drive: {e}")
            return False

    def _check_if_superdrive(self, udev_output: str):
        if 'apple' in udev_output.lower():
            self.is_superdrive = True
            return

        try:
            result = subprocess.run(['lsusb'], capture_output=True, text=True, timeout=5)
            if '05ac:1500' in result.stdout:
                self.is_superdrive = True
        except Exception:
            pass

    def _get_display_name(self) -> str:
        if self.vendor and self.model:
            v = self.vendor.replace('_', ' ')
            m = self.model.replace('_', ' ')
            return f"{v} {m}".strip()
        elif self.model:
            return self.model.replace('_', ' ')
        return "CD/DVD Drive"

    def enable(self) -> bool:
        if not self.is_superdrive:
            logger.warning("device is not a superdrive, skipping enable")
            return True

        try:
            logger.info("enabling apple superdrive...")

            result = subprocess.run(
                ['sg_raw', self.device, 'EA', '00', '00', '00', '00', '00', '01'],
                capture_output=True,
                timeout=10
            )

            if result.returncode == 0:
                logger.info("scsi command sent successfully")
            else:
                logger.warning("scsi command failed, trying alternative method...")
                subprocess.run(
                    ['sg_raw', self.device, '1B', '00', '00', '00', '01', '00'],
                    capture_output=True,
                    timeout=10
                )

            time.sleep(0.5)

            for attempt in range(2):
                result = subprocess.run(
                    ['sg_raw', self.device, '00', '00', '00', '00', '00', '00'],
                    capture_output=True,
                    timeout=2
                )

                if result.returncode == 0:
                    self.is_enabled = True
                    logger.info("superdrive enabled successfully")
                    return True
                else:
                    if attempt < 1:
                        time.sleep(0.5)

            logger.debug("superdrive enable sent, proceeding...")
            self.is_enabled = True
            return True

        except FileNotFoundError:
            logger.error("sg_raw command not found. install: sudo apt-get install sg3-utils")
            return False
        except Exception as e:
            logger.error(f"error enabling superdrive: {e}")
            return False

    def wait_for_cd(self, timeout: int = 60) -> bool:
        logger.info(f"waiting for cd (timeout: {timeout}s)...")

        drive_error_count = 0
        max_drive_errors = 5

        for i in range(timeout):
            try:
                result = subprocess.run(
                    ['cdparanoia', '-d', self.device, '-Q'],
                    capture_output=True,
                    timeout=5
                )

                if result.returncode == 0:
                    logger.info("cd detected")
                    return True

                drive_error_count = 0
                time.sleep(1)

            except subprocess.TimeoutExpired:
                logger.debug(f"cdparanoia timeout on attempt {i+1}/{timeout}")
                time.sleep(1)
            except Exception as e:
                drive_error_count += 1
                logger.debug(f"attempt {i+1}/{timeout}: {e} (errors: {drive_error_count}/{max_drive_errors})")

                if drive_error_count >= max_drive_errors:
                    logger.warning(f"too many consecutive errors ({drive_error_count}), waiting longer...")
                    time.sleep(3)
                    drive_error_count = 0
                else:
                    time.sleep(1)

        logger.warning(f"no cd detected after {timeout}s")
        return False

    def get_info(self) -> dict:
        return {
            'device': self.device,
            'vendor': self.vendor,
            'model': self.model,
            'is_superdrive': self.is_superdrive,
            'is_ready': self.is_ready,
            'display_name': self._get_display_name() if self.is_ready else None
        }

    def eject(self) -> bool:
        try:
            result = subprocess.run(
                ['eject', self.device],
                capture_output=True,
                timeout=10
            )

            if result.returncode == 0:
                logger.info("cd ejected")
                return True
            else:
                logger.error("error ejecting cd")
                return False

        except Exception as e:
            logger.error(f"error ejecting: {e}")
            return False


def setup_superdrive(device: str = '/dev/sr0') -> Optional[SuperDriveController]:
    controller = SuperDriveController(device)
    controller.detect()

    if controller.is_superdrive:
        if not controller.enable():
            logger.error("failed to enable superdrive")
            return None

    return controller


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )

    device = sys.argv[1] if len(sys.argv) > 1 else '/dev/sr0'
    print(f"\nverifying device: {device}\n")

    controller = SuperDriveController(device)

    if controller.detect():
        print("\033[0;32m✓\033[0m apple superdrive detected\n")

        info = controller.get_info()
        print(f"  vendor: {info['vendor']}")
        print(f"  model:  {info['model']}\n")

        if controller.enable():
            print("\033[0;32m✓\033[0m superdrive enabled\n")

            print("waiting for cd...")
            if controller.wait_for_cd(timeout=10):
                print("\033[0;32m✓\033[0m cd detected")
            else:
                print("\033[1;33m~\033[0m no cd detected")
        else:
            print("\033[0;31m✗\033[0m failed to enable superdrive")
            sys.exit(1)
    else:
        print("\033[1;33m~\033[0m not an apple superdrive")
        print("  will use as standard drive")
