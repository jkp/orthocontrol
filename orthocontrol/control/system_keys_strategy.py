# orthocontrol/control/system_keys_strategy.py

import logging
from typing import override # For Python 3.12+

from AppKit import NSEvent
from Quartz import CoreGraphics as CG

from .base import MediaControlStrategy

# Key codes for media keys (subset)
# Full list can be found in IOKit/hidsystem/ev_keymap.h
NX_KEYTYPE_PLAY = 16
NX_KEYTYPE_NEXT = 17
NX_KEYTYPE_PREVIOUS = 18
NX_KEYTYPE_FAST = 19 # Fast Forward
NX_KEYTYPE_REWIND = 20
# For volume, typically system handles these directly or via AppleScript for specific apps.
# NX_KEYTYPE_SOUND_UP = 0
# NX_KEYTYPE_SOUND_DOWN = 1
# NX_KEYTYPE_MUTE = 7

class SystemMediaKeysStrategy(MediaControlStrategy):
    def __init__(self):
        # This strategy doesn't require specific client initialization
        pass

    def _send_media_key_event(self, key_code: int) -> bool:
        """Helper function to send a media key event. Returns True on success, False otherwise."""
        try:
            # Create an HID event for the key press down
            # NSSystemDefined event, type for media keys is 14
            # Subtype is 8 for media keys
            # data1: (key_code << 16) | (0xa << 8) for key down (0xa)
            # data1: (key_code << 16) | (0xb << 8) for key up (0xb)
            # data2: -1 for media keys

            # Key Down
            ev_down = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                14, (0, 0), 0xa00, 0, 0, None, 8, (key_code << 16) | (0xA << 8), -1
            )
            CG.CGEventPost(CG.kCGHIDEventTap, ev_down.CGEvent())

            # Key Up
            ev_up = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                14, (0, 0), 0xa00, 0, 0, None, 8, (key_code << 16) | (0xB << 8), -1 # Modifier flags can be same as down, state change is in data1
            )
            CG.CGEventPost(CG.kCGHIDEventTap, ev_up.CGEvent())
            logging.debug(f"SystemMediaKeys: Sent key event for code {key_code}.")
            return True
        except Exception as e:
            logging.error(f"SystemMediaKeys: Failed to send key event for code {key_code}: {e}")
            return False

    @property
    @override
    def name(self) -> str:
        return "SystemMediaKeys"

    @override
    def is_available(self, app_name: str) -> bool:
        # app_name is ignored as media keys are system-wide.
        # This strategy is generally always available on macOS.
        return True

    @override
    def get_volume(self, app_name: str) -> int | None:
        # Media keys typically don't provide a way to query current volume.
        # This would require a different mechanism (like AppleScript for a specific app, or system calls).
        logging.debug("SystemMediaKeys: get_volume is not supported.")
        return None

    @override
    def set_volume(self, app_name: str, volume_percent: int) -> bool:
        # Media keys send discrete 'up' or 'down' commands, not specific percentages.
        # To simulate volume up/down, one would call _send_media_key_event with NX_KEYTYPE_SOUND_UP/DOWN.
        # However, the MediaControlStrategy expects setting a specific percentage.
        logging.debug("SystemMediaKeys: set_volume to a specific percentage is not supported. Use for discrete up/down if needed.")
        return False

    @override
    def toggle_play_pause(self, app_name: str) -> bool:
        # app_name is ignored.
        logging.debug("SystemMediaKeys: Sending Play/Pause key event.")
        return self._send_media_key_event(NX_KEYTYPE_PLAY)

    # Example future extensions for other media keys:
    # def next_track(self, app_name: str) -> bool:
    #     logging.debug("SystemMediaKeys: Sending Next Track key event.")
    #     return self._send_media_key_event(NX_KEYTYPE_NEXT)

    # def previous_track(self, app_name: str) -> bool:
    #     logging.debug("SystemMediaKeys: Sending Previous Track key event.")
    #     return self._send_media_key_event(NX_KEYTYPE_PREVIOUS)
