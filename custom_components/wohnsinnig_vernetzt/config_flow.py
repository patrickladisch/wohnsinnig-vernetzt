"""Config Flow für Wohnsinnig vernetzt."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_LOGO_URL,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_SERVICES,
    CONF_RSS_URL,
    CONF_SCAN_INTERVAL,
    CONF_SPOTIFY_SHOW_URL,
    DEFAULT_LOGO_URL,
    DEFAULT_NOTIFY_SERVICES,
    DEFAULT_RSS_URL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SPOTIFY_SHOW_URL,
    DOMAIN,
)
from .coordinator import normalize_notify_services


def _get_notify_options(hass: HomeAssistant, current: list[str]) -> list[str]:
    """Sammelt alle verfügbaren Benachrichtigungsdienste aus Home Assistant."""
    options = ["persistent_notification.create"]
    notify_domain = hass.services.async_services().get("notify", {})
    for service_name in sorted(notify_domain.keys()):
        if service_name == "send_message":
            continue
        full = f"notify.{service_name}"
        if full not in options:
            options.append(full)
    for item in current:
        if item not in options:
            options.append(item)
    return options


def _build_schema(hass: HomeAssistant, defaults: dict) -> vol.Schema:
    raw_notify = defaults.get(
        CONF_NOTIFY_SERVICES,
        defaults.get(CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICES),
    )
    current_notify = normalize_notify_services(raw_notify)
    notify_options = _get_notify_options(hass, current_notify)

    return vol.Schema(
        {
            vol.Required(
                CONF_RSS_URL, default=defaults.get(CONF_RSS_URL, DEFAULT_RSS_URL)
            ): str,
            vol.Optional(
                CONF_NOTIFY_SERVICES,
                default=current_notify,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=notify_options,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=1440)),
            vol.Optional(
                CONF_SPOTIFY_SHOW_URL,
                default=defaults.get(
                    CONF_SPOTIFY_SHOW_URL, DEFAULT_SPOTIFY_SHOW_URL
                ),
            ): str,
            vol.Optional(
                CONF_LOGO_URL,
                default=defaults.get(CONF_LOGO_URL) or DEFAULT_LOGO_URL,
            ): str,
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
            data_schema=_build_schema(self.hass, {}),
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
            data_schema=_build_schema(self.hass, current),
        )
