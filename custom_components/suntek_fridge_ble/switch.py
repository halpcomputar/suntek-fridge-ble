"""Switch entity for SUNTEK fridges."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SuntekConfigEntry
from .entity import SuntekFridgeEntity
from .protocol import set_power


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuntekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the power switch."""
    async_add_entities([SuntekFridgePowerSwitch(entry.runtime_data)])


class SuntekFridgePowerSwitch(SuntekFridgeEntity, SwitchEntity):
    """Appliance power.

    Duplicated by each zone's climate HVAC mode, but kept as a switch because it
    is genuinely appliance-wide and is far easier to use in an automation than a
    climate service call.
    """

    _attr_translation_key = "power"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, device) -> None:
        super().__init__(device, "power")

    @property
    def is_on(self) -> bool | None:
        return self._device.status.powered if self._device.status else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._device.async_send_command(set_power(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.async_send_command(set_power(False))
