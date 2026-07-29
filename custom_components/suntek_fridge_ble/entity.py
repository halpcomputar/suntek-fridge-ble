"""Base entity for SUNTEK fridges."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, MODEL
from .device import SuntekFridgeDevice


class SuntekFridgeEntity(Entity):
    """Common wiring: device info, availability, and push updates."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: SuntekFridgeDevice, key: str) -> None:
        self._device = device
        self._attr_unique_id = f"{device.address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.address)},
            connections={(CONNECTION_BLUETOOTH, device.address)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name="Fridge",
            sw_version=device.status.firmware if device.status else None,
        )

    @property
    def available(self) -> bool:
        return self._device.available

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._device.register_callback(self.async_write_ha_state))
