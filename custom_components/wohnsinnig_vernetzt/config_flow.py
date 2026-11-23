"""Config Flow für Wohnsinnig vernetzt."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_NOTIFY_SERVICE,
    CONF_RSS_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_NOTIFY_SERVICE,
    DEFAULT_RSS_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


def _build_schema(defaults: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_RSS_URL, default=defaults.get(CONF_RSS_URL, DEFAULT_RSS_URL)
            ): str,
            vol.Optional(
                CONF_NOTIFY_SERVICE,
                default=defaults.get(CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICE),
            ): str,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=1440)),
        }
    )


class WohnsinnigVernetztConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Einrichtungsassistent für Wohnsinnig vernetzt."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(
                title="Wohnsinnig vernetzt",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema({}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WohnsinnigVernetztOptionsFlow()


class WohnsinnigVernetztOptionsFlow(config_entries.OptionsFlow):
    """Optionen nachträglich anpassen."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(current),
        )
