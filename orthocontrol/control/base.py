from typing import Protocol

class MediaControlStrategy(Protocol):
    """Defines the interface for a media control strategy."""

    @property
    def name(self) -> str:
        """Returns the unique name of the strategy (e.g., 'AppleScript', 'SpotifyAPI')."""
        ...

    def is_available(self, app_name: str) -> bool:
        """Checks if this strategy is available and configured for the given app."""
        ...

    def get_volume(self, app_name: str) -> int | None:
        """Gets the volume for the specified application. Returns None if not supported or error."""
        ...

    def set_volume(self, app_name: str, volume_percent: int) -> bool:
        """Sets the volume for the specified application. Returns True on success, False otherwise."""
        ...

    def toggle_play_pause(self, app_name: str) -> bool:
        """Toggles play/pause for the specified application. Returns True on success, False otherwise."""
        ...

    # Future extensions could include:
    # def next_track(self, app_name: str) -> bool: ...
    # def previous_track(self, app_name: str) -> bool: ...
    # def get_playback_state(self, app_name: str) -> dict | None: ...
