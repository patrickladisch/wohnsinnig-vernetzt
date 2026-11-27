"""Config Flow für Wohnsinnig vernetzt."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    BATTERY_PUSH_MODE_LABELS,
    CONF_ALERTS_URL,
    CONF_BATTERY_PUSH_ENABLED,
    CONF_BATTERY_PUSH_MODE,
    CONF_BATTERY_PUSH_TIME,
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_BATTERY_THRESHOLD,
    CONF_BLUEPRINTS_URL,
    CONF_LOGO_URL,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_SERVICES,
    CONF_RSS_URL,
    CONF_SCAN_INTERVAL,
    CONF_SILENT_HOURS,
    CONF_SPOTIFY_SHOW_URL,
    DEFAULT_ALERTS_URL,
    DEFAULT_BATTERY_PUSH_ENABLED,
    DEFAULT_BATTERY_PUSH_MODE,
    DEFAULT_BATTERY_PUSH_TIME,
    DEFAULT_BATTERY_THRESHOLD,
    DEFAULT_BLUEPRINTS_URL,
    DEFAULT_LOGO_URL,
    DEFAULT_NOTIFY_SERVICES,
    DEFAULT_RSS_URL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SILENT_HOURS,
    DEFAULT_SPOTIFY_SHOW_URL,
    DOMAIN,
    NOTIFY_NONE,
)
from .battery_check import (
    _resolve_excluded_display_name,
    get_all_battery_devices,
    normalize_battery_exclusions,
    resolve_exclusion_key,
)
from .coordinator import normalize_notify_services, parse_hhmm_time
from .notify_helpers import get_mobile_app_services, get_notify_choices


def _build_schema(
    hass: HomeAssistant, defaults: dict, is_initial: bool = False
) -> vol.Schema:
    raw_notify = defaults.get(
        CONF_NOTIFY_SERVICES,
        defaults.get(CONF_NOTIFY_SERVICE),
    )
    if raw_notify is None:
        if is_initial:
            mobile_apps = get_mobile_app_services(hass)
            current_notify = (
                [mobile_apps[0]] if mobile_apps else list(DEFAULT_NOTIFY_SERVICES)
            )
        else:
            current_notify = list(DEFAULT_NOTIFY_SERVICES)
    else:
        current_notify = normalize_notify_services(raw_notify)

    choices = [
        selector.SelectOptionDict(value=svc_id, label=label)
        for svc_id, label in get_notify_choices(hass, current_notify)
        if svc_id != NOTIFY_NONE
    ]

    mode_choices = [
        selector.SelectOptionDict(value=mode_key, label=label)
        for mode_key, label in BATTERY_PUSH_MODE_LABELS.items()
    ]

    current_excluded = normalize_battery_exclusions(
        defaults.get(CONF_BATTERY_EXCLUDED_DEVICES)
    )
    battery_device_choices: list[selector.SelectOptionDict] = []
    seen_excl_values: set[str] = set()
    for dev in get_all_battery_devices(hass):
        key = dev["dedup_key"]
        if key in seen_excl_values:
            continue
        seen_excl_values.add(key)
        lvl = f" ({dev['level_formatted']})" if dev.get("level") is not None else ""
        battery_device_choices.append(
            selector.SelectOptionDict(value=key, label=f"{dev['name']}{lvl}")
        )
    for key in current_excluded:
        if key not in seen_excl_values:
            seen_excl_values.add(key)
            battery_device_choices.append(
                selector.SelectOptionDict(
                    value=key,
                    label=_resolve_excluded_display_name(hass, key),
                )
            )

    default_push_time = parse_hhmm_time(
        defaults.get(CONF_BATTERY_PUSH_TIME, DEFAULT_BATTERY_PUSH_TIME)
    ).strftime("%H:%M:%S")

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
                    options=choices,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_BATTERY_THRESHOLD,
                default=int(
                    defaults.get(CONF_BATTERY_THRESHOLD, DEFAULT_BATTERY_THRESHOLD)
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=50)),
            vol.Optional(
                CONF_BATTERY_EXCLUDED_DEVICES,
                default=current_excluded,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=battery_device_choices,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_BATTERY_PUSH_ENABLED,
                default=bool(
                    defaults.get(
                        CONF_BATTERY_PUSH_ENABLED, DEFAULT_BATTERY_PUSH_ENABLED
                    )
                ),
            ): bool,
            vol.Required(
                CONF_BATTERY_PUSH_MODE,
                default=str(
                    defaults.get(CONF_BATTERY_PUSH_MODE, DEFAULT_BATTERY_PUSH_MODE)
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=mode_choices,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_BATTERY_PUSH_TIME,
                default=default_push_time,
            ): selector.TimeSelector(),
            vol.Required(
                CONF_SILENT_HOURS,
                default=int(defaults.get(CONF_SILENT_HOURS, DEFAULT_SILENT_HOURS)),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
            vol.Optional(
                CONF_BLUEPRINTS_URL,
                default=defaults.get(CONF_BLUEPRINTS_URL) or DEFAULT_BLUEPRINTS_URL,
            ): str,
            vol.Optional(
                CONF_ALERTS_URL,
                default=defaults.get(CONF_ALERTS_URL) or DEFAULT_ALERTS_URL,
            ): str,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=int(defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
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
            cleaned = dict(user_input)
            cleaned[CONF_BATTERY_PUSH_TIME] = parse_hhmm_time(
                cleaned.get(CONF_BATTERY_PUSH_TIME)
            ).strftime("%H:%M")
            cleaned[CONF_BATTERY_EXCLUDED_DEVICES] = normalize_battery_exclusions(
                [
                    resolve_exclusion_key(self.hass, item)
                    for item in normalize_battery_exclusions(
                        cleaned.get(CONF_BATTERY_EXCLUDED_DEVICES)
                    )
                ]
            )
            return self.async_create_entry(
                title="Wohnsinnig vernetzt",
                data=cleaned,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(self.hass, {}, is_initial=True),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WohnsinnigVernetztOptionsFlow()


class WohnsinnigVernetztOptionsFlow(config_entries.OptionsFlow):
    """Optionen nachträglich anpassen."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            cleaned = dict(user_input)
            cleaned[CONF_BATTERY_PUSH_TIME] = parse_hhmm_time(
                cleaned.get(CONF_BATTERY_PUSH_TIME)
            ).strftime("%H:%M")
            cleaned[CONF_BATTERY_EXCLUDED_DEVICES] = normalize_battery_exclusions(
                [
                    resolve_exclusion_key(self.hass, item)
                    for item in normalize_battery_exclusions(
                        cleaned.get(CONF_BATTERY_EXCLUDED_DEVICES)
                    )
                ]
            )
            return self.async_create_entry(title="", data=cleaned)

        current = {**self.config_entry.data, **self.config_entry.options}
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        if coordinator is not None:
            current[CONF_NOTIFY_SERVICES] = list(coordinator.notify_services)
            current[CONF_BATTERY_THRESHOLD] = coordinator.battery_threshold
            current[CONF_BATTERY_EXCLUDED_DEVICES] = list(
                coordinator.battery_excluded_devices
            )
            current[CONF_SILENT_HOURS] = coordinator.silent_hours
            current[CONF_BATTERY_PUSH_ENABLED] = coordinator.battery_push_enabled
            current[CONF_BATTERY_PUSH_MODE] = coordinator.battery_push_mode
            current[CONF_BATTERY_PUSH_TIME] = coordinator.battery_push_time

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(self.hass, current, is_initial=False),
        )
