"""DataUpdateCoordinator für den Podcast-RSS-Feed."""

from __future__ import annotations

from datetime import timedelta
import email.utils
import html
import logging
import re
import xml.etree.ElementTree as ET

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    EVENT_NEW_EPISODE,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


def _format_duration(raw: str | None) -> str:
    """Formatiert Sekunden oder HH:MM:SS sauber lesbar."""
    if not raw:
        return ""
    raw = raw.strip()
    if raw.isdigit():
        total = int(raw)
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"
    return raw


def _clean_html(raw: str | None) -> str:
    """Entfernt HTML-Tags aus den Shownotes."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _format_date(raw: str | None) -> str:
    """Wandelt das RSS-Datum in DD.MM.YYYY um."""
    if not raw:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        return dt.strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return raw


def _parse_rss(xml_text: str) -> dict:
    """Parst den Podcast-RSS-Feed."""
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("Ungültiger RSS-Feed: Kein <channel>-Element gefunden.")

    podcast_title = (channel.findtext("title") or "Wohnsinnig vernetzt").strip()
    podcast_desc = _clean_html(channel.findtext("description"))

    podcast_image = ""
    itunes_img = channel.find(f"{{{ITUNES_NS}}}image")
    if itunes_img is not None and itunes_img.attrib.get("href"):
        podcast_image = itunes_img.attrib["href"]
    else:
        img_url = channel.findtext("image/url")
        if img_url:
            podcast_image = img_url.strip()

    episodes = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        audio_url = enclosure.attrib.get("url", "") if enclosure is not None else ""
        if not audio_url:
            continue

        title = (item.findtext("title") or "Unbenannte Folge").strip()
        guid = (item.findtext("guid") or audio_url or title).strip()
        pub_date = _format_date(item.findtext("pubDate"))
        duration = _format_duration(item.findtext(f"{{{ITUNES_NS}}}duration"))
        description = _clean_html(item.findtext("description"))

        ep_image = podcast_image
        ep_itunes_img = item.find(f"{{{ITUNES_NS}}}image")
        if ep_itunes_img is not None and ep_itunes_img.attrib.get("href"):
            ep_image = ep_itunes_img.attrib["href"]

        episodes.append(
            {
                "guid": guid,
                "title": title,
                "pub_date": pub_date,
                "duration": duration,
                "description": description[:300],
                "audio_url": audio_url,
                "image": ep_image,
            }
        )

    return {
        "title": podcast_title,
        "description": podcast_desc,
        "image": podcast_image,
        "episodes": episodes,
    }


class WohnsinnigVernetztCoordinator(DataUpdateCoordinator[dict]):
    """Verwaltet das Abrufen des Feeds und Benachrichtigungen bei neuen Folgen."""

    def __init__(
        self,
        hass: HomeAssistant,
        rss_url: str,
        notify_service: str,
        scan_interval_minutes: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval_minutes),
        )
        self.rss_url = rss_url
        self.notify_service = notify_service.strip()
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._seen_guids: set[str] | None = None

    async def _async_update_data(self) -> dict:
        """Lädt den RSS-Feed und prüft auf neue Episoden."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                self.rss_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                response.raise_for_status()
                xml_text = await response.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Feed konnte nicht geladen werden: {err}") from err

        try:
            data = await self.hass.async_add_executor_job(_parse_rss, xml_text)
        except Exception as err:
            raise UpdateFailed(
                f"RSS-Feed konnte nicht verarbeitet werden: {err}"
            ) from err

        await self._handle_new_episodes(data["episodes"])
        return data

    async def _handle_new_episodes(self, episodes: list[dict]) -> None:
        """Prüft auf unbekannte GUIDs und löst Benachrichtigungen aus."""
        if not episodes:
            return

        if self._seen_guids is None:
            stored = await self._store.async_load()
            if stored and isinstance(stored.get("guids"), list):
                self._seen_guids = set(stored["guids"])
            else:
                self._seen_guids = {ep["guid"] for ep in episodes}
                await self._store.async_save({"guids": list(self._seen_guids)})
                return

        new_episodes = [ep for ep in episodes if ep["guid"] not in self._seen_guids]
        if not new_episodes:
            return

        for ep in reversed(new_episodes):
            self._seen_guids.add(ep["guid"])
            await self._notify_new_episode(ep)

        await self._store.async_save({"guids": list(self._seen_guids)})

    async def _notify_new_episode(self, episode: dict) -> None:
        """Feuert das HA-Event und ruft den konfigurierten Benachrichtigungsdienst auf."""
        self.hass.bus.async_fire(EVENT_NEW_EPISODE, episode)

        if not self.notify_service:
            return

        if "." in self.notify_service:
            domain, service = self.notify_service.split(".", 1)
        else:
            domain, service = "notify", self.notify_service

        payload = {
            "title": "Neue Folge: Wohnsinnig vernetzt",
            "message": f"{episode['title']} ({episode['duration']})"
            if episode.get("duration")
            else episode["title"],
        }

        try:
            await self.hass.services.async_call(
                domain, service, payload, blocking=False
            )
        except Exception as err:
            _LOGGER.warning(
                "Benachrichtigung über %s.%s fehlgeschlagen: %s",
                domain,
                service,
                err,
            )
