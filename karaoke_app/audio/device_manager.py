"""
Audio Device Manager
Handles enumeration and selection of audio input/output devices.
"""
import logging
from typing import List, Dict, Optional

import sounddevice as sd


logger = logging.getLogger(__name__)


class AudioDeviceManager:
    """Manages audio device enumeration and selection."""

    @staticmethod
    def get_all_devices() -> List[Dict]:
        """
        Get all available audio devices.

        Returns:
            List of device info dicts with id, name, input/output channels
        """
        devices = sd.query_devices()
        result = []
        
        for i, device in enumerate(devices):
            result.append({
                "id": i,
                "name": device["name"],
                "max_input_channels": device["max_input_channels"],
                "max_output_channels": device["max_output_channels"],
                "default_samplerate": device["default_samplerate"],
                "hostapi": device["hostapi"]
            })
        
        return result

    @staticmethod
    def get_input_devices() -> List[Dict]:
        """
        Get all available input (microphone) devices.

        Returns:
            List of input device info dicts
        """
        all_devices = AudioDeviceManager.get_all_devices()
        return [d for d in all_devices if d["max_input_channels"] > 0]

    @staticmethod
    def get_output_devices() -> List[Dict]:
        """
        Get all available output (speaker) devices.

        Returns:
            List of output device info dicts
        """
        all_devices = AudioDeviceManager.get_all_devices()
        return [d for d in all_devices if d["max_output_channels"] > 0]

    @staticmethod
    def get_default_input_device() -> Optional[Dict]:
        """
        Get the default input device.

        Returns:
            Default input device info or None
        """
        try:
            default_id = sd.default.device[0]
            if default_id is not None:
                devices = AudioDeviceManager.get_all_devices()
                if 0 <= default_id < len(devices):
                    return devices[default_id]
        except Exception as e:
            logger.warning(f"Could not get default input device: {e}")
        return None

    @staticmethod
    def get_default_output_device() -> Optional[Dict]:
        """
        Get the default output device.

        Returns:
            Default output device info or None
        """
        try:
            default_id = sd.default.device[1]
            if default_id is not None:
                devices = AudioDeviceManager.get_all_devices()
                if 0 <= default_id < len(devices):
                    return devices[default_id]
        except Exception as e:
            logger.warning(f"Could not get default output device: {e}")
        return None

    @staticmethod
    def get_device_by_name(name: str) -> Optional[Dict]:
        """
        Get a device by name.

        Args:
            name: Device name to search for

        Returns:
            Device info or None if not found
        """
        devices = AudioDeviceManager.get_all_devices()
        for device in devices:
            if device["name"] == name:
                return device
        return None

    @staticmethod
    def set_default_input_device(device_id: int):
        """
        Set the default input device.

        Args:
            device_id: Device ID to set as default input
        """
        sd.default.device[0] = device_id
        logger.info(f"Default input device set to ID: {device_id}")

    @staticmethod
    def set_default_output_device(device_id: int):
        """
        Set the default output device.

        Args:
            device_id: Device ID to set as default output
        """
        sd.default.device[1] = device_id
        logger.info(f"Default output device set to ID: {device_id}")
