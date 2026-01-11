#!/usr/bin/env python3
"""
Exemplo de uso do RedRam com LED Neopixel
Mostra como integrar LED controller com o sistema completo
"""

import logging
from cd_controller import CDPlayerController
from led_controller import setup_led_controller, LEDStatus
from gpio_controller import GPIOController
import config

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Exemplo completo de integração"""
    print("\n\n")
    print("  ██████  ███████ ██████  ██████   █████  ███    ███ ")
    print("  ██   ██ ██      ██   ██ ██   ██ ██   ██ ████  ████ ")
    print("  ██████  █████   ██   ██ ██████  ███████ ██ ████ ██ ")
    print("  ██   ██ ██      ██   ██ ██   ██ ██   ██ ██  ██  ██ ")
    print("  ██   ██ ███████ ██████  ██   ██ ██   ██ ██      ██ ")
    print()
    print("  \033[2mled & gpio example\033[0m\n")

    # 1. Criar controller principal
    controller = CDPlayerController()

    # 2. Configurar LED (se habilitado)
    led = None
    if config.LED_ENABLED:
        led = setup_led_controller(controller)
        if led:
            print("\033[0;32m✓\033[0m neopixel led configured")
            led.set_status(LEDStatus.READY)
        else:
            print("\033[1;33m~\033[0m led unavailable")
    else:
        print("\033[2m• led disabled in config\033[0m")

    # 3. Configurar GPIO (se habilitado)
    gpio = None
    if config.GPIO_ENABLED:
        try:
            gpio = GPIOController(controller)
            if gpio.is_enabled():
                print("\033[0;32m✓\033[0m gpio configured")
            else:
                print("\033[1;33m~\033[0m gpio unavailable")
        except Exception as e:
            logger.error(f"error configuring gpio: {e}")
    else:
        print("\033[2m• gpio disabled in config\033[0m")

    print()
    print("\033[2mavailable controls\033[0m")
    print("  menu command  'load'")
    print("  gpio button   load (gpio 25)")
    print()

    # 4. Exemplo: Verificar se já tem CD carregado
    if controller.is_cd_loaded():
        print(f"\033[0;32m✓\033[0m cd loaded \033[2m({controller.get_total_tracks()} tracks)\033[0m")
        if led:
            led.set_status(LEDStatus.LOADED)
    else:
        print("\033[2m• no cd loaded\033[0m")
        print("  \033[2muse 'load' command or gpio button\033[0m")

    print()
    print("\033[0;32m•\033[0m system ready \033[2m(ctrl+c to exit)\033[0m\n")
    
    # Loop simples para manter o programa rodando
    try:
        import time
        while True:
            # Verificar status periodicamente
            if controller.is_cd_loaded():
                state = controller.get_state()
                if state.value == 1:  # PLAYING
                    if led:
                        led.on_playback_state(True, False)
                elif state.value == 2:  # PAUSED
                    if led:
                        led.on_playback_state(False, True)
            
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n\n\033[2mexiting\033[0m")

    finally:
        # Cleanup
        print("\033[2m→ cleaning up\033[0m")
        if led:
            led.cleanup()
        if gpio:
            gpio.cleanup()
        controller.cleanup()
        print("\033[0;32m✓\033[0m done\n")


if __name__ == "__main__":
    main()

