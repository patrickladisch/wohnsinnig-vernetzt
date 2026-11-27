"""Integration für den Podcast Wohnsinnig vernetzt."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web
import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    ACTION_MARK_SEEN,
    ACTION_PLAY_LATEST,
    BROWSER_TARGET,
    CARD_FILENAME,
    CARD_URL_BASE,
    CONF_ALERTS_URL,
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_BATTERY_PUSH_ENABLED,
    CONF_BATTERY_PUSH_MODE,
    CONF_BATTERY_PUSH_TIME,
    CONF_BATTERY_THRESHOLD,
    CONF_BLUEPRINTS_URL,
    CONF_DEFAULT_TARGET,
    CONF_LOGO_URL,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_SERVICES,
    CONF_PRESENCE_AUTO_PAUSE_MOTION,
    CONF_PRESENCE_ENTITIES,
    CONF_PRESENCE_JITTER_MINUTES,
    CONF_PRESENCE_PAUSE_AUTOMATIONS,
    CONF_PRESENCE_SENSORS,
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
    CONF_PV_BATTERY_ENTITY,
    CONF_PV_INVERT_SURPLUS,
    CONF_PV_RULES,
    CONF_PV_SURPLUS_ENTITY,
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
    DEFAULT_PV_BATTERY_ENTITY,
    DEFAULT_PV_INVERT_SURPLUS,
    DEFAULT_PV_SURPLUS_ENTITY,
    DEFAULT_WAKEUP_TIME,
    DEVICE_CONFIG_URL,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
    SERVICE_EXCLUDE_BATTERY_DEVICE,
    SERVICE_IMPORT_BLUEPRINT,
    SERVICE_INCLUDE_BATTERY_DEVICE,
    SERVICE_MARK_EPISODE_SEEN,
    SERVICE_RESET_BATTERY_PUSH_MEMORY,
    SERVICE_RUN_BATTERY_CHECK,
    SERVICE_RUN_SILENT_SENSORS_CHECK,
    SERVICE_START_WAKEUP,
    SERVICE_EVALUATE_PRESENCE_SENSORS,
    SERVICE_EVALUATE_PV,
    SERVICE_RESET_PV_DAILY,
    SERVICE_STOP_WAKEUP,
    VERSION,
)
from .coordinator import WohnsinnigVernetztCoordinator, normalize_notify_services
from .entity import (
    SECTION_DEVICE_SPECS,
    get_section_device_identifier,
)
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
from .pv_surplus import (
    get_pv_sensor_candidates,
    get_pv_target_candidates,
    normalize_pv_rules,
    normalize_sensor_entity,
)
from .presence_sensors import (
    get_presence_sensor_candidates,
    normalize_presence_sensor_defs,
)

PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.TIME,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.UPDATE,
    Platform.IMAGE,
]

IMPORT_BLUEPRINT_SCHEMA = vol.Schema(
    {
        vol.Optional("url"): str,
        vol.Optional("blueprint_id"): str,
        vol.Optional("import_all", default=False): bool,
    }
)

RUN_BATTERY_CHECK_SCHEMA = vol.Schema(
    {
        vol.Optional("notify", default=False): bool,
    }
)

RUN_SILENT_SENSORS_SCHEMA = vol.Schema(
    {
        vol.Optional("notify", default=False): bool,
    }
)

BATTERY_EXCLUSION_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): str,
        vol.Optional("device_id"): str,
        vol.Optional("key"): str,
    }
)

START_WAKEUP_SCHEMA = vol.Schema(
    {
        vol.Optional("duration_minutes"): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
        vol.Optional("auto_off_minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=180)),
    }
)


class WohnsinnigVernetztEpisodesView(HomeAssistantView):
    """Liefert Podcast-Episoden, Blueprints und Status-Infos als JSON an die Karten."""

    url = f"/api/{DOMAIN}/episodes"
    name = f"api:{DOMAIN}:episodes"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: WohnsinnigVernetztCoordinator | None = domain_data.get(
            "coordinator"
        )

        if coordinator is None or coordinator.data is None:
            return self.json(
                {
                    "title": "Wohnsinnig vernetzt",
                    "image": DEFAULT_LOGO_URL,
                    "episodes": [],
                    "blueprints": [],
                    "infographics": [],
                    "alerts": [],
                    "spotify_show_id": "",
                    "spotify_show_url": "",
                    "target_entity": BROWSER_TARGET,
                    "selected_episode_guid": None,
                }
            )

        return self.json(
            {
                **coordinator.data,
                "battery_check": {
                    k: v
                    for k, v in coordinator.battery_check_result.items()
                    if k != "all_battery_levels"
                },
                "silent_sensors": coordinator.silent_sensors_result,
                "presence": coordinator.presence_manager.get_status_snapshot(),
                "wakeup": coordinator.wakeup_manager.get_status_snapshot(),
                "pv": coordinator.pv_manager.get_status_snapshot(),
                "presence_sensors": coordinator.presence_sensors_manager.get_overview_snapshot(),
                "spotify_show_id": coordinator.spotify_show_id,
                "spotify_show_url": coordinator.spotify_show_url,
                "target_entity": coordinator.target_entity,
                "selected_episode_guid": coordinator.selected_episode_guid,
            }
        )


class WohnsinnigVernetztPlayerStateView(HomeAssistantView):
    """Synchronisiert Browser-Player-Status zurück an die HA-Media-Player-Entität."""

    url = f"/api/{DOMAIN}/player_state"
    name = f"api:{DOMAIN}:player_state"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: WohnsinnigVernetztCoordinator | None = domain_data.get(
            "coordinator"
        )
        if coordinator is None:
            return self.json({"error": "Integration nicht geladen."}, status_code=503)

        try:
            payload = await request.json()
        except ValueError:
            return self.json({"error": "Ungültiges JSON."}, status_code=400)

        state = str(payload.get("state", "idle"))
        guid = payload.get("guid")
        await coordinator.async_sync_browser_state(
            state=state, guid=str(guid) if guid else None
        )
        return self.json({"status": "ok"})


class WohnsinnigVernetztImportBlueprintView(HomeAssistantView):
    """Importiert einen oder alle Blueprints direkt in den HA-Blueprints-Ordner."""

    url = f"/api/{DOMAIN}/import_blueprint"
    name = f"api:{DOMAIN}:import_blueprint"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: WohnsinnigVernetztCoordinator | None = domain_data.get(
            "coordinator"
        )
        if coordinator is None:
            return self.json({"error": "Integration nicht geladen."}, status_code=503)

        try:
            payload = await request.json()
        except ValueError:
            payload = {}

        try:
            if payload.get("import_all"):
                imported = await coordinator.async_import_all_blueprints()
                return self.json(
                    {
                        "status": "ok",
                        "imported": imported,
                        "blueprints": coordinator.get_blueprints(),
                    }
                )

            result = await coordinator.async_import_blueprint(
                url=payload.get("url"),
                blueprint_id=payload.get("blueprint_id"),
            )
            return self.json(
                {
                    "status": "ok",
                    "imported": [result],
                    "blueprints": coordinator.get_blueprints(),
                }
            )
        except HomeAssistantError as err:
            return self.json({"error": str(err)}, status_code=400)


class WohnsinnigVernetztBatteryCheckView(HomeAssistantView):
    """Führt beim Klick in der Dashboard-Karte sofort einen Live-Batterie-Check aus."""

    url = f"/api/{DOMAIN}/battery_check"
    name = f"api:{DOMAIN}:battery_check"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: WohnsinnigVernetztCoordinator | None = domain_data.get(
            "coordinator"
        )
        if coordinator is None:
            return self.json({"error": "Integration nicht geladen."}, status_code=503)

        result = await coordinator.async_run_battery_check(notify=False)
        return self.json({k: v for k, v in result.items() if k != "all_battery_levels"})


class WohnsinnigVernetztSilentSensorsView(HomeAssistantView):
    """Führt beim Klick in der Dashboard-Karte sofort einen Live-Stille-Sensoren-Check aus."""

    url = f"/api/{DOMAIN}/silent_sensors"
    name = f"api:{DOMAIN}:silent_sensors"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: WohnsinnigVernetztCoordinator | None = domain_data.get(
            "coordinator"
        )
        if coordinator is None:
            return self.json({"error": "Integration nicht geladen."}, status_code=503)

        result = await coordinator.async_run_silent_sensors_check(notify=False)
        return self.json(result)


class WohnsinnigVernetztBatteryExclusionsView(HomeAssistantView):
    """Schließt Geräte per 1-Klick-Button aus dem Batterie-Check aus oder nimmt sie wieder auf."""

    url = f"/api/{DOMAIN}/battery_exclusions"
    name = f"api:{DOMAIN}:battery_exclusions"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: WohnsinnigVernetztCoordinator | None = domain_data.get(
            "coordinator"
        )
        if coordinator is None:
            return self.json({"error": "Integration nicht geladen."}, status_code=503)

        try:
            payload = await request.json()
        except ValueError:
            return self.json({"error": "Ungültiges JSON."}, status_code=400)

        action = str(payload.get("action", "")).strip().lower()
        key = str(
            payload.get("key")
            or payload.get("entity_id")
            or payload.get("device_id")
            or ""
        ).strip()

        try:
            if action == "exclude":
                result = await coordinator.async_exclude_battery_device(key)
            elif action == "include":
                result = await coordinator.async_include_battery_device(key)
            elif action == "clear":
                result = await coordinator.async_clear_battery_exclusions()
            else:
                return self.json({"error": "Ungültige Aktion."}, status_code=400)
        except HomeAssistantError as err:
            return self.json({"error": str(err)}, status_code=400)

        return self.json(
            {
                "status": "ok",
                "battery_check": {
                    k: v for k, v in result.items() if k != "all_battery_levels"
                },
            }
        )


class WohnsinnigVernetztPresenceConfigView(HomeAssistantView):
    """Liefert und speichert die Anwesenheitssimulation-Konfiguration direkt aus dem Dialog."""

    url = f"/api/{DOMAIN}/presence_config"
    name = f"api:{DOMAIN}:presence_config"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: WohnsinnigVernetztCoordinator | None = domain_data.get(
            "coordinator"
        )
        if coordinator is None:
            return self.json({"error": "Integration nicht geladen."}, status_code=503)

        pm = coordinator.presence_manager
        lights_switches: list[dict] = []
        for st in hass.states.async_all(["light", "switch"]):
            if f".{DOMAIN}" in st.entity_id:
                continue
            attrs = st.attributes or {}
            if attrs.get("restored") is True:
                continue
            lights_switches.append(
                {
                    "entity_id": st.entity_id,
                    "domain": st.entity_id.split(".", 1)[0],
                    "name": str(attrs.get("friendly_name") or st.entity_id).strip(),
                    "state": st.state,
                }
            )
        lights_switches.sort(key=lambda item: (item["name"].lower(), item["entity_id"]))

        automations: list[dict] = []
        for st in hass.states.async_all("automation"):
            attrs = st.attributes or {}
            automations.append(
                {
                    "entity_id": st.entity_id,
                    "name": str(attrs.get("friendly_name") or st.entity_id).strip(),
                    "state": st.state,
                }
            )
        automations.sort(key=lambda item: (item["name"].lower(), item["entity_id"]))

        return self.json(
            {
                "enabled": pm.enabled,
                "presence_entities": list(pm.entities),
                "presence_jitter_minutes": pm.jitter_minutes,
                "presence_auto_pause_motion": pm.auto_pause_motion,
                "presence_pause_automations": list(pm.manual_pause_automations),
                "available_entities": lights_switches,
                "available_automations": automations,
            }
        )

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return self.json({"error": "Kein Config Entry gefunden."}, status_code=404)
        entry = entries[0]

        try:
            payload = await request.json()
        except ValueError:
            return self.json({"error": "Ungültiges JSON."}, status_code=400)

        entities = normalize_presence_entities(payload.get("presence_entities"))
        automations = normalize_automation_entities(
            payload.get("presence_pause_automations")
        )
        try:
            jitter = max(0, min(30, int(payload.get("presence_jitter_minutes", 7))))
        except (TypeError, ValueError):
            jitter = 7
        auto_pause = bool(payload.get("presence_auto_pause_motion", True))

        merged = {**entry.data, **entry.options}
        merged[CONF_PRESENCE_ENTITIES] = entities
        merged[CONF_PRESENCE_PAUSE_AUTOMATIONS] = automations
        merged[CONF_PRESENCE_JITTER_MINUTES] = jitter
        merged[CONF_PRESENCE_AUTO_PAUSE_MOTION] = auto_pause

        hass.config_entries.async_update_entry(entry, options=merged)
        return self.json(
            {
                "status": "ok",
                "presence_entities": entities,
                "presence_jitter_minutes": jitter,
                "presence_auto_pause_motion": auto_pause,
                "presence_pause_automations": automations,
            }
        )


class WohnsinnigVernetztWakeUpConfigView(HomeAssistantView):
    """Liefert und speichert die Wake-Up-Light-Konfiguration direkt aus dem Dialog."""

    url = f"/api/{DOMAIN}/wakeup_config"
    name = f"api:{DOMAIN}:wakeup_config"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: WohnsinnigVernetztCoordinator | None = domain_data.get(
            "coordinator"
        )
        if coordinator is None:
            return self.json({"error": "Integration nicht geladen."}, status_code=503)

        wm = coordinator.wakeup_manager
        lights: list[dict] = []
        for st in hass.states.async_all("light"):
            if f".{DOMAIN}" in st.entity_id:
                continue
            attrs = st.attributes or {}
            if attrs.get("restored") is True:
                continue
            lights.append(
                {
                    "entity_id": st.entity_id,
                    "name": str(attrs.get("friendly_name") or st.entity_id).strip(),
                    "state": st.state,
                }
            )
        lights.sort(key=lambda item: (item["name"].lower(), item["entity_id"]))

        automations: list[dict] = []
        for st in hass.states.async_all("automation"):
            attrs = st.attributes or {}
            automations.append(
                {
                    "entity_id": st.entity_id,
                    "name": str(attrs.get("friendly_name") or st.entity_id).strip(),
                    "state": st.state,
                }
            )
        automations.sort(key=lambda item: (item["name"].lower(), item["entity_id"]))

        alarm_sensors = get_alarm_sensor_candidates(hass, wm.alarm_entity)
        return self.json(
            {
                "enabled": wm.enabled,
                "wakeup_entities": list(wm.entities),
                "wakeup_alarm_entity": wm.alarm_entity,
                "available_alarm_sensors": alarm_sensors,
                "wakeup_mode": wm.mode,
                "wakeup_time": wm.wakeup_time,
                "wakeup_duration": wm.duration_minutes,
                "wakeup_auto_off_minutes": wm.auto_off_minutes,
                "wakeup_days": wm.weekdays,
                "wakeup_auto_pause": wm.auto_pause,
                "wakeup_pause_automations": list(wm.manual_pause_automations),
                "wakeup_sunrise_color": wm.sunrise_color,
                "available_lights": lights,
                "available_automations": automations,
            }
        )

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return self.json({"error": "Kein Config Entry gefunden."}, status_code=404)
        entry = entries[0]

        try:
            payload = await request.json()
        except ValueError:
            return self.json({"error": "Ungültiges JSON."}, status_code=400)

        lights = normalize_wakeup_lights(payload.get("wakeup_entities"))
        alarm_entity = normalize_wakeup_alarm_entity(
            payload.get("wakeup_alarm_entity")
        )
        automations = normalize_wakeup_automations(
            payload.get("wakeup_pause_automations")
        )
        mode = str(payload.get("wakeup_mode") or DEFAULT_WAKEUP_MODE)
        if mode not in ("reach_100", "start_at"):
            mode = DEFAULT_WAKEUP_MODE
        w_time = parse_wakeup_time(payload.get("wakeup_time")).strftime("%H:%M")
        try:
            duration = max(1, min(120, int(payload.get("wakeup_duration", DEFAULT_WAKEUP_DURATION))))
        except (TypeError, ValueError):
            duration = DEFAULT_WAKEUP_DURATION
        try:
            auto_off = max(0, min(180, int(payload.get("wakeup_auto_off_minutes", DEFAULT_WAKEUP_AUTO_OFF_MINUTES))))
        except (TypeError, ValueError):
            auto_off = DEFAULT_WAKEUP_AUTO_OFF_MINUTES
        days = str(payload.get("wakeup_days") or DEFAULT_WAKEUP_DAYS)
        if days not in ("daily", "workdays", "weekend"):
            days = DEFAULT_WAKEUP_DAYS
        auto_pause = bool(payload.get("wakeup_auto_pause", True))
        sunrise_color = bool(payload.get("wakeup_sunrise_color", True))

        merged = {**entry.data, **entry.options}
        merged[CONF_WAKEUP_ENTITIES] = lights
        merged[CONF_WAKEUP_ALARM_ENTITY] = alarm_entity
        merged[CONF_WAKEUP_MODE] = mode
        merged[CONF_WAKEUP_TIME] = w_time
        merged[CONF_WAKEUP_DURATION] = duration
        merged[CONF_WAKEUP_AUTO_OFF_MINUTES] = auto_off
        merged[CONF_WAKEUP_DAYS] = days
        merged[CONF_WAKEUP_AUTO_PAUSE] = auto_pause
        merged[CONF_WAKEUP_PAUSE_AUTOMATIONS] = automations
        merged[CONF_WAKEUP_SUNRISE_COLOR] = sunrise_color

        hass.config_entries.async_update_entry(entry, options=merged)
        return self.json({"status": "ok"})


class WohnsinnigVernetztPvConfigView(HomeAssistantView):
    """Liefert und speichert PV-Sensoren & beliebig viele PV-Überschuss-Aktionen."""

    url = f"/api/{DOMAIN}/pv_config"
    name = f"api:{DOMAIN}:pv_config"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: WohnsinnigVernetztCoordinator | None = domain_data.get(
            "coordinator"
        )
        if coordinator is None:
            return self.json({"error": "Integration nicht geladen."}, status_code=503)

        pm = coordinator.pv_manager
        power_sensors, battery_sensors = get_pv_sensor_candidates(
            hass, pm.surplus_entity, pm.battery_entity
        )
        targets = get_pv_target_candidates(hass)

        return self.json(
            {
                "enabled": pm.enabled,
                "pv_surplus_entity": pm.surplus_entity,
                "pv_battery_entity": pm.battery_entity,
                "pv_invert_surplus": pm.invert_surplus,
                "pv_rules": list(pm.rules),
                "current_surplus_w": pm.get_current_surplus_w(),
                "current_battery_soc": pm.get_current_battery_soc(),
                "available_power_sensors": power_sensors,
                "available_battery_sensors": battery_sensors,
                "available_targets": targets,
            }
        )

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return self.json({"error": "Kein Config Entry gefunden."}, status_code=404)
        entry = entries[0]

        try:
            payload = await request.json()
        except ValueError:
            return self.json({"error": "Ungültiges JSON."}, status_code=400)

        surplus_entity = normalize_sensor_entity(payload.get("pv_surplus_entity"))
        battery_entity = normalize_sensor_entity(payload.get("pv_battery_entity"))
        invert_surplus = bool(payload.get("pv_invert_surplus", False))
        rules = normalize_pv_rules(payload.get("pv_rules") or [])

        merged = {**entry.data, **entry.options}
        merged[CONF_PV_SURPLUS_ENTITY] = surplus_entity
        merged[CONF_PV_BATTERY_ENTITY] = battery_entity
        merged[CONF_PV_INVERT_SURPLUS] = invert_surplus
        merged[CONF_PV_RULES] = rules

        hass.config_entries.async_update_entry(entry, options=merged)
        return self.json({"status": "ok", "rules_count": len(rules)})


class WohnsinnigVernetztPvTriggerView(HomeAssistantView):
    """Löst eine einzelne PV-Aktion manuell aus der Dashboard-Karte zum Testen aus."""

    url = f"/api/{DOMAIN}/pv_trigger"
    name = f"api:{DOMAIN}:pv_trigger"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: WohnsinnigVernetztCoordinator | None = domain_data.get(
            "coordinator"
        )
        if coordinator is None:
            return self.json({"error": "Integration nicht geladen."}, status_code=503)

        try:
            payload = await request.json()
        except ValueError:
            return self.json({"error": "Ungültiges JSON."}, status_code=400)

        rule_id = str(payload.get("rule_id") or "").strip()
        try:
            await coordinator.pv_manager.async_trigger_rule_now(rule_id)
        except HomeAssistantError as err:
            return self.json({"error": str(err)}, status_code=400)
        return self.json({"status": "ok"})


class WohnsinnigVernetztPresenceSensorsConfigView(HomeAssistantView):
    """Liefert und speichert beliebig viele kombinierte Anwesenheitssensoren."""

    url = f"/api/{DOMAIN}/presence_sensors_config"
    name = f"api:{DOMAIN}:presence_sensors_config"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: WohnsinnigVernetztCoordinator | None = domain_data.get(
            "coordinator"
        )
        if coordinator is None:
            return self.json({"error": "Integration nicht geladen."}, status_code=503)

        cands = get_presence_sensor_candidates(hass)
        return self.json(
            {
                "presence_sensors": list(
                    coordinator.presence_sensors_manager.sensor_defs
                ),
                "overview": coordinator.presence_sensors_manager.get_overview_snapshot(),
                **cands,
            }
        )

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return self.json({"error": "Kein Config Entry gefunden."}, status_code=404)
        entry = entries[0]

        try:
            payload = await request.json()
        except ValueError:
            return self.json({"error": "Ungültiges JSON."}, status_code=400)

        sensors = normalize_presence_sensor_defs(payload.get("presence_sensors") or [])
        merged = {**entry.data, **entry.options}
        merged[CONF_PRESENCE_SENSORS] = sensors

        hass.config_entries.async_update_entry(entry, options=merged)
        return self.json({"status": "ok", "sensors_count": len(sensors)})


LEGACY_ENTITY_UNIQUE_ID_SUFFIXES = (
    "_send_feedback",
    "_feedback_message",
    "_systemcheck",
    "_run_systemcheck",
)


def _cleanup_legacy_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Entfernt veraltete sowie gelöschte Anwesenheitssensor-Entitäten sauber aus der Entity-Registry."""
    ent_reg = er.async_get(hass)
    config = {**entry.data, **entry.options}
    active_ps_uids = {
        f"{entry.entry_id}_presence_sensor_{s['id']}"
        for s in normalize_presence_sensor_defs(config.get(CONF_PRESENCE_SENSORS) or [])
        if s.get("enabled", True)
    }
    ps_prefix = f"{entry.entry_id}_presence_sensor_"

    for reg_entry in list(er.async_entries_for_config_entry(ent_reg, entry.entry_id)):
        uid = reg_entry.unique_id or ""
        if (
            any(uid.endswith(suffix) for suffix in LEGACY_ENTITY_UNIQUE_ID_SUFFIXES)
            or "feedback" in uid.lower()
            or "feedback" in reg_entry.entity_id.lower()
        ):
            ent_reg.async_remove(reg_entry.entity_id)
        elif uid.startswith(ps_prefix) and uid not in active_ps_uids:
            ent_reg.async_remove(reg_entry.entity_id)


def _sync_device_info(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Aktualisiert bestehende Geräte-Informationen für alle 4 Bereiche in der Device-Registry."""
    dev_reg = dr.async_get(hass)
    for section, spec in SECTION_DEVICE_SPECS.items():
        ident = get_section_device_identifier(entry.entry_id, section)
        device = dev_reg.async_get_device(identifiers={ident})
        if device is not None:
            try:
                dev_reg.async_update_device(
                    device.id,
                    name=spec["name"],
                    model=spec["model"],
                    manufacturer=DEVICE_MANUFACTURER,
                    configuration_url=spec["config_url"],
                )
            except TypeError:
                pass


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Richtet Wohnsinnig vernetzt über einen Config Entry ein."""
    _cleanup_legacy_entities(hass, entry)
    _sync_device_info(hass, entry)
    domain_data = hass.data.setdefault(DOMAIN, {})

    if not domain_data.get("frontend_registered"):
        www_path = Path(__file__).parent / "www"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_BASE, str(www_path), cache_headers=False)]
        )
        add_extra_js_url(hass, f"{CARD_URL_BASE}/{CARD_FILENAME}?v={VERSION}")
        hass.http.register_view(WohnsinnigVernetztEpisodesView())
        hass.http.register_view(WohnsinnigVernetztPlayerStateView())
        hass.http.register_view(WohnsinnigVernetztImportBlueprintView())
        hass.http.register_view(WohnsinnigVernetztBatteryCheckView())
        hass.http.register_view(WohnsinnigVernetztSilentSensorsView())
        hass.http.register_view(WohnsinnigVernetztBatteryExclusionsView())
        hass.http.register_view(WohnsinnigVernetztPresenceConfigView())
        hass.http.register_view(WohnsinnigVernetztWakeUpConfigView())
        hass.http.register_view(WohnsinnigVernetztPvConfigView())
        hass.http.register_view(WohnsinnigVernetztPvTriggerView())
        hass.http.register_view(WohnsinnigVernetztPresenceSensorsConfigView())
        domain_data["frontend_registered"] = True

    config = {**entry.data, **entry.options}
    raw_notify = config.get(
        CONF_NOTIFY_SERVICES,
        config.get(CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICES),
    )

    coordinator = WohnsinnigVernetztCoordinator(
        hass=hass,
        rss_url=config.get(CONF_RSS_URL, DEFAULT_RSS_URL),
        notify_services=normalize_notify_services(raw_notify),
        scan_interval_minutes=int(
            config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        ),
        logo_url=config.get(CONF_LOGO_URL) or DEFAULT_LOGO_URL,
        spotify_show_url=config.get(
            CONF_SPOTIFY_SHOW_URL, DEFAULT_SPOTIFY_SHOW_URL
        ),
        blueprints_url=config.get(CONF_BLUEPRINTS_URL) or DEFAULT_BLUEPRINTS_URL,
        alerts_url=config.get(CONF_ALERTS_URL) or DEFAULT_ALERTS_URL,
        battery_threshold=int(
            config.get(CONF_BATTERY_THRESHOLD, DEFAULT_BATTERY_THRESHOLD)
        ),
        battery_excluded_devices=config.get(CONF_BATTERY_EXCLUDED_DEVICES),
        silent_hours=int(config.get(CONF_SILENT_HOURS, DEFAULT_SILENT_HOURS)),
        battery_push_enabled=bool(
            config.get(CONF_BATTERY_PUSH_ENABLED, DEFAULT_BATTERY_PUSH_ENABLED)
        ),
        battery_push_mode=str(
            config.get(CONF_BATTERY_PUSH_MODE, DEFAULT_BATTERY_PUSH_MODE)
        ),
        battery_push_time=str(
            config.get(CONF_BATTERY_PUSH_TIME, DEFAULT_BATTERY_PUSH_TIME)
        ),
        presence_entities=config.get(CONF_PRESENCE_ENTITIES),
        presence_pause_automations=config.get(CONF_PRESENCE_PAUSE_AUTOMATIONS),
        presence_auto_pause_motion=bool(
            config.get(
                CONF_PRESENCE_AUTO_PAUSE_MOTION, DEFAULT_PRESENCE_AUTO_PAUSE_MOTION
            )
        ),
        presence_jitter_minutes=int(
            config.get(
                CONF_PRESENCE_JITTER_MINUTES, DEFAULT_PRESENCE_JITTER_MINUTES
            )
        ),
        wakeup_entities=config.get(CONF_WAKEUP_ENTITIES),
        wakeup_alarm_entity=str(
            config.get(CONF_WAKEUP_ALARM_ENTITY, DEFAULT_WAKEUP_ALARM_ENTITY)
        ),
        wakeup_mode=str(config.get(CONF_WAKEUP_MODE, DEFAULT_WAKEUP_MODE)),
        wakeup_time=str(config.get(CONF_WAKEUP_TIME, DEFAULT_WAKEUP_TIME)),
        wakeup_duration=int(
            config.get(CONF_WAKEUP_DURATION, DEFAULT_WAKEUP_DURATION)
        ),
        wakeup_auto_off_minutes=int(
            config.get(CONF_WAKEUP_AUTO_OFF_MINUTES, DEFAULT_WAKEUP_AUTO_OFF_MINUTES)
        ),
        wakeup_days=str(config.get(CONF_WAKEUP_DAYS, DEFAULT_WAKEUP_DAYS)),
        wakeup_auto_pause=bool(
            config.get(CONF_WAKEUP_AUTO_PAUSE, DEFAULT_WAKEUP_AUTO_PAUSE)
        ),
        wakeup_pause_automations=config.get(CONF_WAKEUP_PAUSE_AUTOMATIONS),
        wakeup_sunrise_color=bool(
            config.get(CONF_WAKEUP_SUNRISE_COLOR, DEFAULT_WAKEUP_SUNRISE_COLOR)
        ),
        pv_surplus_entity=str(
            config.get(CONF_PV_SURPLUS_ENTITY, DEFAULT_PV_SURPLUS_ENTITY)
        ),
        pv_battery_entity=str(
            config.get(CONF_PV_BATTERY_ENTITY, DEFAULT_PV_BATTERY_ENTITY)
        ),
        pv_invert_surplus=bool(
            config.get(CONF_PV_INVERT_SURPLUS, DEFAULT_PV_INVERT_SURPLUS)
        ),
        pv_rules=config.get(CONF_PV_RULES),
        presence_sensors=config.get(CONF_PRESENCE_SENSORS),
        default_target=config.get(CONF_DEFAULT_TARGET, BROWSER_TARGET),
    )

    await coordinator.async_config_entry_first_refresh()
    coordinator.setup_battery_push_schedule()
    entry.async_on_unload(coordinator.async_shutdown_timers)
    domain_data["coordinator"] = coordinator
    domain_data[entry.entry_id] = coordinator

    # Interaktive Companion-App-Push-Buttons direkt verarbeiten (ohne eigene Automation!)
    async def _handle_mobile_app_action(event: Event) -> None:
        action = event.data.get("action")
        if action == ACTION_PLAY_LATEST:
            await coordinator.async_play_latest_episode()
        elif action == ACTION_MARK_SEEN:
            await coordinator.async_mark_latest_episode_seen()

    entry.async_on_unload(
        hass.bus.async_listen(
            "mobile_app_notification_action", _handle_mobile_app_action
        )
    )

    # Anwesenheitssimulation & lokale Checks starten (nach HA-Start, falls noch am Booten)
    if hass.is_running:
        await coordinator.async_init_presence_simulation()
        await coordinator.async_init_wakeup_light()
        await coordinator.async_init_pv_surplus()
        await coordinator.async_init_presence_sensors()
    else:
        async def _run_after_ha_started(_event: Event) -> None:
            await coordinator.async_init_presence_simulation()
            await coordinator.async_init_wakeup_light()
            await coordinator.async_init_pv_surplus()
            await coordinator.async_init_presence_sensors()
            await coordinator.async_run_battery_check(notify=False)
            await coordinator.async_run_silent_sensors_check(notify=False)

        entry.async_on_unload(
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _run_after_ha_started
            )
        )

    if not hass.services.has_service(DOMAIN, SERVICE_IMPORT_BLUEPRINT):
        async def _handle_import_blueprint(call: ServiceCall) -> None:
            coord: WohnsinnigVernetztCoordinator | None = hass.data.get(
                DOMAIN, {}
            ).get("coordinator")
            if coord is None:
                raise HomeAssistantError("Wohnsinnig vernetzt ist nicht aktiv.")
            if call.data.get("import_all"):
                await coord.async_import_all_blueprints()
                return
            await coord.async_import_blueprint(
                url=call.data.get("url"),
                blueprint_id=call.data.get("blueprint_id"),
            )

        hass.services.async_register(
            DOMAIN,
            SERVICE_IMPORT_BLUEPRINT,
            _handle_import_blueprint,
            schema=IMPORT_BLUEPRINT_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_MARK_EPISODE_SEEN):
        async def _handle_mark_episode_seen(call: ServiceCall) -> None:
            coord: WohnsinnigVernetztCoordinator | None = hass.data.get(
                DOMAIN, {}
            ).get("coordinator")
            if coord is None:
                raise HomeAssistantError("Wohnsinnig vernetzt ist nicht aktiv.")
            await coord.async_mark_latest_episode_seen()

        hass.services.async_register(
            DOMAIN,
            SERVICE_MARK_EPISODE_SEEN,
            _handle_mark_episode_seen,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RUN_BATTERY_CHECK):
        async def _handle_run_battery_check(call: ServiceCall) -> None:
            coord: WohnsinnigVernetztCoordinator | None = hass.data.get(
                DOMAIN, {}
            ).get("coordinator")
            if coord is None:
                raise HomeAssistantError("Wohnsinnig vernetzt ist nicht aktiv.")
            await coord.async_run_battery_check(
                notify=bool(call.data.get("notify", False))
            )

        hass.services.async_register(
            DOMAIN,
            SERVICE_RUN_BATTERY_CHECK,
            _handle_run_battery_check,
            schema=RUN_BATTERY_CHECK_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RUN_SILENT_SENSORS_CHECK):
        async def _handle_run_silent_sensors_check(call: ServiceCall) -> None:
            coord: WohnsinnigVernetztCoordinator | None = hass.data.get(
                DOMAIN, {}
            ).get("coordinator")
            if coord is None:
                raise HomeAssistantError("Wohnsinnig vernetzt ist nicht aktiv.")
            await coord.async_run_silent_sensors_check(
                notify=bool(call.data.get("notify", False))
            )

        hass.services.async_register(
            DOMAIN,
            SERVICE_RUN_SILENT_SENSORS_CHECK,
            _handle_run_silent_sensors_check,
            schema=RUN_SILENT_SENSORS_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RESET_BATTERY_PUSH_MEMORY):
        async def _handle_reset_battery_memory(call: ServiceCall) -> None:
            coord: WohnsinnigVernetztCoordinator | None = hass.data.get(
                DOMAIN, {}
            ).get("coordinator")
            if coord is None:
                raise HomeAssistantError("Wohnsinnig vernetzt ist nicht aktiv.")
            await coord.async_reset_battery_push_memory()

        hass.services.async_register(
            DOMAIN,
            SERVICE_RESET_BATTERY_PUSH_MEMORY,
            _handle_reset_battery_memory,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_EXCLUDE_BATTERY_DEVICE):
        async def _handle_exclude_battery_device(call: ServiceCall) -> None:
            coord: WohnsinnigVernetztCoordinator | None = hass.data.get(
                DOMAIN, {}
            ).get("coordinator")
            if coord is None:
                raise HomeAssistantError("Wohnsinnig vernetzt ist nicht aktiv.")
            identifier = (
                call.data.get("key")
                or call.data.get("device_id")
                or call.data.get("entity_id")
                or ""
            )
            await coord.async_exclude_battery_device(str(identifier))

        hass.services.async_register(
            DOMAIN,
            SERVICE_EXCLUDE_BATTERY_DEVICE,
            _handle_exclude_battery_device,
            schema=BATTERY_EXCLUSION_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_INCLUDE_BATTERY_DEVICE):
        async def _handle_include_battery_device(call: ServiceCall) -> None:
            coord: WohnsinnigVernetztCoordinator | None = hass.data.get(
                DOMAIN, {}
            ).get("coordinator")
            if coord is None:
                raise HomeAssistantError("Wohnsinnig vernetzt ist nicht aktiv.")
            identifier = (
                call.data.get("key")
                or call.data.get("device_id")
                or call.data.get("entity_id")
                or ""
            )
            await coord.async_include_battery_device(str(identifier))

        hass.services.async_register(
            DOMAIN,
            SERVICE_INCLUDE_BATTERY_DEVICE,
            _handle_include_battery_device,
            schema=BATTERY_EXCLUSION_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_START_WAKEUP):
        async def _handle_start_wakeup(call: ServiceCall) -> None:
            coord: WohnsinnigVernetztCoordinator | None = hass.data.get(
                DOMAIN, {}
            ).get("coordinator")
            if coord is None:
                raise HomeAssistantError("Wohnsinnig vernetzt ist nicht aktiv.")
            await coord.wakeup_manager.async_start_now(
                duration_override=call.data.get("duration_minutes"),
                auto_off_override=call.data.get("auto_off_minutes"),
                is_scheduled=False,
            )

        hass.services.async_register(
            DOMAIN,
            SERVICE_START_WAKEUP,
            _handle_start_wakeup,
            schema=START_WAKEUP_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_STOP_WAKEUP):
        async def _handle_stop_wakeup(call: ServiceCall) -> None:
            coord: WohnsinnigVernetztCoordinator | None = hass.data.get(
                DOMAIN, {}
            ).get("coordinator")
            if coord is None:
                raise HomeAssistantError("Wohnsinnig vernetzt ist nicht aktiv.")
            await coord.wakeup_manager.async_stop(cancelled=True)

        hass.services.async_register(
            DOMAIN,
            SERVICE_STOP_WAKEUP,
            _handle_stop_wakeup,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_EVALUATE_PV):
        async def _handle_evaluate_pv(call: ServiceCall) -> None:
            coord: WohnsinnigVernetztCoordinator | None = hass.data.get(
                DOMAIN, {}
            ).get("coordinator")
            if coord is None:
                raise HomeAssistantError("Wohnsinnig vernetzt ist nicht aktiv.")
            await coord.pv_manager.async_evaluate()

        hass.services.async_register(
            DOMAIN,
            SERVICE_EVALUATE_PV,
            _handle_evaluate_pv,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RESET_PV_DAILY):
        async def _handle_reset_pv_daily(call: ServiceCall) -> None:
            coord: WohnsinnigVernetztCoordinator | None = hass.data.get(
                DOMAIN, {}
            ).get("coordinator")
            if coord is None:
                raise HomeAssistantError("Wohnsinnig vernetzt ist nicht aktiv.")
            await coord.pv_manager.async_reset_daily_triggers()

        hass.services.async_register(
            DOMAIN,
            SERVICE_RESET_PV_DAILY,
            _handle_reset_pv_daily,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_EVALUATE_PRESENCE_SENSORS):
        async def _handle_evaluate_presence_sensors(call: ServiceCall) -> None:
            coord: WohnsinnigVernetztCoordinator | None = hass.data.get(
                DOMAIN, {}
            ).get("coordinator")
            if coord is None:
                raise HomeAssistantError("Wohnsinnig vernetzt ist nicht aktiv.")
            await coord.presence_sensors_manager.async_evaluate()

        hass.services.async_register(
            DOMAIN,
            SERVICE_EVALUATE_PRESENCE_SENSORS,
            _handle_evaluate_presence_sensors,
        )

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Lädt die Integration bei geänderten Optionen neu."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entlädt die Integration sauber."""
    domain_data = hass.data.get(DOMAIN, {})
    coordinator: WohnsinnigVernetztCoordinator | None = domain_data.get(entry.entry_id)
    if coordinator is not None:
        await coordinator.async_shutdown_presence()
        await coordinator.async_shutdown_wakeup_light()
        await coordinator.async_shutdown_pv_surplus()
        await coordinator.async_shutdown_presence_sensors()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data.pop(entry.entry_id, None)
        domain_data.pop("coordinator", None)
        for svc in (
            SERVICE_IMPORT_BLUEPRINT,
            SERVICE_MARK_EPISODE_SEEN,
            SERVICE_RUN_BATTERY_CHECK,
            SERVICE_RUN_SILENT_SENSORS_CHECK,
            SERVICE_RESET_BATTERY_PUSH_MEMORY,
            SERVICE_EXCLUDE_BATTERY_DEVICE,
            SERVICE_INCLUDE_BATTERY_DEVICE,
            SERVICE_START_WAKEUP,
            SERVICE_STOP_WAKEUP,
            SERVICE_EVALUATE_PV,
            SERVICE_RESET_PV_DAILY,
            SERVICE_EVALUATE_PRESENCE_SENSORS,
        ):
            if hass.services.has_service(DOMAIN, svc):
                hass.services.async_remove(DOMAIN, svc)
    return unload_ok
