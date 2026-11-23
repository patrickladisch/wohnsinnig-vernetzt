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

from .const import (
    CARD_FILENAME,
    CARD_URL_BASE,
    CONF_FEEDBACK_WEBHOOK_URL,
    CONF_LOGO_URL,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_SERVICES,
    CONF_RSS_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_FEEDBACK_WEBHOOK_URL,
    DEFAULT_LOGO_URL,
    DEFAULT_NOTIFY_SERVICES,
    DEFAULT_RSS_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_SEND_FEEDBACK,
    VERSION,
)
from .coordinator import WohnsinnigVernetztCoordinator, normalize_notify_services

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.TEXT,
    Platform.EVENT,
]

SEND_FEEDBACK_SCHEMA = vol.Schema(
    {
        vol.Required("message"): str,
        vol.Optional("sender", default=""): str,
        vol.Optional("episode", default=""): str,
    }
)


class WohnsinnigVernetztEpisodesView(HomeAssistantView):
    """Liefert alle Podcast-Episoden und Feedback-Infos als JSON an die Karte."""

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
                    "image": "",
                    "episodes": [],
                    "feedback_configured": False,
                    "feedback_fallback_url": "https://www.wohnsinnigvernetzt.de",
                }
            )

        return self.json(
            {
                **coordinator.data,
                "feedback_configured": bool(coordinator.feedback_webhook_url),
                "feedback_fallback_url": coordinator.feedback_fallback_url,
            }
        )


class WohnsinnigVernetztFeedbackView(HomeAssistantView):
    """Nimmt Feedback aus der Dashboard-Karte entgegen."""

    url = f"/api/{DOMAIN}/feedback"
    name = f"api:{DOMAIN}:feedback"
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

        try:
            await coordinator.async_send_feedback(
                message=str(payload.get("message", "")),
                sender=str(payload.get("sender", "")),
                episode=str(payload.get("episode", "")),
            )
        except HomeAssistantError as err:
            return self.json({"error": str(err)}, status_code=400)

        return self.json({"status": "ok"})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Richtet Wohnsinnig vernetzt über einen Config Entry ein."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    if not domain_data.get("frontend_registered"):
        www_path = Path(__file__).parent / "www"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_BASE, str(www_path), cache_headers=False)]
        )
        add_extra_js_url(hass, f"{CARD_URL_BASE}/{CARD_FILENAME}?v={VERSION}")
        hass.http.register_view(WohnsinnigVernetztEpisodesView())
        hass.http.register_view(WohnsinnigVernetztFeedbackView())
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
        feedback_webhook_url=config.get(
            CONF_FEEDBACK_WEBHOOK_URL, DEFAULT_FEEDBACK_WEBHOOK_URL
        ),
    )

    await coordinator.async_config_entry_first_refresh()
    domain_data["coordinator"] = coordinator
    domain_data[entry.entry_id] = coordinator

    if not hass.services.has_service(DOMAIN, SERVICE_SEND_FEEDBACK):
        async def _handle_send_feedback(call: ServiceCall) -> None:
            coord: WohnsinnigVernetztCoordinator | None = hass.data.get(
                DOMAIN, {}
            ).get("coordinator")
            if coord is None:
                raise HomeAssistantError("Wohnsinnig vernetzt ist nicht aktiv.")
            await coord.async_send_feedback(
                message=call.data["message"],
                sender=call.data.get("sender", ""),
                episode=call.data.get("episode", ""),
            )

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_FEEDBACK,
            _handle_send_feedback,
            schema=SEND_FEEDBACK_SCHEMA,
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
        if hass.services.has_service(DOMAIN, SERVICE_SEND_FEEDBACK):
            hass.services.async_remove(DOMAIN, SERVICE_SEND_FEEDBACK)
    return unload_ok
