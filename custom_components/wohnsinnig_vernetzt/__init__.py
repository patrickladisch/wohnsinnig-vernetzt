"""Integration für den Podcast Wohnsinnig vernetzt."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web
import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import (
    BROWSER_TARGET,
    CARD_FILENAME,
    CARD_URL_BASE,
    CONF_BLUEPRINTS_URL,
    CONF_DEFAULT_TARGET,
    CONF_LOGO_URL,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_SERVICES,
    CONF_RSS_URL,
    CONF_SCAN_INTERVAL,
    CONF_SPOTIFY_SHOW_URL,
    DEFAULT_BLUEPRINTS_URL,
    DEFAULT_LOGO_URL,
    DEFAULT_NOTIFY_SERVICES,
    DEFAULT_RSS_URL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SPOTIFY_SHOW_URL,
    DOMAIN,
    SERVICE_IMPORT_BLUEPRINT,
    VERSION,
)
from .coordinator import WohnsinnigVernetztCoordinator, normalize_notify_services

PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.EVENT,
]

IMPORT_BLUEPRINT_SCHEMA = vol.Schema(
    {
        vol.Optional("url"): str,
        vol.Optional("blueprint_id"): str,
        vol.Optional("import_all", default=False): bool,
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
                    "spotify_show_id": "",
                    "spotify_show_url": "",
                    "target_entity": BROWSER_TARGET,
                    "selected_episode_guid": None,
                }
            )

        return self.json(
            {
                **coordinator.data,
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


LEGACY_ENTITY_UNIQUE_ID_SUFFIXES = (
    "_send_feedback",
    "_feedback_message",
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Richtet Wohnsinnig vernetzt über einen Config Entry ein."""
    _cleanup_legacy_entities(hass, entry)
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
        default_target=config.get(CONF_DEFAULT_TARGET, BROWSER_TARGET),
    )

    await coordinator.async_config_entry_first_refresh()
    domain_data["coordinator"] = coordinator
    domain_data[entry.entry_id] = coordinator

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
        if hass.services.has_service(DOMAIN, SERVICE_IMPORT_BLUEPRINT):
            hass.services.async_remove(DOMAIN, SERVICE_IMPORT_BLUEPRINT)
    return unload_ok
