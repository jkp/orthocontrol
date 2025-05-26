# orthocontrol/control/controller.py

from typing import List, Optional
from .base import MediaControlStrategy
# We will import specific strategies here later
# from .applescript_strategy import AppleScriptMediaStrategy
# from .spotify_api_strategy import SpotifyApiMediaStrategy
# from .system_keys_strategy import SystemMediaKeysStrategy

class MediaController:
    def __init__(self, strategies: List[MediaControlStrategy], primary_app_name: Optional[str] = None):
        self._strategies = strategies
        self._primary_app_name = primary_app_name
        # TODO: Add logic for preferred_mode (e.g., api_first, applescript_only)

    # TODO: Implement methods like get_volume, set_volume, toggle_play_pause
    pass
