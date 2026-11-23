"""DataUpdateCoordinator für RSS-Feed, Wiedergabe und Benachrichtigungen."""

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
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BROWSER_TARGET,
    DOMAIN,
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


def extract_spotify_show_id(raw: str | None) -> str:
    """Extrahiert eine Spotify-Show-ID aus URL, URI oder direkter ID."""
    if not raw:
        return ""
    val = raw.strip()
    if not val:
        return ""
    match = re.search(r"spotify\.com/show/([A-Za-z0-9]+)", val)
    if match:
        return match.group(1)
    match = re.search(r"spotify:show:([A-Za-z0-9]+)", val)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{15,30}", val):
        return val
    return ""


def _parse_duration_seconds(raw: str | None) -> int | None:
    """Konvertiert itunes:duration in Sekunden für HA-Media-Player."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    parts = raw.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    return None


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
    """Parst den Podcast-RSS-Feed unter Beibehaltung der originalen Tracking-URLs."""
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("Ungültiger RSS-Feed: Kein <channel>-Element gefunden.")

    podcast_title = (channel.findtext("title") or "Wohnsinnig vernetzt").strip()
    podcast_desc = _clean_html(channel.findtext("description"))
    podcast_link = (channel.findtext("link") or "").strip()

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
        raw_dur = item.findtext(f"{{{ITUNES_NS}}}duration")
        duration = _format_duration(raw_dur)
        duration_sec = _parse_duration_seconds(raw_dur)
        description = _clean_html(item.findtext("description"))
        episode_link = (item.findtext("link") or "").strip()

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
                "duration_sec": duration_sec,
                "description": description[:400],
                "audio_url": audio_url,
                "link": episode_link,
                "image": ep_image,
            }
        )

    return {
        "title": podcast_title,
        "description": podcast_desc,
        "link": podcast_link,
        "image": podcast_image,
        "episodes": episodes,
    }


class WohnsinnigVernetztCoordinator(DataUpdateCoordinator[dict]):
    """Verwaltet RSS-Feed, Benachrichtigungen und Media-Player-Wiedergabe."""

    def __init__(
        self,
        hass: HomeAssistant,
        rss_url: str,
        notify_services: list[str],
        scan_interval_minutes: int,
        logo_url: str = "",
        spotify_show_url: str = "",
        default_target: str = BROWSER_TARGET,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval_minutes),
        )
        self.rss_url = rss_url
        self.logo_url = logo_url.strip()
        self.spotify_show_url = spotify_show_url.strip()
        self.spotify_show_id = extract_spotify_show_id(self.spotify_show_url)
        self.notify_services = notify_services

        self._store: Store[dict] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._seen_guids: set[str] | None = None
        self.notifications_enabled: bool = True
        self.selected_episode_guid: str | None = None
        self.target_entity: str = default_target or BROWSER_TARGET
        self.playback_state: str = "idle"
        self.play_command_id: int = 0
        self.last_command_action: str = "idle"
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
            if isinstance(stored.get("target_entity"), str) and stored["target_entity"]:
                self.target_entity = stored["target_entity"]
        self._state_loaded = True

    async def _async_save_state(self) -> None:
        await self._store.async_save(
            {
                "guids": list(self._seen_guids or []),
                "notifications_enabled": self.notifications_enabled,
                "selected_episode_guid": self.selected_episode_guid,
                "target_entity": self.target_entity,
            }
        )

    async def async_set_notifications_enabled(self, enabled: bool) -> None:
        """Aktiviert oder deaktiviert Benachrichtigungen persistent."""
        self.notifications_enabled = enabled
        await self._async_save_state()
        self.async_update_listeners()

    async def async_set_target_entity(self, target_entity: str) -> None:
        """Speichert das ausgewählte Wiedergabe-Gerät."""
        self.target_entity = target_entity or BROWSER_TARGET
        await self._async_save_state()
        self.async_update_listeners()

    def get_episodes(self) -> list[dict]:
        """Liefert alle geladenen Episoden."""
        return (self.data or {}).get("episodes", [])

    def get_selected_episode(self) -> dict | None:
        """Gibt die aktuell ausgewählte Episode (oder die neueste) zurück."""
        episodes = self.get_episodes()
        if not episodes:
            return None
        if self.selected_episode_guid:
            for ep in episodes:
                if ep["guid"] == self.selected_episode_guid:
                    return ep
        return episodes[0]

    def get_selected_index(self) -> int:
        """Index der aktuell gewählten Episode."""
        episodes = self.get_episodes()
        if not episodes:
            return 0
        if self.selected_episode_guid:
            for idx, ep in enumerate(episodes):
                if ep["guid"] == self.selected_episode_guid:
                    return idx
        return 0

    async def async_play_episode(
        self, guid: str | None = None, from_browser: bool = False
    ) -> None:
        """Wählt eine Episode aus und startet sofort die Wiedergabe."""
        episodes = self.get_episodes()
        if not episodes:
            return

        ep = None
        if guid:
            for item in episodes:
                if item["guid"] == guid or item["audio_url"] == guid:
                    ep = item
                    break
        if ep is None:
            ep = self.get_selected_episode() or episodes[0]

        self.selected_episode_guid = ep["guid"]
        self.playback_state = "playing"

        if self.target_entity != BROWSER_TARGET:
            await self._async_play_on_ha_target(ep)
        elif not from_browser:
            self.play_command_id += 1
            self.last_command_action = "play"

        await self._async_save_state()
        self.async_update_listeners()

    async def async_pause(self, from_browser: bool = False) -> None:
        """Pausiert die laufende Wiedergabe."""
        self.playback_state = "paused"
        if self.target_entity != BROWSER_TARGET:
            await self._async_call_target_service("media_pause")
        elif not from_browser:
            self.play_command_id += 1
            self.last_command_action = "pause"
        self.async_update_listeners()

    async def async_resume(self, from_browser: bool = False) -> None:
        """Setzt die Wiedergabe fort oder startet die aktuelle Folge."""
        if self.playback_state == "idle":
            await self.async_play_episode(
                self.selected_episode_guid, from_browser=from_browser
            )
            return

        self.playback_state = "playing"
        if self.target_entity != BROWSER_TARGET:
            await self._async_call_target_service("media_play")
        elif not from_browser:
            self.play_command_id += 1
            self.last_command_action = "play"
        self.async_update_listeners()

    async def async_stop(self, from_browser: bool = False) -> None:
        """Stoppt die Wiedergabe."""
        self.playback_state = "idle"
        if self.target_entity != BROWSER_TARGET:
            await self._async_call_target_service("media_stop")
        elif not from_browser:
            self.play_command_id += 1
            self.last_command_action = "stop"
        self.async_update_listeners()

    async def async_next_episode(self) -> None:
        """Springt zur nächstälteren Folge in der Liste und spielt sie ab."""
        episodes = self.get_episodes()
        if not episodes:
            return
        idx = self.get_selected_index()
        next_idx = (idx + 1) % len(episodes)
        await self.async_play_episode(episodes[next_idx]["guid"])

    async def async_previous_episode(self) -> None:
        """Springt zur neueren Folge in der Liste und spielt sie ab."""
        episodes = self.get_episodes()
        if not episodes:
            return
        idx = self.get_selected_index()
        prev_idx = (idx - 1) % len(episodes)
        await self.async_play_episode(episodes[prev_idx]["guid"])

    async def async_sync_browser_state(
        self, state: str, guid: str | None = None
    ) -> None:
        """Synchronisiert Statusänderungen aus der Dashboard-Karte ohne Rückkopplung."""
        if guid:
            self.selected_episode_guid = guid
        if state in ("playing", "paused", "idle"):
            self.playback_state = state
        await self._async_save_state()
        self.async_update_listeners()

    async def _async_play_on_ha_target(self, episode: dict) -> None:
        """Sendet die originale RSS-Audio-URL direkt an den gewählten HA-Lautsprecher."""
        target = self.target_entity
        if not target or target == BROWSER_TARGET:
            return
        thumb = episode.get("image") or (self.data or {}).get("image") or ""
        service_data = {
            "entity_id": target,
            "media_content_id": episode["audio_url"],
            "media_content_type": "music",
            "extra": {
                "title": episode["title"],
                "thumb": thumb,
                "metadata": {
                    "metadataType": 3,
                    "title": episode["title"],
                    "artist": "Wohnsinnig vernetzt",
                    "images": [{"url": thumb}] if thumb else [],
                },
            },
        }
        try:
            await self.hass.services.async_call(
                "media_player", "play_media", service_data, blocking=False
            )
        except Exception as err:
            _LOGGER.warning(
                "Wiedergabe auf %s fehlgeschlagen: %s", target, err
            )

    async def _async_call_target_service(self, service: str) -> None:
        target = self.target_entity
        if not target or target == BROWSER_TARGET:
            return
        try:
            await self.hass.services.async_call(
                "media_player", service, {"entity_id": target}, blocking=False
            )
        except Exception as err:
            _LOGGER.warning(
                "Dienst media_player.%s auf %s fehlgeschlagen: %s",
                service,
                target,
                err,
            )

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
        episodes = self.get_episodes()
        ep = (
            episodes[0]
            if episodes
            else {"title": "Test-Folge", "duration": "00:42", "pub_date": ""}
        )
        await self.async_send_notification(ep, is_test=True)
