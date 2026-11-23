"""DataUpdateCoordinator für den Podcast-RSS-Feed, Benachrichtigungen und Feedback."""

from __future__ import annotations

from datetime import timedelta
import email.utils
import html
import logging
import re
import xml.etree.ElementTree as ET

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_FEEDBACK_FALLBACK_URL,
    DOMAIN,
    EVENT_FEEDBACK_SENT,
    EVENT_NEW_EPISODE,
    SIGNAL_NEW_EPISODE,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


def normalize_notify_services(raw: str | list[str] | None) -> list[str]:
    """Wandelt Einzelstring oder Liste sauber in eine Liste von Diensten um."""
    if not raw:
        return []
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [str(item).strip() for item in raw if str(item).strip()]


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


def _parse_rss(xml_text: str, override_logo_url: str = "") -> dict:
    """Parst den Podcast-RSS-Feed."""
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("Ungültiger RSS-Feed: Kein <channel>-Element gefunden.")

    podcast_title = (channel.findtext("title") or "Wohnsinnig vernetzt").strip()
    podcast_desc = _clean_html(channel.findtext("description"))

    podcast_image = override_logo_url.strip()
    if not podcast_image:
        itunes_img = channel.find(f"{{{ITUNES_NS}}}image")
        if itunes_img is not None and itunes_img.attrib.get("href"):
            podcast_image = itunes_img.attrib["href"]
        else:
            img_url = channel.findtext("image/url")
            if img_url:
                podcast_image = img_url.strip()

    episodes = []
    for idx, item in enumerate(channel.findall("item"), start=1):
        enclosure = item.find("enclosure")
        audio_url = enclosure.attrib.get("url", "") if enclosure is not None else ""
        if not audio_url:
            continue

        title = (item.findtext("title") or f"Folge {idx}").strip()
        guid = (item.findtext("guid") or audio_url or title).strip()
        pub_date = _format_date(item.findtext("pubDate"))
        duration = _format_duration(item.findtext(f"{{{ITUNES_NS}}}duration"))
        description = _clean_html(item.findtext("description"))

        ep_image = podcast_image
        if not override_logo_url.strip():
            ep_itunes_img = item.find(f"{{{ITUNES_NS}}}image")
            if ep_itunes_img is not None and ep_itunes_img.attrib.get("href"):
                ep_image = ep_itunes_img.attrib["href"]

        episodes.append(
            {
                "guid": guid,
                "title": title,
                "pub_date": pub_date,
                "duration": duration,
                "description": description[:400],
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
    """Verwaltet RSS-Feed, Benachrichtigungen, Auswahl und Feedback."""

    def __init__(
        self,
        hass: HomeAssistant,
        rss_url: str,
        notify_services: list[str],
        scan_interval_minutes: int,
        logo_url: str = "",
        feedback_webhook_url: str = "",
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval_minutes),
        )
        self.rss_url = rss_url
        self.logo_url = logo_url.strip()
        self.notify_services = notify_services
        self.feedback_webhook_url = feedback_webhook_url.strip()
        self.feedback_fallback_url = DEFAULT_FEEDBACK_FALLBACK_URL

        self._store: Store[dict] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._seen_guids: set[str] | None = None
        self.notifications_enabled: bool = True
        self.selected_episode_guid: str | None = None
        self.feedback_draft: str = ""
        self._state_loaded: bool = False

    async def _async_load_state(self) -> None:
        if self._state_loaded:
            return
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            if isinstance(stored.get("guids"), list):
                self._seen_guids = set(stored["guids"])
            if isinstance(stored.get("notifications_enabled"), bool):
                self.notifications_enabled = stored["notifications_enabled"]
            if isinstance(stored.get("selected_episode_guid"), str):
                self.selected_episode_guid = stored["selected_episode_guid"]
        self._state_loaded = True

    async def _async_save_state(self) -> None:
        await self._store.async_save(
            {
                "guids": list(self._seen_guids or []),
                "notifications_enabled": self.notifications_enabled,
                "selected_episode_guid": self.selected_episode_guid,
            }
        )

    async def async_set_notifications_enabled(self, enabled: bool) -> None:
        """Aktiviert oder deaktiviert Benachrichtigungen persistent."""
        self.notifications_enabled = enabled
        await self._async_save_state()
        self.async_update_listeners()

    async def async_set_selected_episode(self, guid: str) -> None:
        """Speichert die im Dropdown ausgewählte Episode."""
        self.selected_episode_guid = guid
        await self._async_save_state()
        self.async_update_listeners()

    def get_selected_episode(self) -> dict | None:
        """Gibt die aktuell ausgewählte Episode (oder die neueste) zurück."""
        episodes = (self.data or {}).get("episodes", [])
        if not episodes:
            return None
        if self.selected_episode_guid:
            for ep in episodes:
                if ep["guid"] == self.selected_episode_guid:
                    return ep
        return episodes[0]

    async def _async_update_data(self) -> dict:
        """Lädt den RSS-Feed und prüft auf neue Episoden."""
        await self._async_load_state()
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
            data = await self.hass.async_add_executor_job(
                _parse_rss, xml_text, self.logo_url
            )
        except Exception as err:
            raise UpdateFailed(
                f"RSS-Feed konnte nicht verarbeitet werden: {err}"
            ) from err

        if data["episodes"] and not self.selected_episode_guid:
            self.selected_episode_guid = data["episodes"][0]["guid"]

        await self._handle_new_episodes(data["episodes"])
        return data

    async def _handle_new_episodes(self, episodes: list[dict]) -> None:
        """Prüft auf unbekannte GUIDs und löst Benachrichtigungen aus."""
        if not episodes:
            return

        if self._seen_guids is None:
            # Erststart: vorhandene Folgen merken, ohne Benachrichtigungsflut
            self._seen_guids = {ep["guid"] for ep in episodes}
            await self._async_save_state()
            return

        new_episodes = [ep for ep in episodes if ep["guid"] not in self._seen_guids]
        if not new_episodes:
            return

        for ep in reversed(new_episodes):
            self._seen_guids.add(ep["guid"])
            self.hass.bus.async_fire(EVENT_NEW_EPISODE, ep)
            async_dispatcher_send(self.hass, SIGNAL_NEW_EPISODE, ep)
            if self.notifications_enabled:
                await self.async_send_notification(ep, is_test=False)

        await self._async_save_state()

    async def async_send_notification(
        self, episode: dict, is_test: bool = False
    ) -> None:
        """Sendet eine Benachrichtigung über alle konfigurierten Dienste."""
        services = self.notify_services or ["persistent_notification.create"]
        prefix = "[Test] " if is_test else ""
        duration_part = f" ({episode['duration']})" if episode.get("duration") else ""
        payload = {
            "title": f"{prefix}Neue Folge: Wohnsinnig vernetzt",
            "message": f"{episode['title']}{duration_part}",
        }

        for svc in services:
            if "." in svc:
                domain, service = svc.split(".", 1)
            else:
                domain, service = "notify", svc
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

    async def async_send_test_notification(self) -> None:
        """Sendet eine Test-Benachrichtigung mit der aktuellsten Folge."""
        episodes = (self.data or {}).get("episodes", [])
        ep = (
            episodes[0]
            if episodes
            else {"title": "Test-Folge", "duration": "00:42", "pub_date": ""}
        )
        await self.async_send_notification(ep, is_test=True)

    async def async_send_feedback(
        self,
        message: str,
        sender: str = "",
        episode: str = "",
    ) -> None:
        """Sendet Hörer-Feedback an den konfigurierten Webhook-Endpunkt."""
        clean_msg = (message or "").strip()
        if not clean_msg:
            raise HomeAssistantError("Bitte gib zuerst eine Feedback-Nachricht ein.")

        if not self.feedback_webhook_url:
            raise HomeAssistantError(
                "Es ist noch keine Feedback-Webhook-URL konfiguriert. "
                "Trage in den Integrations-Optionen (oder in const.py) eine URL ein "
                "(z. B. Formspree, n8n oder Discord Webhook)."
            )

        clean_sender = (sender or "Home Assistant Hörer").strip()
        clean_episode = (episode or "").strip()

        if "discord.com/api/webhooks" in self.feedback_webhook_url:
            ep_line = f"\n**Folge:** {clean_episode}" if clean_episode else ""
            body = {
                "content": (
                    f"**Neues Podcast-Feedback (Home Assistant)**\n"
                    f"**Von:** {clean_sender}{ep_line}\n"
                    f"**Nachricht:**\n{clean_msg}"
                )
            }
        else:
            body = {
                "source": "Home Assistant Integration (Wohnsinnig vernetzt)",
                "sender": clean_sender,
                "episode": clean_episode,
                "message": clean_msg,
            }

        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                self.feedback_webhook_url,
                json=body,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status >= 400:
                    resp_text = await response.text()
                    raise HomeAssistantError(
                        f"Feedback konnte nicht gesendet werden (HTTP {response.status}): "
                        f"{resp_text[:120]}"
                    )
        except HomeAssistantError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                f"Verbindungsfehler beim Senden des Feedbacks: {err}"
            ) from err

        self.hass.bus.async_fire(
            EVENT_FEEDBACK_SENT,
            {
                "sender": clean_sender,
                "episode": clean_episode,
                "message": clean_msg,
            },
        )
