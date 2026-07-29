"""Binary sensor entities for SUNTEK fridges."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SuntekConfigEntry
from .entity import SuntekFridgeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuntekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the fridge power sensor."""
    async_add_entities([SuntekFridgePowerSensor(entry.runtime_data)])


class SuntekFridgePowerSensor(SuntekFridgeEntity, BinarySensorEntity):
    """Whether the fridge is powered on.

    Read-only for now: the command characteristic format is not yet mapped, so this
    is a binary_sensor rather than a switch. See PROTOCOL.md.
    """

    _attr_translation_key = "power"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, device) -> None:
        super().__init__(device, "power")

    @property
    def is_on(self) -> bool | None:
        if (status := self._device.status) is None:
            return None
        return status.powered
