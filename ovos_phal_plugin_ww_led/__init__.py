"""Wake word LED entrypoint PHAL plugin
"""
from time import sleep
from json_database import JsonConfigXDG
from ovos_plugin_manager.phal import PHALPlugin
from ovos_utils import create_daemon
from ovos_utils.log import LOG
from typing import Optional

from RPi import GPIO
try:
    import board
    import adafruit_dotstar as dotstar
except ImportError:
    LOG.error("adafruit-circuitpython-dotstar not installed, disabling DotStar")


class WwLedPlugin(PHALPlugin):
    """This is the place where all the magic happens for the
    wake word LED PHAL plugin.
    """
    blue = (0, 0, 255)
    cyan = (0, 255, 255)
    green = (0, 255, 0)
    magenta = (255, 0, 255)
    off = (0, 0 , 0 )
    orange = (255, 165, 0)
    purple = (128, 0, 128)
    red = ( 255, 0, 0)
    white = (255, 255, 255)
    yellow = (255, 255, 0)
    light_blue = (173, 216, 230)
    light_green = (144, 238, 144)
    light_magenta = (255, 128, 255)

    def __init__(self, bus=None, config=None):
        super().__init__(bus=bus, name="ovos-phal-plugin-ww-led", config=config)

        # Retrieves settings from ~/.config/OpenVoiceOS/ovos-phal-plugin-ww-led.json
        self.settings = JsonConfigXDG(self.name, subfolder="OpenVoiceOS")
        # single-pin mode:
        pin = self.settings.get("gpio_pin", None)
        # DotStar mode:
        self.use_dotstar = self.settings.get("use_dotstar", False)
        self.listen_color = self.settings.get("listen_color", "green")
        self.speak_color = self.settings.get("speak_color", "blue")
        self.data_pin  = self.settings.get("data_pin", pin)
        self.clock_pin = self.settings.get("clock_pin", 6)
        self.num_leds = self.settings.get("num_leds", 1)

        self.wakeword_only = self.settings.get("wakeword_only", False)
        self.pulse = self.settings.get("pulse", True)

        # Default values
        self.duty_cycle = 0
        self.pwm = None
        self.pulsing = False

        try:
            # configure pins
            if self.use_dotstar:
                self._data = getattr(board, f'D{self.data_pin}')
                self._clock = getattr(board, f'D{self.clock_pin}')

                self.strip = dotstar.DotStar(self._clock,
                                            self._data,
                                            n=self.num_leds,
                                            brightness=0.5,
                                            auto_write=False)
                self.strip.fill(getattr(self, self.listen_color))
                self.strip.show()
                sleep(0.25)
                self.strip.fill(getattr(self, self.speak_color))
                self.strip.show()
                sleep(0.25)
                self.strip.fill(self.off)
                self.strip.show()

            else:
                # Setup GPIO
                # By default the GPIO module will be configured with BCM.
                # https://raspberrypi.stackexchange.com/a/12967
                GPIO.setmode(GPIO.BCM)
                GPIO.setwarnings(False)
                GPIO.setup(self.data_pin, GPIO.OUT)

            if self.pulse:
                if self.use_dotstar:
                    # start at zero brightness
                    self.strip.brightness = 0.0
                    self.strip.show()
                else:
                    self.pwm = GPIO.PWM(self.data_pin, 100)
                    self.pwm.start(self.duty_cycle)
            # Map bus events to methods
            self.bus.on("recognizer_loop:record_begin", self._handle_listener_started)
            self.bus.on("recognizer_loop:record_end", self._handle_led_off)
            self.bus.on("recognizer_loop:audio_output_start", self._handle_speaking_started)
            self.bus.on("recognizer_loop:audio_output_end", self._handle_led_off)
            self.bus.on("ovos.utterance.cancelled", self._handle_led_off)
            self.bus.on("ovos.utterance.handled", self._handle_led_off)
        except RuntimeError:
            if self.use_dotstar:
                LOG.error("Cannot initialize DotStar - plugin will not load")
            else:
                LOG.error("Cannot initialize GPIO - plugin will not load")

    def led_pulsing_thread(self, color: Optional[tuple[int, int, int]] = None):
        """Wrapper function calling the create_daemon() method from ovos-utils
        to start a thread.
        """
        create_daemon(target=self._pulsing, kwargs={"color": color})

    def _pulsing(self, color: Optional[tuple[int, int, int]] = None):
        """Watchdog for the create_daemon() method
        This will make the LED pulse based on the self.duty_cycle variable.
        """
        if color is None:
            color = getattr(self, self.listen_color)

        while self.pulsing:
            for duty in range(0, 101, 5):
                if self.use_dotstar:
                    self.strip.fill(color)
                    self.strip.brightness = duty/200.0
                    self.strip.show()
                else:
                    self.pwm.ChangeDutyCycle(duty)
                sleep(0.05)
            for duty in range(100, -1, -5):
                if self.use_dotstar:
                    self.strip.fill(color)
                    self.strip.brightness = duty/200.0
                    self.strip.show()
                else:
                    self.pwm.ChangeDutyCycle(duty)
                sleep(0.05)
        if self.use_dotstar:
            self.strip.fill(self.off)
            self.strip.show()
        else:
            GPIO.output(self.data_pin, GPIO.LOW)

    def _handle_listener_started(self, _):
        """Handle the record_begin event detection and turn the LED on."""
        if self.use_dotstar:
            # DotStar mode
            if self.pulse:
                self.pulsing = True
                self.led_pulsing_thread()
            else:
                self.strip.fill(getattr(self, self.listen_color))
                self.strip.show()
        else:
            # single-GPIO mode
            if self.pulse:
                self.pulsing = True
                self.led_pulsing_thread()
            else:
                GPIO.output(self.data_pin, GPIO.HIGH)

    def _handle_speaking_started(self, _):
        """Handle the audio_output_startd event detection and turn the LED on."""
        if self.use_dotstar:
            # DotStar mode
            if self.pulse:
                self.pulsing = True
                self.led_pulsing_thread(color=getattr(self, self.speak_color))
            else:
                # full-white
                self.strip.fill(getattr(self, self.speak_color))
                self.strip.show()
        else:
            # single-GPIO mode
            if self.pulse:
                self.pulsing = True
                self.led_pulsing_thread()
            else:
                GPIO.output(self.data_pin, GPIO.HIGH)

    def _handle_led_off(self, _):
        """Handle the different events that will lead to turn the LED off."""
        if not self.wakeword_only:
            if self.use_dotstar:
                # DotStar mode
                if self.pulse:
                    self.pulsing = False
                else:
                    # Off
                    self.strip.fill(self.off)
                    self.strip.show()
            else:
                # single-GPIO mode
                if self.pulse:
                    self.pulsing = False
                else:
                    GPIO.output(self.data_pin, GPIO.LOW)
