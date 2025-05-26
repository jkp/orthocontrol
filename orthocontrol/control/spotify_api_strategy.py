# orthocontrol/control/spotify_api_strategy.py

import logging
from typing import override # For Python 3.12+

import spotipy
from spotipy.exceptions import SpotifyException

from .base import MediaControlStrategy

class SpotifyApiMediaStrategy(MediaControlStrategy):
    def __init__(self, sp_client: spotipy.Spotify | None):
        self._sp = sp_client

    @property
    @override
    def name(self) -> str:
        return "SpotifyAPI"

    @override
    def is_available(self, app_name: str) -> bool:
        if app_name.lower() != "spotify":
            return False
        if not self._sp:
            logging.debug("SpotifyAPI: Spotipy client not initialized.")
            return False
        # Further checks could involve trying a light API call, e.g., sp.me(), 
        # but that might be too slow for frequent checks.
        # For now, assume if client exists, it's potentially available.
        return True

    @override
    def get_volume(self, app_name: str) -> int | None:
        if not self.is_available(app_name):
            return None
        assert self._sp is not None # Ensured by is_available or should be

        try:
            playback = self._sp.current_playback()
            if playback and playback.get('device') and playback['device'].get('volume_percent') is not None:
                volume = int(playback['device']['volume_percent'])
                logging.debug(f"SpotifyAPI: Current volume is {volume}% via API.")
                return volume
            else:
                logging.debug("SpotifyAPI: No active device or volume info found for get_volume.")
                return None
        except SpotifyException as e:
            logging.warning(f"SpotifyAPI: SpotifyException getting volume: {e}")
            if "authentication credentials" in str(e).lower() or "token expired" in str(e).lower():
                logging.error("SpotifyAPI: Token may be invalid or expired. Please update SPOTIFY_TOKEN.")
            return None
        except Exception as e:
            logging.error(f"SpotifyAPI: Unexpected error getting volume: {e}")
            return None

    def _get_spotify_device_id_for_volume_control(self) -> str | None:
        """
        Attempts to find a suitable Spotify device ID for volume control.
        Prioritizes active devices, then preferred types (Computer, Speaker), then any available device.
        Will attempt to transfer playback to a non-active device if found.
        Returns the device ID if successful, otherwise None.
        """
        assert self._sp is not None
        logging.debug("SpotifyAPI: Searching for device for volume control.")

        try:
            # Check for currently active device first
            current_playback_info = self._sp.current_playback() # type: ignore
            active_device_id_from_playback: str | None = None
            active_device_name_from_playback: str | None = None
            is_playing_on_device = False

            if current_playback_info and (device_info := current_playback_info.get('device')):
                active_device_id_from_playback = device_info.get('id')
                active_device_name_from_playback = device_info.get('name', 'Unknown Device')
                is_playing_on_device = bool(current_playback_info.get('is_playing'))

            if active_device_id_from_playback and is_playing_on_device:
                logging.info(f"SpotifyAPI: Found active playing device: {active_device_name_from_playback} (ID: {active_device_id_from_playback}). Using this device.")
                return active_device_id_from_playback
            elif active_device_id_from_playback:
                logging.info(f"SpotifyAPI: Found current (possibly paused) device: {active_device_name_from_playback} (ID: {active_device_id_from_playback}). Using this device.")
                return active_device_id_from_playback

            logging.info("SpotifyAPI: No current device or not playing. Listing all available devices.")
            devices_info = self._sp.devices() # type: ignore
            if not devices_info or not devices_info.get("devices"):
                logging.warning("SpotifyAPI: No devices available at all.")
                return None

            all_devices = devices_info["devices"]
            target_device_id: str | None = None
            target_device_name: str | None = None

            preferred_device_types = ["Computer", "Speaker"]
            for dev_type in preferred_device_types:
                for device in all_devices:
                    if device.get("type") == dev_type and device.get("id") and not device.get("is_restricted"):
                        target_device_id = device["id"]
                        target_device_name = device.get("name", "Unknown Device")
                        logging.info(f"SpotifyAPI: Found preferred device type '{dev_type}': {target_device_name} (ID: {target_device_id}).")
                        break
                if target_device_id:
                    break
            
            if not target_device_id:
                for device in all_devices:
                    if device.get("id") and not device.get("is_restricted"):
                        target_device_id = device["id"]
                        target_device_name = device.get("name", "Unknown Device")
                        logging.info(f"SpotifyAPI: No preferred type found. Using first available non-restricted device: {target_device_name} (ID: {target_device_id}).")
                        break
            
            if not target_device_id or not target_device_name:
                logging.warning("SpotifyAPI: No suitable (non-restricted) device found to target for volume control.")
                return None

            # If the chosen device is not the current one, transfer playback
            if target_device_id != active_device_id_from_playback:
                logging.info(f"SpotifyAPI: Target device {target_device_name} (ID: {target_device_id}) is not the current one. Attempting to transfer playback.")
                try:
                    self._sp.transfer_playback(device_id=target_device_id, force_play=False) # type: ignore
                    logging.info(f"SpotifyAPI: Playback successfully transferred to {target_device_name} (ID: {target_device_id}).")
                except SpotifyException as e_transfer:
                    logging.error(f"SpotifyAPI: Failed to transfer playback to {target_device_name} (ID: {target_device_id}): {e_transfer}. HTTP: {e_transfer.http_status}, Code: {e_transfer.code}, Reason: {e_transfer.reason}")
                    return None # Transfer failed, cannot proceed
            else:
                logging.info(f"SpotifyAPI: Target device {target_device_name} (ID: {target_device_id}) is already the current device.")

            return target_device_id

        except SpotifyException as e:
            logging.error(f"SpotifyAPI: SpotifyException while getting/activating device for volume control: {e}. HTTP: {e.http_status}, Code: {e.code}, Reason: {e.reason}")
            return None
        except Exception as e:
            logging.error(f"SpotifyAPI: Unexpected error while getting/activating device for volume control: {e}", exc_info=True)
            return None

    @override
    def set_volume(self, app_name: str, volume_percent: int) -> bool:
        logging.debug(f"SpotifyAPI: set_volume called for app '{app_name}' with volume {volume_percent}%.")
        if not self.is_available(app_name): # is_available checks self._sp
            logging.warning(f"SpotifyAPI: Service not available for app '{app_name}'. Cannot set volume.")
            return False
        assert self._sp is not None

        clamped_volume = max(0, min(100, volume_percent))
        logging.debug(f"SpotifyAPI: Volume clamped to {clamped_volume}%.")

        try:
            target_device_id = self._get_spotify_device_id_for_volume_control()

            if not target_device_id:
                logging.warning("SpotifyAPI: No target device ID obtained for volume control. Cannot set volume.")
                return False

            logging.info(f"SpotifyAPI: Attempting to set volume to {clamped_volume}% on device ID: {target_device_id}.")
            self._sp.volume(volume_percent=clamped_volume, device_id=target_device_id) # type: ignore
            logging.info(f"SpotifyAPI: Volume successfully set to {clamped_volume}% on device ID: {target_device_id}.")
            return True

        except SpotifyException as e:
            logging.error(f"SpotifyAPI: SpotifyException setting volume: {e}. HTTP: {e.http_status}, Code: {e.code}, Reason: {e.reason}")
            if "authentication credentials" in str(e).lower() or "token expired" in str(e).lower():
                logging.error("SpotifyAPI: Token may be invalid or expired. Please check credentials/token.")
            return False
        except Exception as e:
            logging.error(f"SpotifyAPI: Unexpected error setting volume: {e}", exc_info=True)
            return False

    @override
    def toggle_play_pause(self, app_name: str) -> bool:
        if not self.is_available(app_name):
            return False
        assert self._sp is not None

        try:
            playback = self._sp.current_playback()
            if playback and playback.get('is_playing'):
                _ = self._sp.pause_playback()
                logging.debug("SpotifyAPI: Paused playback.")
            else:
                # If no playback info or not playing, attempt to start/resume playback.
                # This also handles the case where playback is paused on an active device.
                _ = self._sp.start_playback()
                logging.debug("SpotifyAPI: Started/Resumed playback.")
            return True
        except SpotifyException as e:
            # Handle common issues like no active device
            if e.http_status == 404 and "No active device found" in str(e):
                 logging.warning("SpotifyAPI: No active device for play/pause. User might need to start playback manually on a device.")
            elif "authentication credentials" in str(e).lower() or "token expired" in str(e).lower():
                logging.error("SpotifyAPI: Token may be invalid or expired. Please update SPOTIFY_TOKEN.")
            else:
                logging.error(f"SpotifyAPI: SpotifyException toggling play/pause: {e}")
            return False
        except Exception as e:
            logging.error(f"SpotifyAPI: Unexpected error toggling play/pause: {e}")
            return False
