"""Image-Entität für die Episoden-Infografik von Wohnsinnig vernetzt."""

from __future__ import annotations

from pathlib import Path

import aiohttp

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .blueprints import HTTP_HEADERS
from .const import DOMAIN
from .coordinator import WohnsinnigVernetztCoordinator
from .entity import WohnsinnigVernetztEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Erstellt die Infografik-Image-Entität."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [WohnsinnigVernetztInfographicImage(hass, coordinator, entry.entry_id)]
    )


class WohnsinnigVernetztInfographicImage(WohnsinnigVernetztEntity, ImageEntity):
    """Zeigt die Infografik der aktuellen/ausgewählten Podcast-Folge an."""

    _attr_name = "Episoden-Infografik"
    _attr_icon = "mdi:image-area"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: WohnsinnigVernetztCoordinator,
        entry_id: str,
    ) -> None:
        WohnsinnigVernetztEntity.__init__(self, coordinator, entry_id, "episode_infographic")
        ImageEntity.__init__(self, hass)
        self._cached_url: str | None = None
        self._cached_bytes: bytes | None = None
        self._cached_content_type: str = "image/png"
        self._attr_image_last_updated = dt_util.utcnow()

    def _resolve_info(self) -> tuple[str, str]:
        """Liefert (url, titel) für die aktuell passende Infografik."""
        info = self.coordinator.get_current_infographic()
        if info and info.get("url"):
            return info["url"], info.get("title", "Episoden-Infografik")
        ep = self.coordinator.get_selected_episode()
        if ep and ep.get("rss_image") and ep["rss_image"].startswith(("http://", "https://")):
            return ep["rss_image"], ep.get("title", "Podcast Cover")
        return "", "Wohnsinnig vernetzt"

    def _handle_coordinator_update(self) -> None:
        url, _ = self._resolve_info()
        if url != self._cached_url:
            self._cached_bytes = None
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    @property
    def content_type(self) -> str:
        return self._cached_content_type

    @property
    def extra_state_attributes(self) -> dict:
        url, title = self._resolve_info()
        ep = self.coordinator.get_selected_episode() or {}
        matched = self.coordinator.get_current_infographic()
        return {
            "episode_number": ep.get("episode_number"),
            "episode_title": ep.get("title", ""),
            "has_infographic": matched is not None,
            "infographic_filename": matched.get("filename", "") if matched else "",
            "image_url": url,
            "infographic_title": title,
            "infographics_count": len(self.coordinator.get_infographics()),
        }

    def _read_fallback_logo(self) -> bytes | None:
        logo_path = Path(__file__).parent / "www" / "logo.png"
        if logo_path.is_file():
            return logo_path.read_bytes()
        return None

    async def async_image(self) -> bytes | None:
        """Lädt die aktuelle Episoden-Infografik (mit In-Memory-Cache) oder Fallback-Logo."""
        url, _ = self._resolve_info()
        if url and url == self._cached_url and self._cached_bytes:
            return self._cached_bytes

        if url and url.startswith(("http://", "https://")):
            session = async_get_clientsession(self.hass)
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=15),
                    headers=HTTP_HEADERS,
                ) as response:
                    if response.status == 200:
                        data = await response.read()
                        ctype = response.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                        self._cached_url = url
                        self._cached_bytes = data
                        self._cached_content_type = ctype or "image/jpeg"
                        return data
            except (aiohttp.ClientError, TimeoutError):
                pass

        fallback = await self.hass.async_add_executor_job(self._read_fallback_logo)
        if fallback:
            self._cached_content_type = "image/png"
            return fallback
        return None
