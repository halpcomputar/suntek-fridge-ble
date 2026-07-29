"""Sensor entities for SUNTEK fridges."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfElectricPotential, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SuntekConfigEntry
from .entity import SuntekFridgeEntity
from .protocol import FridgeStatus


@dataclass(frozen=True, kw_only=True)
class SuntekSensorDescription(SensorEntityDescription):
    """Describes a fridge sensor."""

    value: Callable[[FridgeStatus], float | str | None]


SENSORS: tuple[SuntekSensorDescription, ...] = (
    SuntekSensorDescription(
        key="zone1_temperature",
        translation_key="zone1_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value=lambda status: status.zone1_temp,
    ),
    SuntekSensorDescription(
        key="zone2_temperature",
        translation_key="zone2_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value=lambda status: status.zone2_temp,
    ),
    SuntekSensorDescription(
        key="zone1_setpoint",
        translation_key="zone1_setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value=lambda status: status.zone1_setpoint,
    ),
    SuntekSensorDescription(
        key="zone2_setpoint",
        translation_key="zone2_setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value=lambda status: status.zone2_setpoint,
    ),
    SuntekSensorDescription(
        key="voltage",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # The fridge reports tenths, and supply sag under compressor load is the most
        # informative signal it emits — without this, 11.8 and 12.3 both render as "12".
        suggested_display_precision=1,
        value=lambda status: status.voltage,
    ),
    SuntekSensorDescription(
        key="run_mode",
        translation_key="run_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["eco", "max"],
        value=lambda status: status.run_mode,
    ),
    SuntekSensorDescription(
        key="battery_protection",
        translation_key="battery_protection",
        device_class=SensorDeviceClass.ENUM,
        options=["low", "medium", "high"],
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda status: status.battery_protection,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SuntekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up fridge sensors."""
    async_add_entities(
        SuntekFridgeSensor(entry.runtime_data, description) for description in SENSORS
    )


class SuntekFridgeSensor(SuntekFridgeEntity, SensorEntity):
    """A single value read from the fridge's status frame."""

    entity_description: SuntekSensorDescription

    def __init__(self, device, description: SuntekSensorDescription) -> None:
        super().__init__(device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | str | None:
        if (status := self._device.status) is None:
            return None
        return self.entity_description.value(status)
