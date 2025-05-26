# orthocontrol/control/applescript_strategy.py

import subprocess
import logging
import psutil # For is_process_running
from typing import override

from .base import MediaControlStrategy

# Module-level helper functions for AppleScript execution
def _run_applescript_capture_output(script: str, app_name_for_log: str) -> tuple[str | None, str | None]:
    """Runs an AppleScript and captures its output. Returns (stdout, stderr)."""
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
        stdout = result.stdout.strip() if result.stdout else None
        stderr = result.stderr.strip() if result.stderr else None
        if result.returncode != 0:
            logging.warning(f"AppleScript for {app_name_for_log} exited with code {result.returncode}. Stderr: {stderr}")
        return stdout, stderr
    except FileNotFoundError: # pragma: no cover
        logging.error("osascript command not found. AppleScript execution is not possible.")
        return None, "osascript not found"
    except Exception as e: # pragma: no cover
        logging.error(f"Unexpected error running AppleScript for {app_name_for_log}: {e}")
        return None, str(e)

def _run_applescript_no_capture(script: str, app_name_for_log: str) -> bool:
    """Runs an AppleScript without capturing output. Returns True on success (exit code 0)."""
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=False, text=True, check=False)
        if result.returncode != 0:
            logging.warning(f"AppleScript for {app_name_for_log} (no capture) exited with code {result.returncode}.")
            return False
        return True
    except FileNotFoundError: # pragma: no cover
        logging.error("osascript command not found. AppleScript execution is not possible.")
        return False
    except Exception as e: # pragma: no cover
        logging.error(f"Unexpected error running AppleScript for {app_name_for_log} (no capture): {e}")
        return False

def is_process_running(app_name: str) -> bool:
    """Check if there is any running process that contains the given name app_name."""
    # This is a simplified check. For more robust checking, one might need to verify
    # the exact executable path or bundle identifier if false positives are an issue.
    try:
        for process in psutil.process_iter(['name']):
            if app_name.lower() in process.info['name'].lower():
                return True
    except psutil.Error as e:
        logging.debug(f"Error accessing process list for '{app_name}': {e}")
    return False

class AppleScriptMediaStrategy(MediaControlStrategy):
    @property
    @override
    def name(self) -> str:
        return "AppleScript"

    @override
    def is_available(self, app_name: str) -> bool:
        """Checks if the application is running, as AppleScript typically targets running apps."""
        if app_name.lower() not in ["spotify", "music"]:
             return False # Only support Spotify and Music for now
        return is_process_running(app_name)

    @override
    def get_volume(self, app_name: str) -> int | None:
        if not self.is_available(app_name):
            logging.debug(f"AppleScript strategy not available for {app_name} (get_volume). App may not be running or supported.")
            return None

        script = f"""
        tell application "System Events"
            if exists (application process "{app_name}") then
                tell application "{app_name}"
                    try
                        return sound volume
                    on error errMsg number errNum
                        return "Error: " & errMsg & " (" & errNum & ")"
                    end try
                end tell
            else
                return "Error: App not running"
            end if
        end tell
        """
        stdout, _ = _run_applescript_capture_output(script, app_name)
        if stdout and not stdout.startswith("Error:"):
            try:
                volume = int(stdout)
                logging.debug(f"AppleScript: Got volume {volume}% for {app_name}.")
                return volume
            except ValueError:
                logging.error(f"AppleScript: Could not parse volume for {app_name} from output: '{stdout}'")
                return None
        elif stdout:
            logging.warning(f"AppleScript: Could not get {app_name} volume: {stdout}")
        return None

    @override
    def set_volume(self, app_name: str, volume_percent: int) -> bool:
        if not (0 <= volume_percent <= 100):
            logging.error(f"AppleScript: Volume {volume_percent}% out of range (0-100) for {app_name}.")
            return False # Or raise ValueError
        
        # No explicit is_available check here, as set_application_volume in original code
        # also checked process running status implicitly via the AppleScript itself.
        # If the app isn't running, the script will do nothing or error gracefully.

        script = f"""
        tell application "System Events"
            if exists (application process "{app_name}") then
                tell application "{app_name}"
                    try
                        set sound volume to {volume_percent}
                    on error errMsg number errNum
                        log "Error setting volume for {app_name}: " & errMsg & " (" & errNum & ")"
                    end try
                end tell
            else
                log "{app_name} not running, cannot set volume."
            end if
        end tell
        """
        success = _run_applescript_no_capture(script, app_name)
        if success:
            logging.debug(f"AppleScript: Set volume for {app_name} to {volume_percent}% attempt sent.")
        return success # subprocess.run with check=False, so success means script ran, not necessarily that volume changed

    @override
    def toggle_play_pause(self, app_name: str) -> bool:
        if not self.is_available(app_name):
            logging.debug(f"AppleScript strategy not available for {app_name} (toggle_play_pause).")
            return False

        script = f"""
        tell application "System Events"
            if exists (application process "{app_name}") then
                tell application "{app_name}"
                    try
                        playpause
                    on error errMsg number errNum
                        log "Error toggling play/pause for {app_name}: " & errMsg & " (" & errNum & ")"
                    end try
                end tell
            else
                log "{app_name} not running, cannot toggle play/pause."
            end if
        end tell
        """
        success = _run_applescript_no_capture(script, app_name)
        if success:
            logging.debug(f"AppleScript: Toggle play/pause command sent to {app_name}.")
        return success
