import sys
import subprocess
import getopt
import rtmidi
import time
from functools import wraps
from threading import Timer
from Quartz.CoreGraphics import CGEventPost, kCGHIDEventTap
from AppKit import NSEvent
from CoreMIDI import MIDIRestart
import logging

# Constants
CODE_PLAY = 16

def setup_logging(level='info'):
    level_dict = {
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'warning': logging.WARNING,
        'error': logging.ERROR,
        'critical': logging.CRITICAL
    }
    numeric_level = level_dict.get(level.lower(), logging.INFO)  # Default to INFO if level is not recognized
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def process_command_line_args():
    try:
        options, _ = getopt.getopt(
            sys.argv[1:],
            '',
            ["midi-name=", "midi-restart", "midi-restart-interval=", "midi-sysex", "midi-notifications", "log-level="]
        )
        options = dict(options)
        if "--midi-name" not in options:
            logging.error("Missing --midi-name argument")
            sys.exit(1)
        if "--log-level" in options:
            setup_logging(options["--log-level"])
        else:
            setup_logging()  # Default setup if no log level specified
        logging.info("Command line arguments processed successfully.")
        return options
    except getopt.GetoptError as e:
        logging.error(f"Command line error: {e}")
        sys.exit(1)

def throttle_debounce(throttle_ms, debounce_ms):
    throttle_interval = throttle_ms / 1000.0
    debounce_interval = debounce_ms / 1000.0

    def decorator(func):
        last_call = [0]
        debounce_timer = [None]

        @wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            if debounce_timer[0] is not None:
                debounce_timer[0].cancel()

            if now - last_call[0] > throttle_interval:
                last_call[0] = now
                func(*args, **kwargs)
            else:
                def call_it():
                    func(*args, **kwargs)
                    last_call[0] = time.time()
                debounce_timer[0] = Timer(debounce_interval, call_it)
                debounce_timer[0].start()

        return wrapper
    return decorator

def set_application_volume(app_name, volume):
    if not 0 <= volume <= 100:
        raise ValueError("Volume must be between 0 and 100.")
    script = f"""
    tell application "System Events"
        if exists (application process "{app_name}") then
            tell application "{app_name}"
                set sound volume to {volume}
            end tell
        end if
    end tell
    """
    try:
        subprocess.run(["osascript", "-e", script], check=True)
        logging.debug(f"{app_name} volume set to {volume}%.")
    except subprocess.CalledProcessError:
        logging.error(f"Failed to set {app_name} volume.")

@throttle_debounce(throttle_ms=250, debounce_ms=100)
def set_volume(volume):
    logging.debug(f"Setting volume to {volume}%.")
    set_application_volume("Music", volume)
    set_application_volume("Spotify", volume)

def tap(code, flags=0):
    event = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
        14, (0, 0), 0xA00 + flags, 0, 0, 0, 8, (code << 16) | (0xA << 8), -1
    )
    CGEventPost(kCGHIDEventTap, event.CGEvent())

def toggle_play_pause():
    logging.debug("Toggling play/pause")
    tap(CODE_PLAY)

def midi_callback(message, time_stamp):
    message_type, note, velocity = message[0]

    if message_type == 176:
        volume_percentage = int((velocity / 127.0) * 100)
        set_volume(volume_percentage)
        logging.debug(f"Volume adjusted to {volume_percentage}% based on MIDI control.")

    elif message_type == 144:
        toggle_play_pause()
        logging.debug(f"Play/Pause toggled based on MIDI note {note}.")

def main():
    options = process_command_line_args()
    midi_in = rtmidi.MidiIn()
    midi_out = rtmidi.MidiOut()

    port_name = options["--midi-name"]
    restart_interval = float(options.get("--midi-restart-interval", 1.0))
    sysex_enable = "--midi-sysex" in options
    restart_enable = "--midi-restart" in options

    while True:
        ports_in = midi_in.get_ports()
        ports_out = midi_out.get_ports()
        if port_name in ports_in and port_name in ports_out:
            try:
                with midi_in.open_port(ports_in.index(port_name)) as port_in, \
                     midi_out.open_port(ports_out.index(port_name)) as port_out:
                    if sysex_enable:
                        midi_out.send_message([0xF0, 0x00, 0x20, 0x76, 0x02, 0x00, 0x02, 0x00, 0xF7])
                    midi_in.set_callback(midi_callback)
                    while port_name in midi_in.get_ports() and port_name in midi_out.get_ports():
                        time.sleep(restart_interval)
                    midi_in.cancel_callback()
            except Exception as e:
                logging.error(f"Error with MIDI port {port_name}: {str(e)}")
        else:
            logging.info(f"Port unavailable: '{port_name}'")

        if restart_enable:
            MIDIRestart()
        time.sleep(restart_interval)

if __name__ == "__main__":
    main()
