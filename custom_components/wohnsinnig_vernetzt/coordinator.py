"""DataUpdateCoordinator für RSS-Feed, Blueprint-Updates, Infografiken, Eilmeldungen & Systemcheck."""

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

from .alerts import parse_alerts_payload, sync_alert_repair_issues
from .blueprints import (
    HTTP_HEADERS,
    annotate_installed_status,
    build_safe_filename,
    compute_yaml_hash,
    extract_blueprints_from_js_blob,
    match_episode_infographic,
    normalize_blueprint_url,
    parse_blueprints_catalog_with_hints,
    parse_infographics_from_html,
    validate_blueprint_yaml,
    write_blueprint_file,
)
from .const import (
    ACTION_MARK_SEEN,
    ACTION_PLAY_LATEST,
    BROWSER_TARGET,
    DEFAULT_ALERTS_URL,
    DEFAULT_BATTERY_THRESHOLD,
    DEFAULT_BLUEPRINTS_URL,
    DOMAIN,
    EVENT_ALERT_RECEIVED,
    EVENT_BLUEPRINT_IMPORTED,
    EVENT_NEW_EPISODE,
    EVENT_SYSTEMCHECK_COMPLETED,
    NOTIFY_ALL_MOBILE_APPS,
    NOTIFY_NONE,
    SIGNAL_NEW_EPISODE,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .notify_helpers import get_mobile_app_services
from .systemcheck import run_systemcheck

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

    rss_podcast_image = ""
    itunes_img = channel.find(f"{{{ITUNES_NS}}}image")
    if itunes_img is not None and itunes_img.attrib.get("href"):
        rss_podcast_image = itunes_img.attrib["href"]
    else:
        img_url = channel.findtext("image/url")
        if img_url:
            rss_podcast_image = img_url.strip()

    podcast_image = override_logo_url.strip() or rss_podcast_image

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

        ep_itunes_img = item.find(f"{{{ITUNES_NS}}}image")
        rss_ep_image = (
            ep_itunes_img.attrib["href"]
            if ep_itunes_img is not None and ep_itunes_img.attrib.get("href")
            else rss_podcast_image
        )
        ep_image = podcast_image if override_logo_url.strip() else rss_ep_image

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
                "rss_image": rss_ep_image,
            }
        )

    # Episodennummern chronologisch zuweisen (älteste = 1, neueste = Anzahl Folgen, z. B. 23)
    total_episodes = len(episodes)
    for pos, ep in enumerate(episodes):
        ep["episode_number"] = total_episodes - pos

    return {
        "title": podcast_title,
        "description": podcast_desc,
        "link": podcast_link,
        "image": podcast_image,
        "rss_image": rss_podcast_image,
        "episodes": episodes,
    }


class WohnsinnigVernetztCoordinator(DataUpdateCoordinator[dict]):
    """Zentraler Coordinator für Podcast, Blueprint-Updates, Infografiken, Eilmeldungen & Systemcheck."""

    def __init__(
        self,
        hass: HomeAssistant,
        rss_url: str,
        notify_services: list[str],
        scan_interval_minutes: int,
        logo_url: str = "",
        spotify_show_url: str = "",
        blueprints_url: str = DEFAULT_BLUEPRINTS_URL,
        alerts_url: str = DEFAULT_ALERTS_URL,
        battery_threshold: int = DEFAULT_BATTERY_THRESHOLD,
        default_target: str = BROWSER_TARGET,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval_minutes),
        )
        self.rss_url = rss_url
        self.blueprints_url = (blueprints_url or DEFAULT_BLUEPRINTS_URL).strip()
        self.alerts_url = (alerts_url or DEFAULT_ALERTS_URL).strip()
        self.logo_url = logo_url.strip()
        self.spotify_show_url = spotify_show_url.strip()
        self.spotify_show_id = extract_spotify_show_id(self.spotify_show_url)
        self.battery_threshold = int(battery_threshold or DEFAULT_BATTERY_THRESHOLD)
        self._config_notify_services = list(notify_services)
        self.notify_services = list(notify_services)

        self._store: Store[dict] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._seen_guids: set[str] | None = None
        self._seen_alert_ids: set[str] = set()
        self._remote_bp_cache: dict[str, dict] = {}
        self._tracked_issue_ids: set[str] = set()

        self.notifications_enabled: bool = True
        self.alerts_enabled: bool = True
        self.selected_episode_guid: str | None = None
        self.acknowledged_latest_guid: str | None = None
        self.acknowledged_latest_title: str = ""
        self.selected_blueprint_id: str | None = None
        self.target_entity: str = default_target or BROWSER_TARGET
        self.playback_state: str = "idle"
        self.play_command_id: int = 0
        self.last_command_action: str = "idle"
        self.blueprints_last_error: str | None = None
        self.systemcheck_result: dict = {
            "status": "Ausstehend",
            "total_issues": 0,
            "unavailable_count": 0,
            "low_battery_count": 0,
            "orphaned_count": 0,
            "battery_threshold": self.battery_threshold,
            "checked_at": "",
            "unavailable_entities": [],
            "low_battery_entities": [],
            "orphaned_entities": [],
        }
        self._state_loaded: bool = False

    async def _async_load_state(self) -> None:
        if self._state_loaded:
            return
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            if isinstance(stored.get("guids"), list):
                self._seen_guids = set(stored["guids"])
            if isinstance(stored.get("seen_alert_ids"), list):
                self._seen_alert_ids = set(stored["seen_alert_ids"])
            if isinstance(stored.get("remote_bp_cache"), dict):
                self._remote_bp_cache = stored["remote_bp_cache"]
            if isinstance(stored.get("notifications_enabled"), bool):
                self.notifications_enabled = stored["notifications_enabled"]
            if isinstance(stored.get("alerts_enabled"), bool):
                self.alerts_enabled = stored["alerts_enabled"]
            if isinstance(stored.get("selected_episode_guid"), str):
                self.selected_episode_guid = stored["selected_episode_guid"]
            if isinstance(stored.get("acknowledged_latest_guid"), str):
                self.acknowledged_latest_guid = stored["acknowledged_latest_guid"]
            if isinstance(stored.get("acknowledged_latest_title"), str):
                self.acknowledged_latest_title = stored["acknowledged_latest_title"]
            if isinstance(stored.get("selected_blueprint_id"), str):
                self.selected_blueprint_id = stored["selected_blueprint_id"]
            if isinstance(stored.get("target_entity"), str) and stored["target_entity"]:
                self.target_entity = stored["target_entity"]
            stored_last_cfg = stored.get("last_config_notify_services")
            stored_notify = stored.get("notify_services")
            if (
                isinstance(stored_notify, list)
                and stored_last_cfg == self._config_notify_services
            ):
                self.notify_services = [str(s) for s in stored_notify if s]
        self._state_loaded = True

    async def _async_save_state(self) -> None:
        await self._store.async_save(
            {
                "guids": list(self._seen_guids or []),
                "seen_alert_ids": list(self._seen_alert_ids),
                "remote_bp_cache": self._remote_bp_cache,
                "notifications_enabled": self.notifications_enabled,
                "alerts_enabled": self.alerts_enabled,
                "selected_episode_guid": self.selected_episode_guid,
                "acknowledged_latest_guid": self.acknowledged_latest_guid,
                "acknowledged_latest_title": self.acknowledged_latest_title,
                "selected_blueprint_id": self.selected_blueprint_id,
                "target_entity": self.target_entity,
                "notify_services": list(self.notify_services),
                "last_config_notify_services": list(self._config_notify_services),
            }
        )

    async def async_set_notifications_enabled(self, enabled: bool) -> None:
        """Aktiviert oder deaktiviert Benachrichtigungen persistent."""
        self.notifications_enabled = enabled
        await self._async_save_state()
        self.async_update_listeners()

    async def async_set_alerts_enabled(self, enabled: bool) -> None:
        """Aktiviert oder deaktiviert Smart-Home-Eilmeldungen inkl. Repair-Issues."""
        self.alerts_enabled = enabled
        self._tracked_issue_ids = sync_alert_repair_issues(
            self.hass,
            self.get_alerts(),
            self.alerts_enabled,
            self._tracked_issue_ids,
        )
        await self._async_save_state()
        self.async_update_listeners()

    async def async_set_notify_target(self, service_id: str) -> None:
        """Speichert das ausgewählte Handy bzw. Benachrichtigungsziel persistent."""
        if not service_id or service_id == NOTIFY_NONE:
            self.notify_services = []
        else:
            self.notify_services = [service_id]
        await self._async_save_state()
        self.async_update_listeners()

    async def async_set_target_entity(self, target_entity: str) -> None:
        """Speichert das ausgewählte Wiedergabe-Gerät."""
        self.target_entity = target_entity or BROWSER_TARGET
        await self._async_save_state()
        self.async_update_listeners()

    async def async_set_selected_blueprint(self, bp_id: str) -> None:
        """Speichert den im Dropdown gewählten Blueprint."""
        self.selected_blueprint_id = bp_id
        await self._async_save_state()
        self.async_update_listeners()

    def get_episodes(self) -> list[dict]:
        return (self.data or {}).get("episodes", [])

    def get_blueprints(self) -> list[dict]:
        return (self.data or {}).get("blueprints", [])

    def get_infographics(self) -> list[dict]:
        return (self.data or {}).get("infographics", [])

    def get_alerts(self) -> list[dict]:
        return (self.data or {}).get("alerts", [])

    def get_current_infographic(self, episode: dict | None = None) -> dict | None:
        ep = episode or self.get_selected_episode()
        return match_episode_infographic(ep, self.get_infographics())

    def get_public_push_image(self, episode: dict | None = None) -> str:
        """Liefert eine öffentlich per HTTPS erreichbare Bild-URL für Push-Vorschauen."""
        ep = episode or self.get_selected_episode()
        info = self.get_current_infographic(ep)
        if info and info.get("url", "").startswith("https://"):
            return info["url"]
        if ep and ep.get("rss_image", "").startswith("https://"):
            return ep["rss_image"]
        rss_img = (self.data or {}).get("rss_image", "")
        if rss_img.startswith("https://"):
            return rss_img
        return ""

    def get_selected_blueprint(self) -> dict | None:
        blueprints = self.get_blueprints()
        if not blueprints:
            return None
        if self.selected_blueprint_id:
            for bp in blueprints:
                if bp["id"] == self.selected_blueprint_id:
                    return bp
        return blueprints[0]

    def get_selected_episode(self) -> dict | None:
        episodes = self.get_episodes()
        if not episodes:
            return None
        if self.selected_episode_guid:
            for ep in episodes:
                if ep["guid"] == self.selected_episode_guid:
                    return ep
        return episodes[0]

    def get_selected_index(self) -> int:
        episodes = self.get_episodes()
        if not episodes:
            return 0
        if self.selected_episode_guid:
            for idx, ep in enumerate(episodes):
                if ep["guid"] == self.selected_episode_guid:
                    return idx
        return 0

    def has_newer_episode(self) -> bool:
        episodes = self.get_episodes()
        if not episodes:
            return False
        latest = episodes[0]
        if self.acknowledged_latest_guid:
            return latest["guid"] != self.acknowledged_latest_guid
        return False

    def newer_episodes_count(self) -> int:
        episodes = self.get_episodes()
        if not episodes or not self.acknowledged_latest_guid:
            return 0
        count = 0
        for ep in episodes:
            if ep["guid"] == self.acknowledged_latest_guid:
                break
            count += 1
        return count

    async def async_mark_latest_episode_seen(self) -> None:
        """Markiert die aktuell neueste Folge als bekannt/gesehen (Sensor -> NEIN)."""
        episodes = self.get_episodes()
        if not episodes:
            return
        latest = episodes[0]
        self.acknowledged_latest_guid = latest["guid"]
        self.acknowledged_latest_title = latest["title"]
        await self._async_save_state()
        self.async_update_listeners()

    async def async_run_systemcheck(self, notify: bool = False) -> dict:
        """Führt den lokalen Smart-Home-Systemcheck aus und aktualisiert den Sensor."""
        result = run_systemcheck(self.hass, battery_threshold=self.battery_threshold)
        self.systemcheck_result = result
        self.hass.bus.async_fire(EVENT_SYSTEMCHECK_COMPLETED, result)
        self.async_update_listeners()

        if notify:
            summary_lines = [
                f"Status: {result['status']} (Stand: {result['checked_at']})",
                f"• Nicht verfügbar: {result['unavailable_count']}",
                f"• Schwache Batterien (≤ {result['battery_threshold']} %): {result['low_battery_count']}",
                f"• Verwaiste Entitäten: {result['orphaned_count']}",
            ]
            if result["low_battery_entities"]:
                summary_lines.append(
                    "Batterien: " + ", ".join(result["low_battery_entities"][:5])
                )
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Wohnsinnig vernetzt – Systemcheck",
                    "message": "\n".join(summary_lines),
                },
                blocking=False,
            )

        return result

    async def _async_check_blueprint_updates(
        self, session: aiohttp.ClientSession, blueprints: list[dict]
    ) -> list[dict]:
        """Prüft für alle lokal installierten Blueprints per Hash/ETag auf Updates."""
        cache_dirty = False
        updated: list[dict] = []

        for bp in blueprints:
            if not bp.get("installed"):
                updated.append(bp)
                continue

            url = bp["url"]
            cached = self._remote_bp_cache.get(url, {})
            headers = dict(HTTP_HEADERS)
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                headers["If-Modified-Since"] = cached["last_modified"]

            remote_hash = cached.get("sha256", "")
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=15),
                    headers=headers,
                ) as resp:
                    if resp.status == 304 and remote_hash:
                        pass
                    elif resp.status == 200:
                        yaml_text = await resp.text(errors="replace")
                        remote_hash = compute_yaml_hash(yaml_text)
                        new_entry = {
                            "sha256": remote_hash,
                            "etag": resp.headers.get("ETag", ""),
                            "last_modified": resp.headers.get("Last-Modified", ""),
                        }
                        if new_entry != cached:
                            self._remote_bp_cache[url] = new_entry
                            cache_dirty = True
            except (aiohttp.ClientError, TimeoutError):
                pass

            local_hash = bp.get("local_hash", "")
            update_available = bool(
                local_hash and remote_hash and local_hash != remote_hash
            )
            updated.append(
                {
                    **bp,
                    "remote_hash": remote_hash,
                    "update_available": update_available,
                }
            )

        if cache_dirty:
            await self._async_save_state()

        return updated

    async def _async_fetch_website_assets(
        self, session: aiohttp.ClientSession
    ) -> tuple[list[dict], list[dict]]:
        """Lädt wohnsinnigvernetzt.de einmalig und extrahiert Blueprints + Infografiken."""
        if not self.blueprints_url:
            self.blueprints_last_error = "Keine Blueprints-URL konfiguriert."
            return [], []

        self.blueprints_last_error = None
        try:
            async with session.get(
                self.blueprints_url,
                timeout=aiohttp.ClientTimeout(total=20),
                headers=HTTP_HEADERS,
            ) as response:
                response.raise_for_status()
                raw_text = await response.text(errors="replace")
                final_url = str(response.url)
        except (aiohttp.ClientError, TimeoutError) as err:
            self.blueprints_last_error = f"Abruf fehlgeschlagen: {err}"
            _LOGGER.warning(
                "Webseite %s konnte nicht geladen werden: %s",
                self.blueprints_url,
                err,
            )
            prev = self.data or {}
            return prev.get("blueprints", []), prev.get("infographics", [])

        try:
            parsed, ext_scripts, subpages = await self.hass.async_add_executor_job(
                parse_blueprints_catalog_with_hints, raw_text, final_url
            )
            infographics = await self.hass.async_add_executor_job(
                parse_infographics_from_html, raw_text, final_url
            )

            if not parsed and ext_scripts:
                seen_urls: set[str] = set()
                for script_url in ext_scripts[:6]:
                    try:
                        async with session.get(
                            script_url,
                            timeout=aiohttp.ClientTimeout(total=15),
                            headers=HTTP_HEADERS,
                        ) as s_resp:
                            if s_resp.status == 200:
                                js_text = await s_resp.text(errors="replace")
                                found_js = await self.hass.async_add_executor_job(
                                    extract_blueprints_from_js_blob,
                                    js_text,
                                    final_url,
                                    seen_urls,
                                )
                                parsed.extend(found_js)
                    except (aiohttp.ClientError, TimeoutError):
                        continue

            if not parsed and subpages:
                for sub_url in subpages[:3]:
                    try:
                        async with session.get(
                            sub_url,
                            timeout=aiohttp.ClientTimeout(total=15),
                            headers=HTTP_HEADERS,
                        ) as sub_resp:
                            if sub_resp.status == 200:
                                sub_text = await sub_resp.text(errors="replace")
                                sub_bps, _, _ = await self.hass.async_add_executor_job(
                                    parse_blueprints_catalog_with_hints,
                                    sub_text,
                                    str(sub_resp.url),
                                )
                                if sub_bps:
                                    parsed.extend(sub_bps)
                                    break
                    except (aiohttp.ClientError, TimeoutError):
                        continue

            if not parsed:
                self.blueprints_last_error = (
                    f"Keine .yaml-Links auf {final_url} erkannt "
                    f"({len(raw_text)} Bytes geladen)."
                )
                _LOGGER.warning("%s", self.blueprints_last_error)

            annotated = await self.hass.async_add_executor_job(
                annotate_installed_status, parsed, self.hass.config.config_dir
            )
            checked = await self._async_check_blueprint_updates(session, annotated)
            return checked, infographics
        except Exception as err:
            self.blueprints_last_error = f"Parse-Fehler: {err}"
            _LOGGER.warning("Fehler beim Parsen von Website-Assets: %s", err)
            prev = self.data or {}
            return prev.get("blueprints", []), prev.get("infographics", [])

    async def _async_ensure_episode_infographic(
        self,
        session: aiohttp.ClientSession,
        episode_number: int,
        infographics: list[dict],
    ) -> list[dict]:
        """Prüft direkt auf <episode_number>.jpeg/.jpg/.png, falls index.html noch nicht aktualisiert wurde."""
        if any(item.get("episode_number") == episode_number for item in infographics):
            return infographics
        if not self.blueprints_url:
            return infographics

        base_dir = self.blueprints_url.rstrip("/") + "/"
        for ext in ("jpeg", "jpg", "png"):
            candidate_url = f"{base_dir}{episode_number}.{ext}"
            try:
                async with session.head(
                    candidate_url,
                    timeout=aiohttp.ClientTimeout(total=8),
                    headers=HTTP_HEADERS,
                    allow_redirects=True,
                ) as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    if resp.status == 200 and ctype.startswith("image/"):
                        found = {
                            "episode_number": episode_number,
                            "filename": f"{episode_number}.{ext}",
                            "url": str(resp.url),
                            "title": f"Folge {episode_number} – Infografik",
                        }
                        return sorted(
                            [found, *infographics],
                            key=lambda item: item["episode_number"],
                            reverse=True,
                        )
            except (aiohttp.ClientError, TimeoutError):
                continue
        return infographics

    async def _async_fetch_alerts(self, session: aiohttp.ClientSession) -> list[dict]:
        """Lädt optionale Smart-Home-Eilmeldungen (leise bei 404, kein Log-Spam)."""
        if not self.alerts_url:
            return []
        try:
            async with session.get(
                self.alerts_url,
                timeout=aiohttp.ClientTimeout(total=15),
                headers=HTTP_HEADERS,
            ) as response:
                if response.status == 404:
                    return []
                response.raise_for_status()
                raw_text = await response.text(errors="replace")
        except (aiohttp.ClientError, TimeoutError):
            return (self.data or {}).get("alerts", [])

        return parse_alerts_payload(raw_text)

    async def _handle_alerts(self, alerts: list[dict]) -> None:
        """Synchronisiert Repair-Issues und schickt Push-Meldungen für neue Eilmeldungen."""
        self._tracked_issue_ids = sync_alert_repair_issues(
            self.hass, alerts, self.alerts_enabled, self._tracked_issue_ids
        )

        if not self.alerts_enabled or not alerts:
            return

        new_alerts = [a for a in alerts if a["id"] not in self._seen_alert_ids]
        if not new_alerts:
            return

        for alert in new_alerts:
            self._seen_alert_ids.add(alert["id"])
            self.hass.bus.async_fire(EVENT_ALERT_RECEIVED, alert)
            if self.notifications_enabled:
                await self._async_send_alert_notification(alert)

        await self._async_save_state()

    def _reset_ha_blueprint_cache(self, bp_domain: str) -> None:
        try:
            bp_data = self.hass.data.get("blueprint")
            if isinstance(bp_data, dict):
                domain_bps = bp_data.get(bp_domain)
                if domain_bps is not None and hasattr(domain_bps, "async_reset_cache"):
                    domain_bps.async_reset_cache()
        except Exception as err:
            _LOGGER.debug("Blueprint-Cache-Reset übersprungen: %s", err)

    async def async_import_blueprint(
        self, url: str | None = None, blueprint_id: str | None = None
    ) -> dict:
        """Lädt eine Blueprint-YAML herunter, validiert sie und speichert sie direkt in HA."""
        target_bp = None
        if blueprint_id:
            for bp in self.get_blueprints():
                if bp["id"] == blueprint_id or bp["filename"] == blueprint_id:
                    target_bp = bp
                    break
        elif url:
            norm_check = normalize_blueprint_url(url, self.blueprints_url)
            for bp in self.get_blueprints():
                if bp["url"] == norm_check or bp["url"] == url:
                    target_bp = bp
                    break
        else:
            target_bp = self.get_selected_blueprint()

        raw_url = url or (target_bp["url"] if target_bp else "")
        resolved_url = normalize_blueprint_url(raw_url, self.blueprints_url)
        if not resolved_url:
            raise HomeAssistantError("Keine gültige Blueprint-URL angegeben.")

        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                resolved_url,
                timeout=aiohttp.ClientTimeout(total=20),
                headers=HTTP_HEADERS,
            ) as response:
                response.raise_for_status()
                yaml_text = await response.text(errors="replace")
                etag = response.headers.get("ETag", "")
                last_mod = response.headers.get("Last-Modified", "")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                f"Blueprint konnte nicht heruntergeladen werden: {err}"
            ) from err

        try:
            bp_domain, bp_name = await self.hass.async_add_executor_job(
                validate_blueprint_yaml, yaml_text
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

        filename = (
            target_bp["filename"]
            if target_bp
            else build_safe_filename(resolved_url, bp_name or "")
        )

        rel_path = await self.hass.async_add_executor_job(
            write_blueprint_file,
            self.hass.config.config_dir,
            bp_domain,
            filename,
            yaml_text,
        )

        new_hash = compute_yaml_hash(yaml_text)
        self._remote_bp_cache[resolved_url] = {
            "sha256": new_hash,
            "etag": etag,
            "last_modified": last_mod,
        }

        self._reset_ha_blueprint_cache(bp_domain)

        if self.data and "blueprints" in self.data:
            refreshed = []
            for bp in self.data["blueprints"]:
                if bp["url"] == resolved_url:
                    bp = {**bp, "remote_hash": new_hash}
                refreshed.append(bp)
            self.data["blueprints"] = await self.hass.async_add_executor_job(
                annotate_installed_status,
                refreshed,
                self.hass.config.config_dir,
            )

        await self._async_save_state()

        result = {
            "title": (target_bp["title"] if target_bp else None) or bp_name or filename,
            "filename": filename,
            "domain": bp_domain,
            "path": rel_path,
            "url": resolved_url,
        }

        self.hass.bus.async_fire(EVENT_BLUEPRINT_IMPORTED, result)
        self.async_update_listeners()
        return result

    async def async_import_all_blueprints(self) -> list[dict]:
        """Importiert alle Blueprints von wohnsinnigvernetzt.de auf einmal."""
        blueprints = self.get_blueprints()
        if not blueprints:
            raise HomeAssistantError(
                "Aktuell wurden keine Blueprints auf der Webseite gefunden."
            )

        imported: list[dict] = []
        errors: list[str] = []
        for bp in blueprints:
            try:
                res = await self.async_import_blueprint(
                    url=bp["url"], blueprint_id=bp["id"]
                )
                imported.append(res)
            except HomeAssistantError as err:
                errors.append(f"{bp['title']}: {err}")

        if errors and not imported:
            raise HomeAssistantError("; ".join(errors))

        if errors:
            _LOGGER.warning(
                "Einige Blueprints konnten nicht importiert werden: %s",
                "; ".join(errors),
            )

        return imported

    async def async_update_outdated_blueprints(self) -> list[dict]:
        """Aktualisiert alle lokal installierten Blueprints, für die ein Update vorliegt."""
        outdated = [
            bp
            for bp in self.get_blueprints()
            if bp.get("installed") and bp.get("update_available")
        ]
        if not outdated:
            return []

        updated: list[dict] = []
        for bp in outdated:
            res = await self.async_import_blueprint(
                url=bp["url"], blueprint_id=bp["id"]
            )
            updated.append(res)
        return updated

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
        if episodes and ep["guid"] == episodes[0]["guid"]:
            self.acknowledged_latest_guid = ep["guid"]
            self.acknowledged_latest_title = ep["title"]

        if self.target_entity != BROWSER_TARGET:
            await self._async_play_on_ha_target(ep)
        elif not from_browser:
            self.play_command_id += 1
            self.last_command_action = "play"

        await self._async_save_state()
        self.async_update_listeners()

    async def async_play_latest_episode(self) -> None:
        """Startet gezielt die allerneueste Episode (z. B. über Push-Action-Button)."""
        episodes = self.get_episodes()
        if episodes:
            await self.async_play_episode(episodes[0]["guid"])

    async def async_pause(self, from_browser: bool = False) -> None:
        self.playback_state = "paused"
        if self.target_entity != BROWSER_TARGET:
            await self._async_call_target_service("media_pause")
        elif not from_browser:
            self.play_command_id += 1
            self.last_command_action = "pause"
        self.async_update_listeners()

    async def async_resume(self, from_browser: bool = False) -> None:
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
        self.playback_state = "idle"
        if self.target_entity != BROWSER_TARGET:
            await self._async_call_target_service("media_stop")
        elif not from_browser:
            self.play_command_id += 1
            self.last_command_action = "stop"
        self.async_update_listeners()

    async def async_next_episode(self) -> None:
        episodes = self.get_episodes()
        if not episodes:
            return
        idx = self.get_selected_index()
        next_idx = (idx + 1) % len(episodes)
        await self.async_play_episode(episodes[next_idx]["guid"])

    async def async_previous_episode(self) -> None:
        episodes = self.get_episodes()
        if not episodes:
            return
        idx = self.get_selected_index()
        prev_idx = (idx - 1) % len(episodes)
        await self.async_play_episode(episodes[prev_idx]["guid"])

    async def async_sync_browser_state(
        self, state: str, guid: str | None = None
    ) -> None:
        if guid:
            self.selected_episode_guid = guid
            episodes = self.get_episodes()
            if state == "playing" and episodes and guid == episodes[0]["guid"]:
                self.acknowledged_latest_guid = episodes[0]["guid"]
                self.acknowledged_latest_title = episodes[0]["title"]
        if state in ("playing", "paused", "idle"):
            self.playback_state = state
        await self._async_save_state()
        self.async_update_listeners()

    async def _async_play_on_ha_target(self, episode: dict) -> None:
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
            _LOGGER.warning("Wiedergabe auf %s fehlgeschlagen: %s", target, err)

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
        """Lädt RSS-Feed, Blueprints, Infografiken, Eilmeldungen und führt den Systemcheck aus."""
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

        blueprints, infographics = await self._async_fetch_website_assets(session)
        if data["episodes"]:
            latest_num = data["episodes"][0].get("episode_number")
            if isinstance(latest_num, int) and latest_num > 0:
                infographics = await self._async_ensure_episode_infographic(
                    session, latest_num, infographics
                )
        alerts = await self._async_fetch_alerts(session)

        data["blueprints"] = blueprints
        data["infographics"] = infographics
        data["alerts"] = alerts

        if data["episodes"] and not self.selected_episode_guid:
            self.selected_episode_guid = data["episodes"][0]["guid"]

        if blueprints and not self.selected_blueprint_id:
            self.selected_blueprint_id = blueprints[0]["id"]

        if self.hass.is_running:
            self.systemcheck_result = run_systemcheck(
                self.hass, battery_threshold=self.battery_threshold
            )

        await self._handle_new_episodes(data["episodes"], data)
        await self._handle_alerts(alerts)
        return data

    async def _handle_new_episodes(
        self, episodes: list[dict], fresh_data: dict | None = None
    ) -> None:
        if not episodes:
            return

        if self.acknowledged_latest_guid is None and episodes:
            matched_prev = None
            prev_state = self.hass.states.get("sensor.wohnsinnig_vernetzt_neueste_folge")
            if prev_state and prev_state.state not in (
                "unknown",
                "unavailable",
                "Keine Folgen gefunden",
            ):
                for ep in episodes:
                    if ep["title"][:255] == prev_state.state:
                        matched_prev = ep
                        break
            baseline = matched_prev or episodes[0]
            self.acknowledged_latest_guid = baseline["guid"]
            self.acknowledged_latest_title = baseline["title"]

        if self._seen_guids is None:
            self._seen_guids = {ep["guid"] for ep in episodes}
            await self._async_save_state()
            return

        new_episodes = [ep for ep in episodes if ep["guid"] not in self._seen_guids]
        if not new_episodes:
            await self._async_save_state()
            return

        for ep in reversed(new_episodes):
            self._seen_guids.add(ep["guid"])
            self.hass.bus.async_fire(EVENT_NEW_EPISODE, ep)
            async_dispatcher_send(self.hass, SIGNAL_NEW_EPISODE, ep)
            if self.notifications_enabled:
                await self.async_send_notification(
                    ep, is_test=False, data_override=fresh_data
                )

        await self._async_save_state()

    def _resolve_active_notify_services(self) -> list[str]:
        resolved: list[str] = []
        for svc in self.notify_services:
            if not svc or svc == NOTIFY_NONE:
                continue
            if svc == NOTIFY_ALL_MOBILE_APPS:
                for m_svc in get_mobile_app_services(self.hass):
                    if m_svc not in resolved:
                        resolved.append(m_svc)
            elif svc not in resolved:
                resolved.append(svc)
        return resolved

    async def async_send_notification(
        self,
        episode: dict,
        is_test: bool = False,
        data_override: dict | None = None,
    ) -> None:
        """Sendet eine interaktive Push-Benachrichtigung mit Infografik & Action-Buttons."""
        services = self._resolve_active_notify_services()
        if not services:
            if is_test:
                services = ["persistent_notification.create"]
            else:
                return

        prefix = "[Test] " if is_test else ""
        duration_part = f" ({episode['duration']})" if episode.get("duration") else ""
        title = f"{prefix}🎙️ Neue Folge: Wohnsinnig vernetzt"
        message = f"{episode['title']}{duration_part}"
        ep_link = episode.get("link") or "https://www.wohnsinnigvernetzt.de"

        source_data = data_override or self.data or {}
        matched_info = match_episode_infographic(
            episode, source_data.get("infographics", [])
        )
        image_url = ""
        if matched_info and matched_info.get("url", "").startswith("https://"):
            image_url = matched_info["url"]
        elif episode.get("rss_image", "").startswith("https://"):
            image_url = episode["rss_image"]
        elif source_data.get("rss_image", "").startswith("https://"):
            image_url = source_data["rss_image"]

        for svc in services:
            if "." in svc:
                domain, service = svc.split(".", 1)
            else:
                domain, service = "notify", svc

            payload: dict = {
                "title": title,
                "message": message,
            }
            if domain == "notify" and service.startswith("mobile_app_"):
                mobile_data: dict = {
                    "clickAction": ep_link,
                    "url": ep_link,
                    "tag": "wohnsinnig_vernetzt_new_episode",
                    "actions": [
                        {
                            "action": ACTION_PLAY_LATEST,
                            "title": "▶️ Folge abspielen",
                        },
                        {
                            "action": ACTION_MARK_SEEN,
                            "title": "✅ Als gesehen markieren",
                        },
                    ],
                }
                if image_url:
                    mobile_data["image"] = image_url
                    mobile_data["attachment"] = {"url": image_url}
                payload["data"] = mobile_data

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

    async def _async_send_alert_notification(self, alert: dict) -> None:
        """Schickt eine Push-Meldung für eine neue Smart-Home-Eilmeldung."""
        services = self._resolve_active_notify_services()
        if not services:
            return

        icon_prefix = "🚨" if alert["severity"] == "critical" else "⚠️" if alert["severity"] == "warning" else "ℹ️"
        title = f"{icon_prefix} Niels & Patrick warnen: {alert['title']}"
        message = alert["message"] or alert["title"]
        url = alert.get("url") or "https://www.wohnsinnigvernetzt.de/"

        for svc in services:
            if "." in svc:
                domain, service = svc.split(".", 1)
            else:
                domain, service = "notify", svc

            payload: dict = {"title": title, "message": message}
            if domain == "notify" and service.startswith("mobile_app_"):
                payload["data"] = {
                    "clickAction": url,
                    "url": url,
                    "tag": f"wohnsinnig_vernetzt_alert_{alert['id']}",
                }
            try:
                await self.hass.services.async_call(
                    domain, service, payload, blocking=False
                )
            except Exception as err:
                _LOGGER.warning(
                    "Eilmeldung über %s.%s fehlgeschlagen: %s", domain, service, err
                )

    async def async_send_test_notification(self) -> None:
        """Sendet eine Test-Benachrichtigung inkl. Infografik & Action-Buttons."""
        episodes = self.get_episodes()
        ep = (
            episodes[0]
            if episodes
            else {"title": "Test-Folge", "duration": "00:42", "pub_date": ""}
        )
        await self.async_send_notification(ep, is_test=True)
