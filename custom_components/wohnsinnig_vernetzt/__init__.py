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
    CONF_BATTERY_PUSH_ENABLED,
    CONF_BATTERY_PUSH_MODE,
    CONF_BATTERY_PUSH_TIME,
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_BATTERY_THRESHOLD,
    CONF_BLUEPRINTS_URL,
    CONF_DEFAULT_TARGET,
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
    DEVICE_CONFIG_URL,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
    SERVICE_IMPORT_BLUEPRINT,
    SERVICE_MARK_EPISODE_SEEN,
    SERVICE_EXCLUDE_BATTERY_DEVICE,
    SERVICE_INCLUDE_BATTERY_DEVICE,
    SERVICE_RESET_BATTERY_PUSH_MEMORY,
    SERVICE_RUN_BATTERY_CHECK,
    SERVICE_RUN_SILENT_SENSORS_CHECK,
    VERSION,
)
from .coordinator import WohnsinnigVernetztCoordinator, normalize_notify_services

PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
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


class WohnsinnigVernetztEpisodesView(HomeAssistantView):
    """Liefert Podcast-Episoden, Blueprints und Player-Infos als JSON an die Karte."""

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


LEGACY_ENTITY_UNIQUE_ID_SUFFIXES = (
    "_send_feedback",
    "_feedback_message",
    "_systemcheck",
    "_run_systemcheck",
)


def _cleanup_legacy_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Entfernt veraltete Feedback-Entitäten dauerhaft aus der HA-Entity-Registry."""
    ent_reg = er.async_get(hass)
    for reg_entry in list(er.async_entries_for_config_entry(ent_reg, entry.entry_id)):
        uid = reg_entry.unique_id or ""
        if (
            any(uid.endswith(suffix) for suffix in LEGACY_ENTITY_UNIQUE_ID_SUFFIXES)
            or "feedback" in uid.lower()
            or "feedback" in reg_entry.entity_id.lower()
        ):
            ent_reg.async_remove(reg_entry.entity_id)


def _sync_device_info(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Aktualisiert bestehende Geräte-Informationen direkt in der Device-Registry."""
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    if device is not None:
        try:
            dev_reg.async_update_device(
                device.id,
                name=DEVICE_NAME,
                model=DEVICE_MODEL,
                manufacturer=DEVICE_MANUFACTURER,
                configuration_url=DEVICE_CONFIG_URL,
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
        hass.bus.async_listen("mobile_app_notification_action", _handle_mobile_app_action)
    )

    # Erste lokale Checks nach vollständigem HA-Start ausführen (vermeidet Boot-Fehlalarme)
    if not hass.is_running:
        async def _run_initial_local_checks(_event: Event) -> None:
            await coordinator.async_run_battery_check(notify=False)
            await coordinator.async_run_silent_sensors_check(notify=False)

        entry.async_on_unload(
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _run_initial_local_checks
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
            await coord.async_run_battery_check(notify=bool(call.data.get("notify", False)))

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
            SERVICE_EXCLUDE_BATTERY_DEVICE,
            SERVICE_INCLUDE_BATTERY_DEVICE,
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

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Lädt die Integration bei geänderten Optionen neu."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entlädt die Integration sauber."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data = hass.data.get(DOMAIN, {})
        domain_data.pop(entry.entry_id, None)
        domain_data.pop("coordinator", None)
        for svc in (
            SERVICE_IMPORT_BLUEPRINT,
            SERVICE_MARK_EPISODE_SEEN,
            SERVICE_RUN_BATTERY_CHECK,
            SERVICE_RUN_SILENT_SENSORS_CHECK,
            SERVICE_RESET_BATTERY_PUSH_MEMORY,
        ):
            if hass.services.has_service(DOMAIN, svc):
                hass.services.async_remove(DOMAIN, svc)
    return unload_ok
