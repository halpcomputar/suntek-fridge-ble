"""Select entities for SUNTEK fridges."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SuntekConfigEntry
from .entity import SuntekFridgeEntity
from .protocol import set_battery_protection, set_display_unit

UNIT_CELSIUS = "celsius"
UNIT_FAHRENHEIT = "fahrenheit"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuntekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the configuration selects."""
    device = entry.runtime_data
    async_add_entities(
        [SuntekBatteryProtectionSelect(device), SuntekDisplayUnitSelect(device)]
    )


class SuntekBatteryProtectionSelect(SuntekFridgeEntity, SelectEntity):
    """Low-voltage cut-off band.

    Per the vendor app: Low 9.6-10.9 V, Medium 10.1-11.4 V, High 11.1-12.4 V.
    Higher settings cut the compressor sooner, reserving more starting power for
    the vehicle it is plugged into.
    """

    _attr_translation_key = "battery_protection"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = ["low", "medium", "high"]

    def __init__(self, device) -> None:
        super().__init__(device, "battery_protection")

    @property
    def current_option(self) -> str | None:
        return self._device.status.battery_protection if self._device.status else None

    async def async_select_option(self, option: str) -> None:
        await self._device.async_send_command(set_battery_protection(option))


class SuntekDisplayUnitSelect(SuntekFridgeEntity, SelectEntity):
    """Unit shown on the fridge's own front panel.

    This does not change how Home Assistant displays anything — temperatures are
    normalised on the way in, so HA always renders them in the user's own
    preference. It only affects the appliance's display, and by extension the unit
    the protocol itself speaks.
    """

    _attr_translation_key = "display_unit"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = [UNIT_CELSIUS, UNIT_FAHRENHEIT]

    def __init__(self, device) -> None:
        super().__init__(device, "display_unit")

    @property
    def current_option(self) -> str | None:
        if (status := self._device.status) is None:
            return None
        return UNIT_FAHRENHEIT if status.displays_fahrenheit else UNIT_CELSIUS

    async def async_select_option(self, option: str) -> None:
        await self._device.async_send_command(
            set_display_unit(fahrenheit=option == UNIT_FAHRENHEIT)
        )
