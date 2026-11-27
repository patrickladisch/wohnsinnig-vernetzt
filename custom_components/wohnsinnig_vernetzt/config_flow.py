"""Config Flow & übersichtliches Options-Menü für Wohnsinnig vernetzt."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .battery_check import (
    _resolve_excluded_display_name,
    get_all_battery_devices,
    normalize_battery_exclusions,
    resolve_exclusion_key,
)
from .const import (
    BATTERY_PUSH_MODE_LABELS,
    CONF_ALERTS_URL,
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_BATTERY_PUSH_ENABLED,
    CONF_BATTERY_PUSH_MODE,
    CONF_BATTERY_PUSH_TIME,
    CONF_BATTERY_THRESHOLD,
    CONF_BLUEPRINTS_URL,
    CONF_LOGO_URL,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_SERVICES,
    CONF_PRESENCE_AUTO_PAUSE_MOTION,
    CONF_PRESENCE_ENTITIES,
    CONF_PRESENCE_JITTER_MINUTES,
    CONF_PRESENCE_PAUSE_AUTOMATIONS,
    CONF_RSS_URL,
    CONF_SCAN_INTERVAL,
    CONF_SILENT_HOURS,
    CONF_SPOTIFY_SHOW_URL,
    CONF_WAKEUP_ALARM_ENTITY,
    CONF_WAKEUP_AUTO_PAUSE,
    CONF_WAKEUP_DAYS,
    CONF_WAKEUP_AUTO_OFF_MINUTES,
    CONF_WAKEUP_DURATION,
    CONF_WAKEUP_ENTITIES,
    CONF_WAKEUP_MODE,
    CONF_WAKEUP_PAUSE_AUTOMATIONS,
    CONF_WAKEUP_SUNRISE_COLOR,
    CONF_WAKEUP_TIME,
    DEFAULT_ALERTS_URL,
    DEFAULT_BATTERY_PUSH_ENABLED,
    DEFAULT_BATTERY_PUSH_MODE,
    DEFAULT_BATTERY_PUSH_TIME,
    DEFAULT_BATTERY_THRESHOLD,
    DEFAULT_BLUEPRINTS_URL,
    DEFAULT_LOGO_URL,
    DEFAULT_NOTIFY_SERVICES,
    DEFAULT_PRESENCE_AUTO_PAUSE_MOTION,
    DEFAULT_PRESENCE_JITTER_MINUTES,
    DEFAULT_RSS_URL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SILENT_HOURS,
    DEFAULT_SPOTIFY_SHOW_URL,
    DEFAULT_WAKEUP_ALARM_ENTITY,
    DEFAULT_WAKEUP_AUTO_PAUSE,
    DEFAULT_WAKEUP_DAYS,
    DEFAULT_WAKEUP_AUTO_OFF_MINUTES,
    DEFAULT_WAKEUP_DURATION,
    DEFAULT_WAKEUP_MODE,
    DEFAULT_WAKEUP_SUNRISE_COLOR,
    DEFAULT_WAKEUP_TIME,
    WAKEUP_ALARM_MANUAL,
    WAKEUP_DAYS_LABELS,
    WAKEUP_MODE_LABELS,
    DOMAIN,
    NOTIFY_NONE,
)
from .coordinator import normalize_notify_services, parse_hhmm_time
from .notify_helpers import get_mobile_app_services, get_notify_choices
from .presence_simulation import (
    normalize_automation_entities,
    normalize_presence_entities,
)
from .wakeup_light import (
    get_alarm_sensor_candidates,
    normalize_wakeup_alarm_entity,
    normalize_wakeup_automations,
    normalize_wakeup_lights,
    parse_wakeup_time,
)


def _build_podcast_schema(
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


def _build_monitoring_schema(hass: HomeAssistant, defaults: dict) -> vol.Schema:
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
        }
    )


def _build_presence_schema(defaults: dict) -> vol.Schema:
    current_entities = normalize_presence_entities(defaults.get(CONF_PRESENCE_ENTITIES))
    current_autos = normalize_automation_entities(
        defaults.get(CONF_PRESENCE_PAUSE_AUTOMATIONS)
    )
    return vol.Schema(
        {
            vol.Optional(
                CONF_PRESENCE_ENTITIES,
                default=current_entities,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["light", "switch"],
                    multiple=True,
                )
            ),
            vol.Required(
                CONF_PRESENCE_JITTER_MINUTES,
                default=int(
                    defaults.get(
                        CONF_PRESENCE_JITTER_MINUTES, DEFAULT_PRESENCE_JITTER_MINUTES
                    )
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=30)),
            vol.Required(
                CONF_PRESENCE_AUTO_PAUSE_MOTION,
                default=bool(
                    defaults.get(
                        CONF_PRESENCE_AUTO_PAUSE_MOTION,
                        DEFAULT_PRESENCE_AUTO_PAUSE_MOTION,
                    )
                ),
            ): bool,
            vol.Optional(
                CONF_PRESENCE_PAUSE_AUTOMATIONS,
                default=current_autos,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["automation"],
                    multiple=True,
                )
            ),
        }
    )


def _build_wakeup_schema(hass: HomeAssistant, defaults: dict) -> vol.Schema:
    current_lights = normalize_wakeup_lights(defaults.get(CONF_WAKEUP_ENTITIES))
    current_alarm = normalize_wakeup_alarm_entity(
        defaults.get(CONF_WAKEUP_ALARM_ENTITY, DEFAULT_WAKEUP_ALARM_ENTITY)
    )
    current_autos = normalize_wakeup_automations(
        defaults.get(CONF_WAKEUP_PAUSE_AUTOMATIONS)
    )
    alarm_choices = [
        selector.SelectOptionDict(
            value=WAKEUP_ALARM_MANUAL,
            label="🕒 Feste Uhrzeit (manuell)",
        )
    ]
    for cand in get_alarm_sensor_candidates(hass, current_alarm):
        alarm_choices.append(
            selector.SelectOptionDict(
                value=cand["entity_id"],
                label=cand["display_label"],
            )
        )
    mode_choices = [
        selector.SelectOptionDict(value=k, label=v)
        for k, v in WAKEUP_MODE_LABELS.items()
    ]
    days_choices = [
        selector.SelectOptionDict(value=k, label=v)
        for k, v in WAKEUP_DAYS_LABELS.items()
    ]
    default_t = parse_wakeup_time(
        defaults.get(CONF_WAKEUP_TIME, DEFAULT_WAKEUP_TIME)
    ).strftime("%H:%M:%S")

    return vol.Schema(
        {
            vol.Optional(
                CONF_WAKEUP_ENTITIES,
                default=current_lights,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["light"],
                    multiple=True,
                )
            ),
            vol.Optional(
                CONF_WAKEUP_ALARM_ENTITY,
                default=current_alarm,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=alarm_choices,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_WAKEUP_MODE,
                default=str(defaults.get(CONF_WAKEUP_MODE, DEFAULT_WAKEUP_MODE)),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=mode_choices,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_WAKEUP_TIME,
                default=default_t,
            ): selector.TimeSelector(),
            vol.Required(
                CONF_WAKEUP_DURATION,
                default=int(
                    defaults.get(CONF_WAKEUP_DURATION, DEFAULT_WAKEUP_DURATION)
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
            vol.Required(
                CONF_WAKEUP_AUTO_OFF_MINUTES,
                default=int(
                    defaults.get(
                        CONF_WAKEUP_AUTO_OFF_MINUTES,
                        DEFAULT_WAKEUP_AUTO_OFF_MINUTES,
                    )
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=180)),
            vol.Required(
                CONF_WAKEUP_DAYS,
                default=str(defaults.get(CONF_WAKEUP_DAYS, DEFAULT_WAKEUP_DAYS)),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=days_choices,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_WAKEUP_AUTO_PAUSE,
                default=bool(
                    defaults.get(CONF_WAKEUP_AUTO_PAUSE, DEFAULT_WAKEUP_AUTO_PAUSE)
                ),
            ): bool,
            vol.Optional(
                CONF_WAKEUP_PAUSE_AUTOMATIONS,
                default=current_autos,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["automation"],
                    multiple=True,
                )
            ),
            vol.Required(
                CONF_WAKEUP_SUNRISE_COLOR,
                default=bool(
                    defaults.get(
                        CONF_WAKEUP_SUNRISE_COLOR, DEFAULT_WAKEUP_SUNRISE_COLOR
                    )
                ),
            ): bool,
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
                data=dict(user_input),
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_podcast_schema(self.hass, {}, is_initial=True),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WohnsinnigVernetztOptionsFlow()


class WohnsinnigVernetztOptionsFlow(config_entries.OptionsFlow):
    """Übersichtliches 3-Bereiche-Menü für alle Einstellungen."""

    def _current_merged(self) -> dict:
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
            current[CONF_PRESENCE_ENTITIES] = list(
                coordinator.presence_manager.entities
            )
            current[CONF_PRESENCE_PAUSE_AUTOMATIONS] = list(
                coordinator.presence_manager.manual_pause_automations
            )
            current[CONF_PRESENCE_AUTO_PAUSE_MOTION] = (
                coordinator.presence_manager.auto_pause_motion
            )
            current[CONF_PRESENCE_JITTER_MINUTES] = (
                coordinator.presence_manager.jitter_minutes
            )
            wm = coordinator.wakeup_manager
            current[CONF_WAKEUP_ENTITIES] = list(wm.entities)
            current[CONF_WAKEUP_ALARM_ENTITY] = wm.alarm_entity
            current[CONF_WAKEUP_MODE] = wm.mode
            current[CONF_WAKEUP_TIME] = wm.wakeup_time
            current[CONF_WAKEUP_DURATION] = wm.duration_minutes
            current[CONF_WAKEUP_AUTO_OFF_MINUTES] = wm.auto_off_minutes
            current[CONF_WAKEUP_DAYS] = wm.weekdays
            current[CONF_WAKEUP_AUTO_PAUSE] = wm.auto_pause
            current[CONF_WAKEUP_PAUSE_AUTOMATIONS] = list(wm.manual_pause_automations)
            current[CONF_WAKEUP_SUNRISE_COLOR] = wm.sunrise_color
        return current

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["wakeup", "presence", "monitoring", "podcast"],
        )

    async def async_step_wakeup(self, user_input=None):
        current = self._current_merged()
        if user_input is not None:
            merged = {**current, **user_input}
            merged[CONF_WAKEUP_ENTITIES] = normalize_wakeup_lights(
                merged.get(CONF_WAKEUP_ENTITIES)
            )
            merged[CONF_WAKEUP_ALARM_ENTITY] = normalize_wakeup_alarm_entity(
                merged.get(CONF_WAKEUP_ALARM_ENTITY)
            )
            merged[CONF_WAKEUP_PAUSE_AUTOMATIONS] = normalize_wakeup_automations(
                merged.get(CONF_WAKEUP_PAUSE_AUTOMATIONS)
            )
            merged[CONF_WAKEUP_TIME] = parse_wakeup_time(
                merged.get(CONF_WAKEUP_TIME)
            ).strftime("%H:%M")
            return self.async_create_entry(title="", data=merged)

        return self.async_show_form(
            step_id="wakeup",
            data_schema=_build_wakeup_schema(self.hass, current),
        )

    async def async_step_presence(self, user_input=None):
        current = self._current_merged()
        if user_input is not None:
            merged = {**current, **user_input}
            merged[CONF_PRESENCE_ENTITIES] = normalize_presence_entities(
                merged.get(CONF_PRESENCE_ENTITIES)
            )
            merged[CONF_PRESENCE_PAUSE_AUTOMATIONS] = normalize_automation_entities(
                merged.get(CONF_PRESENCE_PAUSE_AUTOMATIONS)
            )
            return self.async_create_entry(title="", data=merged)

        return self.async_show_form(
            step_id="presence",
            data_schema=_build_presence_schema(current),
        )

    async def async_step_monitoring(self, user_input=None):
        current = self._current_merged()
        if user_input is not None:
            merged = {**current, **user_input}
            merged[CONF_BATTERY_PUSH_TIME] = parse_hhmm_time(
                merged.get(CONF_BATTERY_PUSH_TIME)
            ).strftime("%H:%M")
            merged[CONF_BATTERY_EXCLUDED_DEVICES] = normalize_battery_exclusions(
                [
                    resolve_exclusion_key(self.hass, item)
                    for item in normalize_battery_exclusions(
                        merged.get(CONF_BATTERY_EXCLUDED_DEVICES)
                    )
                ]
            )
            return self.async_create_entry(title="", data=merged)

        return self.async_show_form(
            step_id="monitoring",
            data_schema=_build_monitoring_schema(self.hass, current),
        )

    async def async_step_podcast(self, user_input=None):
        current = self._current_merged()
        if user_input is not None:
            merged = {**current, **user_input}
            return self.async_create_entry(title="", data=merged)

        return self.async_show_form(
            step_id="podcast",
            data_schema=_build_podcast_schema(self.hass, current, is_initial=False),
        )
