import psutil
import sys
import subprocess
import getopt
import rtmidi # type: ignore[reportMissingModuleSource]
import time
from functools import wraps, partial
from threading import Timer, Thread, Lock, Event
import threading
from typing import Callable, TypeVar, Any
from Quartz.CoreGraphics import CGEventPost, kCGHIDEventTap
from AppKit import NSEvent
from CoreMIDI import MIDIRestart
import logging
from dotenv import load_dotenv
import spotipy # type: ignore[reportMissingModuleSource]
from spotipy.exceptions import SpotifyException # type: ignore[reportMissingModuleSource]
from spotipy.oauth2 import SpotifyOAuth # type: ignore[reportMissingModuleSource]

# Constants
CODE_PLAY = 16  # Default MIDI code for play/pause
LATCH_TOLERANCE_PERCENT = 3 # Tolerance for latching remote to app volume

# Global State for Latching
actual_app_volume_on_connect: int | None = None
is_latched: bool = False

# Global Spotify Client
sp: "spotipy.Spotify | None" = None

# Volume sync thread variables
target_volume: int | None = None
target_volume_lock = Lock()
volume_sync_thread: Thread | None = None
stop_sync_thread = False

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

def throttle_debounce(throttle_ms: int, debounce_ms: int, first_call_threshold_ms: int = 500, 
                  initial_throttle_ms: int = 50, max_throttle_ms: int = 500, 
                  backoff_factor: float = 1.5) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that combines throttling and debouncing with a special case for the first call and backoff.
    
    Args:
        throttle_ms: Base throttle time between executions in milliseconds (used as a reference)
        debounce_ms: Time to wait after last call before executing in milliseconds
        first_call_threshold_ms: Time threshold in ms to consider a call as the first in a new interaction
        initial_throttle_ms: Starting throttle time for a new interaction sequence in milliseconds
        max_throttle_ms: Maximum throttle time to reach with backoff in milliseconds
        backoff_factor: Multiplier for increasing throttle time with each call
        
    Returns:
        Decorated function with throttling, debouncing, and backoff behavior
    """
    # Convert to seconds for internal use
    debounce_interval = debounce_ms / 1000.0
    first_call_interval_threshold = first_call_threshold_ms / 1000.0
    initial_throttle_interval = initial_throttle_ms / 1000.0
    max_throttle_interval = max_throttle_ms / 1000.0

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        last_call_time: list[float] = [0.0]  # Time of the last throttled execution
        # Time of the last actual execution (either throttled or debounced), marks end of an interaction sequence
        last_interaction_end_time: list[float] = [0.0]
        debounce_timer: list[Timer | None] = [None]
        # Track the current throttle interval with backoff
        current_throttle_interval: list[float] = [initial_throttle_interval]

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> None:
            now = time.time()

            if debounce_timer[0] is not None:
                debounce_timer[0].cancel()
                debounce_timer[0] = None

            is_new_interaction = (now - last_interaction_end_time[0]) > first_call_interval_threshold

            if is_new_interaction:
                # First call in a new interaction sequence: execute immediately and reset throttle interval
                logging.debug(f"throttle_debounce: New interaction - immediate call for {getattr(func, '__name__', 'decorated_function')}")
                # Reset throttle interval to initial value for new interaction
                current_throttle_interval[0] = initial_throttle_interval
                logging.debug(f"throttle_debounce: Reset throttle interval to {current_throttle_interval[0]*1000:.1f}ms")
                func(*args, **kwargs)
                last_call_time[0] = now
                last_interaction_end_time[0] = now
            else:
                # Subsequent call in an ongoing interaction: apply throttle/debounce with backoff
                if now - last_call_time[0] > current_throttle_interval[0]:
                    # Throttle condition met: execute immediately and increase throttle interval
                    logging.debug(f"throttle_debounce: Throttled call for {getattr(func, '__name__', 'decorated_function')} at {current_throttle_interval[0]*1000:.1f}ms")
                    func(*args, **kwargs)
                    last_call_time[0] = now
                    last_interaction_end_time[0] = now
                    
                    # Apply backoff to throttle interval for next call
                    new_throttle = min(current_throttle_interval[0] * backoff_factor, max_throttle_interval)
                    if new_throttle != current_throttle_interval[0]:
                        logging.debug(f"throttle_debounce: Increasing throttle interval from {current_throttle_interval[0]*1000:.1f}ms to {new_throttle*1000:.1f}ms")
                        current_throttle_interval[0] = new_throttle
                else:
                    # Throttle condition not met: set up debounce
                    def call_it_debounced():
                        logging.debug(f"throttle_debounce: Debounced call for {getattr(func, '__name__', 'decorated_function')}")
                        func(*args, **kwargs)
                        # Update last_call_time as this is an execution, helps throttle next immediate if any
                        current_time_debounced = time.time()
                        last_call_time[0] = current_time_debounced 
                        last_interaction_end_time[0] = current_time_debounced
                    
                    logging.debug(f"throttle_debounce: Setting up debounce for {getattr(func, '__name__', 'decorated_function')}")
                    debounce_timer[0] = Timer(debounce_interval, call_it_debounced)
                    debounce_timer[0].start()

        return wrapper
    return decorator

def is_process_running(app_name):
    """Check if there is any running process that contains the given name app_name."""
    for process in psutil.process_iter(['name']):
        if app_name.lower() in process.info['name'].lower():
            return True
    return False

def get_application_volume(app_name: str) -> int | None:
    """Get the current sound volume of a given application."""
    global sp
    if app_name == "Spotify" and sp:
        api_volume = get_spotify_volume_api()
        if api_volume is not None:
            return api_volume
        # Fall through to AppleScript if API fails for Spotify
        logging.debug("Spotify API failed to get volume, falling back to AppleScript for Spotify.")

    if not is_process_running(app_name):
        logging.debug(f"{app_name} is not running, cannot get volume.")
        return None

    script = f"""
    tell application \"System Events\"
        if exists (application process \"{app_name}\") then
            tell application \"{app_name}\"
                try
                    return sound volume
                on error errMsg number errNum
                    return \"Error: \" & errMsg & \" (\" & errNum & \")\"
                end try
            end tell
        else
            return \"Error: App not running\"
        end if
    end tell
    """
    volume_str_for_error_log = "<not captured>"
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True)
        volume_str_for_error_log = result.stdout.strip()
        if volume_str_for_error_log.startswith("Error:"):
            logging.warning(f"Could not get {app_name} volume: {volume_str_for_error_log}")
            return None
        volume = int(volume_str_for_error_log)
        logging.info(f"Initial volume for {app_name}: {volume}%")
        return volume
    except subprocess.CalledProcessError as e:
        error_output = "<no stderr>"
        if isinstance(e.stderr, str):
            error_output = e.stderr.strip()
        elif isinstance(e.stderr, bytes):
            # Decode if bytes, replacing errors, then strip
            error_output = e.stderr.decode(errors='replace').strip()
        logging.error(f"Failed to get {app_name} volume via AppleScript. Error: {error_output}")
        return None
    except ValueError:
        logging.error(f"Could not parse volume for {app_name} from AppleScript output: '{volume_str_for_error_log}'")
        return None

def set_application_volume(app_name, volume):
    if not 0 <= volume <= 100:
        raise ValueError("Volume must be between 0 and 100.")

    # Early exit if the application is not running
    if not is_process_running(app_name):
        logging.debug(f"{app_name} is not running.")
        return

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
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to set {app_name} volume.", exc_info=e)

def get_spotify_volume_api() -> int | None:
    """Gets the current volume from Spotify via API."""
    global sp
    if not sp:
        return None
    try:
        playback = sp.current_playback()
        if playback and playback.get('device') and playback['device'].get('volume_percent') is not None:
            volume = playback['device']['volume_percent']
            logging.debug(f"Spotify API: Current volume is {volume}%")
            return int(volume)
        else:
            logging.debug("Spotify API: No active device or volume info found.")
            return None
    except SpotifyException as e:
        logging.warning(f"Spotify API error getting volume: {e}")
        if "authentication credentials" in str(e).lower() or "token expired" in str(e).lower():
            logging.error("Spotify token may be invalid or expired. Please update SPOTIFY_TOKEN in .env")
        return None
    except Exception as e:
        logging.error(f"Unexpected error getting Spotify volume via API: {e}")
        return None

def set_spotify_volume_api(volume_percent: int) -> bool:
    """Sets Spotify volume using the API, returns True on success."""
    global sp
    if not sp:
        logging.warning("Spotify API: Spotipy client not initialized, cannot set volume.")
        return False
    # Clamp volume_percent to Spotify's valid range (0-100)
    clamped_volume = max(0, min(100, volume_percent))
    try:
        sp.volume(clamped_volume) # type: ignore
        logging.debug(f"Spotify API: Volume set to {clamped_volume}%")
        return True
    except SpotifyException as e:
        logging.warning(f"Spotify API error setting volume: {e}")
        if "authentication credentials" in str(e).lower() or "token expired" in str(e).lower():
            logging.error("Spotify token may be invalid or expired. Please update SPOTIFY_TOKEN in .env")
        if "restricted device" in str(e).lower() or "not active" in str(e).lower() or ": NO_ACTIVE_DEVICE" in str(e).upper():
             logging.warning("Spotify API: Cannot set volume. No active device or device is restricted.")
        # Attempt to find an active device and transfer playback if none is active - simplified
        try:
            devices = sp.devices() # type: ignore
            if devices and devices.get('devices'):
                active_or_first_device_id: str | None = None
                for device in devices['devices']:
                    if device.get('is_active'):
                        active_or_first_device_id = device.get('id')
                        break
                if not active_or_first_device_id and devices['devices']:
                    # Fallback to first available device if no active one was found
                    active_or_first_device_id = devices['devices'][0].get('id') 
                
                if active_or_first_device_id:
                    logging.info(f"Spotify API: Attempting to transfer playback to device ID {active_or_first_device_id} and retry volume set.")
                    sp.transfer_playback(device_id=active_or_first_device_id, force_play=False) # type: ignore
                    time.sleep(0.5) # Give a moment for transfer to occur
                    sp.volume(clamped_volume) # type: ignore # Retry volume set
                    logging.debug(f"Spotify API: Volume set to {clamped_volume}% after playback transfer.")
                    return True
        except SpotifyException as transfer_e:
            logging.error(f"Spotify API: Failed to transfer playback or set volume after transfer: {transfer_e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error setting Spotify volume via API: {e}")
        return False

def set_volume(volume_percentage: int):
    """Simply updates the target volume. Worker thread handles syncing."""
    global target_volume
    
    with target_volume_lock:
        if target_volume != volume_percentage:
            logging.debug(f"Target volume: {volume_percentage}%")
        target_volume = volume_percentage


def tap(code: int, flags: int = 0):
    event = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
        14, # NSSystemDefined
        (0, 0), 
        0xA00 + flags, 
        0, 
        0, 
        0, 
        8, 
        (code << 16) | (0xA << 8), 
        -1
    )
    CGEventPost(kCGHIDEventTap, event.CGEvent())


def toggle_play_pause():
    tap(CODE_PLAY)


def volume_sync_worker():
    """Simple fixed-rate sync with rate limit protection."""
    global target_volume, stop_sync_thread, sp
    
    last_synced_volume = None
    last_sync_time = 0
    rate_limited_until = 0
    
    SYNC_INTERVAL = 0.25  # 250ms = 4 updates/second max
    RATE_LIMIT_BACKOFF = 10.0  # 10 seconds when rate limited
    
    logging.info("Volume sync worker started (250ms interval)")
    
    while not stop_sync_thread:
        try:
            time.sleep(0.05)  # Small sleep to prevent CPU spinning
            now = time.time()
            
            # Skip if rate limited
            if now < rate_limited_until:
                continue
            
            # Skip if too soon since last sync
            if now - last_sync_time < SYNC_INTERVAL:
                continue
            
            # Get current target
            with target_volume_lock:
                current_target = target_volume
            
            # Sync if changed
            if current_target is not None and current_target != last_synced_volume:
                logging.info(f"Syncing volume: {last_synced_volume}% → {current_target}%")
                
                try:
                    if sp and set_spotify_volume_api(current_target):
                        last_synced_volume = current_target
                        last_sync_time = now
                except SpotifyException as e:
                    if hasattr(e, 'http_status') and e.http_status == 429:
                        logging.warning(f"RATE LIMITED! Backing off for {RATE_LIMIT_BACKOFF} seconds")
                        rate_limited_until = now + RATE_LIMIT_BACKOFF
                    else:
                        logging.error(f"Spotify error: {e}")
                except Exception as e:
                    logging.error(f"Unexpected error: {e}")
            
        except Exception as e:
            logging.error(f"Worker error: {e}")
            time.sleep(1.0)
    
    logging.info("Volume sync worker stopped")


def midi_callback(message: tuple[list[int], float], _time_stamp: float, sysex_enabled: bool = False, log_level: str = 'info'):
    """Process MIDI messages instantly - no throttling here!"""
    global is_latched, actual_app_volume_on_connect, LATCH_TOLERANCE_PERCENT

    logging.debug(f"MIDI message received: {message}")
    message_type, note, velocity = message[0]

    if sysex_enabled:
        logging.info(f"MIDI Raw (SYSEX Mode): Type={message_type}, Note={note}, Velocity={velocity}")
    elif log_level == 'debug':
        logging.debug(f"MIDI Raw: Type={message_type}, Note={note}, Velocity={velocity}")

    if message_type == 176:  # CC message
        remote_value_percent = int((velocity / 127.0) * 100)

        if not is_latched:
            if actual_app_volume_on_connect is not None:
                if abs(remote_value_percent - actual_app_volume_on_connect) <= LATCH_TOLERANCE_PERCENT:
                    is_latched = True
                    logging.info(f"Remote latched at {remote_value_percent}%. App volume was {actual_app_volume_on_connect}%. Control engaged.")
                    set_volume(remote_value_percent)
                else:
                    logging.debug(
                        f"Waiting for latch: Remote at {remote_value_percent}%, App at {actual_app_volume_on_connect}%. "
                        f"Difference {abs(remote_value_percent - actual_app_volume_on_connect)}% > {LATCH_TOLERANCE_PERCENT}%"
                    )
            else:
                # No initial app volume, latch immediately
                is_latched = True
                logging.info(f"No initial app volume. Remote latched immediately at {remote_value_percent}%. Control engaged.")
                set_volume(remote_value_percent)
        else:
            # Already latched - just update the target instantly!
            set_volume(remote_value_percent)

    elif message_type == 144:  # Note On message
        toggle_play_pause()
        logging.debug(f"Play/Pause toggled based on MIDI note {note}.")


def main():
    options = process_command_line_args()

    # Load environment variables from .env file
    _ = load_dotenv()

    # Spotify setup using SpotifyOAuth
    global sp
    spotify_scope = "user-read-playback-state user-modify-playback-state"

    try:
        auth_manager = SpotifyOAuth(
            scope=spotify_scope,
            # client_id, client_secret, redirect_uri will be picked up from env vars:
            # SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI
            # You can also explicitly pass them here if preferred, e.g.:
            # client_id=os.getenv('SPOTIPY_CLIENT_ID'),
            # client_secret=os.getenv('SPOTIPY_CLIENT_SECRET'),
            # redirect_uri=os.getenv('SPOTIPY_REDIRECT_URI'),
            open_browser=True, # Set to True to re-enable automatic browser opening
        )
        # Disable automatic retries to handle rate limits ourselves
        sp = spotipy.Spotify(auth_manager=auth_manager, retries=0)

        # Test if authentication was successful by making a simple API call
        try:
            current_user = sp.current_user()
            if current_user:
                logging.info(f"Successfully authenticated with Spotify as {current_user['display_name']} ({current_user['id']}).")
            else:
                logging.warning("Spotify authentication seemed to pass but could not fetch current user.")
        except SpotifyException as e:
            logging.error(f"Spotify authentication failed or token is invalid: {e}")
            logging.error("Please ensure SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, and SPOTIPY_REDIRECT_URI are correctly set in your .env file.")
            logging.error("If this is the first run, a browser window should open for authorization. If not, check console output.")
            logging.error("You might need to copy a URL from the console to your browser and then paste the redirected URL back into the console.")
            sp = None # Ensure sp is None if auth fails

    except Exception as e:
        logging.error(f"Failed to initialize Spotify client: {e}")
        sp = None # Ensure sp is None if auth fails

    # Initialize actual_app_volume_on_connect for Spotify if sp is available
    if sp:
        initial_spotify_volume = get_spotify_volume_api() # This now uses the authenticated sp
        if initial_spotify_volume is not None:
            global actual_app_volume_on_connect, is_latched
            actual_app_volume_on_connect = initial_spotify_volume
            is_latched = False # Reset latching state on connect
            logging.info(f"Initial Spotify volume (API): {actual_app_volume_on_connect}%. Latching will occur on first remote interaction.")
        else:
            logging.warning("Could not get initial Spotify volume via API after authentication.")
    else:
        logging.info("Spotify client not available. Spotify features will be disabled.")

    # MIDI setup
    midi_in = rtmidi.MidiIn()
    midi_out = rtmidi.MidiOut()
    sysex_enabled = "--midi-sysex" in options
    restart_interval = float(options.get("--midi-restart-interval", 1.0))
    current_log_level = options.get("--log-level", "info").lower()

    port_name = options["--midi-name"]
    restart_enable = "--midi-restart" in options

    while True:
        ports_in = midi_in.get_ports()
        ports_out = midi_out.get_ports()
        logging.info(f"Available MIDI input ports: {ports_in}")
        logging.info(f"Available MIDI output ports: {ports_out}")

        if port_name in ports_in and port_name in ports_out:
            try:
                with midi_in.open_port(ports_in.index(port_name)), \
                     midi_out.open_port(ports_out.index(port_name)):

                    if sysex_enabled:
                        sysex_message = [0xF0, 0x00, 0x20, 0x76, 0x02, 0x00, 0x02, 0x00, 0xF7]
                        logging.info(f"SYSEX Mode Enabled: Attempting to send SYSEX message: {sysex_message}")
                        try:
                            midi_out.send_message(sysex_message)
                            logging.info("SYSEX message sent successfully.")
                        except Exception as e:
                            logging.error(f"Failed to send SYSEX message: {e}")
                    
                    # Log initial volumes and set for latching
                    initial_spotify_volume = get_application_volume("Spotify")
                    if initial_spotify_volume is not None:
                        logging.info(f"Initial Spotify volume: {initial_spotify_volume}%")
                        if actual_app_volume_on_connect is None: # Prioritize Spotify
                            actual_app_volume_on_connect = initial_spotify_volume
                    
                    initial_music_volume = get_application_volume("Music")
                    if initial_music_volume is not None:
                        logging.info(f"Initial Music volume: {initial_music_volume}%")
                        if actual_app_volume_on_connect is None: # Use Music if Spotify wasn't available
                            actual_app_volume_on_connect = initial_music_volume

                    if actual_app_volume_on_connect is not None:
                        logging.info(f"App volume for latching set to: {actual_app_volume_on_connect}%")
                    else:
                        logging.warning("Could not determine initial application volume for latching. Will latch on first remote movement.")
                    
                    is_latched = False # Reset latch state on new connection

                    # Prepare callback with current sysex_enable status and log_level
                    callback_with_context = partial(midi_callback, sysex_enabled=sysex_enabled, log_level=current_log_level)
                    midi_in.set_callback(callback_with_context)
                    logging.info(f"'{port_name}' opened successfully. Callback set. Waiting for MIDI data...")
                    logging.info("Turn the knob on your Ortho Remote to test the connection.")
                    
                    # Start the volume sync worker thread
                    global volume_sync_thread, stop_sync_thread
                    stop_sync_thread = False
                    volume_sync_thread = Thread(target=volume_sync_worker, daemon=True)
                    volume_sync_thread.start()
                    
                    # Log initial volumes
                    _ = get_application_volume("Music")
                    _ = get_application_volume("Spotify")

                    while port_name in midi_in.get_ports() and port_name in midi_out.get_ports():
                        time.sleep(restart_interval)
                    
                    # Stop the sync thread when MIDI disconnects
                    stop_sync_thread = True
                    if volume_sync_thread:
                        volume_sync_thread.join(timeout=1.0)
                    
                    midi_in.cancel_callback()
            except Exception as e:
                logging.error(f"Error with MIDI port {port_name}: {str(e)}")
        else:
            logging.info(f"Port unavailable: '{port_name}'")

        if restart_enable:
            logging.info(f"Attempting MIDIRestart due to port '{port_name}' unavailability.")
            MIDIRestart()
        time.sleep(restart_interval)

if __name__ == "__main__":
    main()
