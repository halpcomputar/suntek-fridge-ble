"""Config flow for the SUNTEK fridge BLE integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN, SERVICE_UUID


def _is_supported(info: BluetoothServiceInfoBleak) -> bool:
    """Match the fridge without claiming every FFF0 device in the house.

    FFF0 is a generic transparent-UART service used by countless unrelated gadgets,
    so the advertised name has to agree too. SYZ-D is the module's device number
    rather than a per-unit name, so a prefix match covers sibling models.
    """
    return SERVICE_UUID in info.service_uuids and bool(
        info.name and info.name.upper().startswith("SYZ")
    )


class SuntekFridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SUNTEK fridges."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle automatic discovery over Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        if not _is_supported(discovery_info):
            return self.async_abort(reason="not_supported")

        self._discovered = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered fridge."""
        assert self._discovered is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered.name,
                data={CONF_ADDRESS: self._discovered.address},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._discovered.name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a manually initiated flow."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._discovered_devices[address], data={CONF_ADDRESS: address}
            )

        current = self._async_current_ids()
        self._discovered_devices = {
            info.address: info.name
            for info in async_discovered_service_info(self.hass, connectable=True)
            if info.address not in current and _is_supported(info)
        }
        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._discovered_devices)}
            ),
        )
