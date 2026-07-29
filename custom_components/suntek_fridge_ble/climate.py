"""Climate entities for SUNTEK fridges — one per cooling zone."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SuntekConfigEntry
from .entity import SuntekFridgeEntity
from .protocol import (
    MAX_SETPOINT_C,
    MIN_SETPOINT_C,
    set_power,
    set_run_mode,
    set_setpoint,
)

PRESET_ECO = "eco"
PRESET_MAX = "max"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuntekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a climate entity per zone."""
    device = entry.runtime_data
    async_add_entities([SuntekFridgeZone(device, 1), SuntekFridgeZone(device, 2)])


class SuntekFridgeZone(SuntekFridgeEntity, ClimateEntity):
    """One cooling zone.

    Note that power and Eco/Max are properties of the *appliance*, not the zone —
    the protocol has no per-zone equivalent. Both zone entities therefore report
    and control the same HVAC mode and preset; changing either changes both. Only
    the target temperature is genuinely per-zone.
    """

    _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL]
    _attr_preset_modes = [PRESET_ECO, PRESET_MAX]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_target_temperature_step = 1

    def __init__(self, device, zone: int) -> None:
        super().__init__(device, f"zone{zone}")
        self._zone = zone
        self._attr_translation_key = f"zone{zone}"

    # -- unit handling -------------------------------------------------------
    #
    # The fridge reports and accepts whole degrees in whatever unit its panel is
    # displaying. Reporting that unit here means Home Assistant hands us values
    # already in it, so setpoints land on the same integers the vendor app uses
    # and nothing is lost to double conversion.

    @property
    def temperature_unit(self) -> str:
        status = self._device.status
        if status is not None and not status.displays_fahrenheit:
            return UnitOfTemperature.CELSIUS
        return UnitOfTemperature.FAHRENHEIT

    def _in_device_unit(self, celsius: int) -> int:
        status = self._device.status
        if status is not None and not status.displays_fahrenheit:
            return celsius
        return round(celsius * 9 / 5 + 32)

    @property
    def min_temp(self) -> float:
        return self._in_device_unit(MIN_SETPOINT_C)

    @property
    def max_temp(self) -> float:
        return self._in_device_unit(MAX_SETPOINT_C)

    # -- state ---------------------------------------------------------------

    @property
    def current_temperature(self) -> float | None:
        if (status := self._device.status) is None:
            return None
        return status.zone1_temp_raw if self._zone == 1 else status.zone2_temp_raw

    @property
    def target_temperature(self) -> float | None:
        if (status := self._device.status) is None:
            return None
        return status.zone1_setpoint_raw if self._zone == 1 else status.zone2_setpoint_raw

    @property
    def hvac_mode(self) -> HVACMode | None:
        if (status := self._device.status) is None:
            return None
        return HVACMode.COOL if status.powered else HVACMode.OFF

    @property
    def preset_mode(self) -> str | None:
        return self._device.status.run_mode if self._device.status else None

    # -- control -------------------------------------------------------------

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (target := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self._device.async_send_command(set_setpoint(self._zone, round(target)))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self._device.async_send_command(set_power(hvac_mode is HVACMode.COOL))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self._attr_preset_modes:
            raise HomeAssistantError(f"Unsupported preset {preset_mode!r}")
        await self._device.async_send_command(set_run_mode(preset_mode))
