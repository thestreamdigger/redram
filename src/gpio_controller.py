"""
GPIO controller for physical buttons using gpiozero
"""

import logging
from typing import Optional, Callable, Dict
import config

logger = logging.getLogger(__name__)

if config.GPIO_ENABLED:
    try:
        from gpiozero import Button
        from gpiozero.pins.pigpio import PiGPIOFactory
        GPIOZERO_AVAILABLE = True
    except ImportError:
        try:
            from gpiozero import Button
            GPIOZERO_AVAILABLE = True
        except ImportError:
            logger.warning("gpiozero not available. disabling gpio.")
            GPIOZERO_AVAILABLE = False
else:
    GPIOZERO_AVAILABLE = False


class GPIOController:
    
    def __init__(self, controller):
        self.controller = controller
        self.enabled = config.GPIO_ENABLED and GPIOZERO_AVAILABLE
        self.initialized = False
        self.buttons: Dict[str, Button] = {}
        
        self.on_button_press: Optional[Callable] = None
        
        if self.enabled:
            self._init_gpio()
    
    def _init_gpio(self):
        """Inicializa pinos GPIO usando gpiozero"""
        try:
            for button_name, pin in config.GPIO_PINS.items():
                try:
                    bounce_time_sec = config.GPIO_BOUNCE_TIME / 1000.0
                    
                    button = Button(
                        pin,
                        pull_up=True,
                        bounce_time=bounce_time_sec,
                        hold_time=0.5
                    )
                    
                    button.when_pressed = lambda name=button_name: self._button_callback(name)
                    
                    self.buttons[button_name] = button
                    logger.info(f"gpio configured: {button_name} -> GPIO{pin}")
                    
                except Exception as e:
                    logger.error(f"error configuring gpio{pin} for {button_name}: {e}")
            
            self.initialized = True
            logger.info("[OK] gpio initialized successfully (gpiozero)")
            
        except Exception as e:
            logger.error(f"error initializing gpio: {e}")
            self.enabled = False
    
    def _button_callback(self, button_name: str):
        logger.debug(f"button pressed: {button_name}")
        
        if button_name == "play":
            self.controller.play()

        elif button_name == "pause":
            self.controller.pause()

        elif button_name == "stop":
            self.controller.stop()
        
        elif button_name == "next":
            self.controller.next()

        elif button_name == "prev":
            self.controller.prev()
        
        elif button_name == "eject":
            self.controller.eject()
        
        elif button_name == "load":
            if not self.controller.is_cd_loaded():
                def progress_cb(track_num, total_tracks, status):
                    logger.debug(f"loading: {status} - track {track_num}/{total_tracks}")

                import threading
                def load_thread():
                    self.controller.load(progress_cb)

                thread = threading.Thread(target=load_thread, daemon=True)
                thread.start()
            else:
                logger.info("cd already loaded")
        
        if self.on_button_press:
            try:
                self.on_button_press(button_name)
            except Exception as e:
                logger.error(f"error in custom callback: {e}")
    
    def is_enabled(self) -> bool:
        return self.enabled and self.initialized
    
    def cleanup(self):
        """Limpa recursos GPIO"""
        if self.enabled and self.initialized:
            try:
                for button in self.buttons.values():
                    button.close()
                self.buttons.clear()
                logger.info("gpio cleaned")
            except Exception as e:
                logger.debug(f"error cleaning gpio: {e}")


"""
COMO USAR:

1. HARDWARE:
   - Conecte botões entre os pinos GPIO e GND
   - Não precisa resistores (pull-up interno ativado)
   
   Exemplo de conexão:
   GPIO 17 ──┬──[ Botão ]──┬── GND
             │              │
             └──────────────┘

2. SOFTWARE:
   
   # Em config.py, habilite GPIO:
   GPIO_ENABLED = True
   
   # No seu código principal:
   from gpio_controller import GPIOController
   
   controller = CDPlayerController()
   gpio = GPIOController(controller)
   
   # Callback opcional para eventos de botão
   def on_button(button_name):
       print(f"Botão {button_name} pressionado!")
   
   gpio.on_button_press = on_button
   
   # Ao encerrar:
   gpio.cleanup()

3. TESTE:

   # Teste se GPIO está funcionando:
   if gpio.is_enabled():
       print("\033[0;32m✓\033[0m gpio operational")
   else:
       print("\033[0;31m✗\033[0m gpio unavailable")

4. CUSTOMIZAÇÃO:
   
   # Alterar pinos em config.py:
   GPIO_PINS = {
       'play_pause': 17,  # Seu pino preferido
       'stop': 27,
       # ...
   }
   
   # Ajustar debounce (ms):
   GPIO_BOUNCE_TIME = 200

5. VANTAGENS DO gpiozero:
   
   - API mais simples e Pythonica
   - Não precisa cleanup() explícito (mas pode usar)
   - Suporte nativo a eventos
   - Melhor tratamento de erros
   - Funciona com pigpio (melhor performance) ou modo local

6. ESQUEMA SUGERIDO:
   
   ┌─────────────────────────────────────┐
   │  Raspberry Pi GPIO Header           │
   │                                     │
   │  3.3V  [1] [2]  5V                 │
   │  GPIO2 [3] [4]  5V                 │
   │  GPIO3 [5] [6]  GND                │
   │  GPIO4 [7] [8]  GPIO14             │
   │  GND   [9] [10] GPIO15             │
   │  GPIO17[11][12] GPIO18  ← Play     │
   │  GPIO27[13][14] GND                │
   │  GPIO22[15][16] GPIO23             │
   │  3.3V  [17][18] GPIO24             │
   │  ...                                │
   └─────────────────────────────────────┘
   
   Play:       GPIO17 (Pin 11) -> GND
   Pause:      GPIO26 (Pin 37) -> GND
   Stop:       GPIO27 (Pin 13) -> GND
   Next:       GPIO22 (Pin 15) -> GND
   Prev:       GPIO23 (Pin 16) -> GND
   Eject:      GPIO24 (Pin 18) -> GND
   Load:       GPIO25 (Pin 22) -> GND

TROUBLESHOOTING:

Q: Erro "Permission denied"
A: gpiozero geralmente não precisa sudo. Se precisar, adicione usuário ao grupo gpio:
   sudo usermod -a -G gpio $USER
   # Ou instale pigpio para melhor suporte:
   sudo apt-get install pigpio
   sudo systemctl enable pigpio
   sudo systemctl start pigpio

Q: Botões não respondem
A: Verifique conexões, use multímetro para testar continuidade
   Verifique se gpiozero está instalado: pip list | grep gpiozero

Q: Múltiplos triggers por pressão
A: Aumente GPIO_BOUNCE_TIME em config.py

Q: Quer melhor performance?
A: Use pigpio (opcional mas recomendado):
   sudo apt-get install pigpio
   sudo systemctl enable pigpio
   sudo systemctl start pigpio
   # O código detecta automaticamente e usa pigpio se disponível
"""
