"""Constants for the SUNTEK fridge BLE integration."""

from __future__ import annotations

DOMAIN = "suntek_fridge_ble"

MANUFACTURER = "SUNTEK"
MODEL = "SC-BLE-1.0"

SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_STATUS = "0000fff4-0000-1000-8000-00805f9b34fb"  # read / notify
CHAR_COMMAND = "0000fff1-0000-1000-8000-00805f9b34fb"  # write; format not yet mapped
