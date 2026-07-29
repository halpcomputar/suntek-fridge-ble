"""The SUNTEK fridge BLE integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .device import SuntekFridgeDevice

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type SuntekConfigEntry = ConfigEntry[SuntekFridgeDevice]


async def async_setup_entry(hass: HomeAssistant, entry: SuntekConfigEntry) -> bool:
    """Set up a fridge from a config entry."""
    address: str = entry.data[CONF_ADDRESS]

    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise ConfigEntryNotReady(f"Could not find fridge with address {address}")

    device = SuntekFridgeDevice(
        ble_device,
        lambda: bluetooth.async_ble_device_from_address(hass, address, connectable=True),
    )

    try:
        await device.start()
    except Exception as err:
        await device.stop()
        raise ConfigEntryNotReady(f"Could not connect to fridge at {address}: {err}") from err

    entry.runtime_data = device
    entry.async_on_unload(device.stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SuntekConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
