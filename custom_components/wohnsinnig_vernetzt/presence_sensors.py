"""Kombinierte Anwesenheitssensoren (Standort + WLAN + Bewegungsmelder-Timeout + Extras)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any
import uuid

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import (
    DEFAULT_PRESENCE_AWAY_DELAY,
    DEFAULT_PRESENCE_MOTION_TIMEOUT,
    DOMAIN,
    EVENT_PRESENCE_SENSOR_CHANGED,
    PRESENCE_COMBINE_ALL,
    PRESENCE_COMBINE_ANY,
)

_LOGGER = logging.getLogger(__name__)

LOCATION_DOMAINS = ("person", "device_tracker")
WIFI_DOMAINS = ("device_tracker", "sensor", "binary_sensor")
MOTION_DOMAINS = ("binary_sensor",)
EXTRA_DOMAINS = ("binary_sensor", "device_tracker", "person", "input_boolean", "switch")

_WIFI_DISCONNECTED_VALUES = {
    "",
    "not_home",
    "away",
    "off",
    "false",
    "0",
    "unknown",
    "unavailable",
    "none",
    "not connected",
    "<not connected>",
    "disconnected",
    "<unknown ssid>",
    "unknown ssid",
    "offline",
}

_MOTION_DEVICE_CLASSES = {"motion", "occupancy", "presence"}


def _utc_now() -> datetime:
    try:
        from homeassistant.util import dt as dt_util

        return dt_util.utcnow()
    except Exception:
        return datetime.now(timezone.utc)


def _to_local_hhmm(dt_val: datetime) -> str:
    try:
        from homeassistant.util import dt as dt_util

        return dt_util.as_local(dt_val).strftime("%H:%M")
    except Exception:
        return dt_val.strftime("%H:%M")


def _normalize_entity_list(raw: object, allowed_domains: tuple[str, ...]) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        items = [p.strip() for p in raw.split(",") if p.strip()]
    elif isinstance(raw, (list, tuple, set)):
        items = [str(p).strip() for p in raw if str(p).strip()]
    else:
        return []

    seen: set[str] = set()
    cleaned: list[str] = []
    for eid in items:
        if "." not in eid:
            continue
        dom = eid.split(".", 1)[0].lower()
        if dom not in allowed_domains:
            continue
        if f".{DOMAIN}" in eid:
            continue
        if eid not in seen:
            seen.add(eid)
            cleaned.append(eid)
    return cleaned


def normalize_ssid_list(raw: object) -> list[str]:
    """Normalisiert kommagetrennte oder als Liste übergebene WLAN-Namen (SSIDs)."""
    if not raw:
        return []
    if isinstance(raw, str):
        parts = [p.strip() for p in re.split(r"[,;\n]+", raw) if p.strip()]
    elif isinstance(raw, (list, tuple, set)):
        parts = [str(p).strip() for p in raw if str(p).strip()]
    else:
        return []

    seen: set[str] = set()
    out: list[str] = []
    for item in parts:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _safe_int(val: object, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(round(float(val)))))
    except (TypeError, ValueError):
        return default


def normalize_presence_sensor_def(
    raw: dict[str, Any], index: int = 1
) -> dict[str, Any] | None:
    """Validiert und normalisiert die Definition eines kombinierten Anwesenheitssensors."""
    if not isinstance(raw, dict):
        return None

    name = str(raw.get("name") or "").strip()
    if not name:
        name = f"Person {index}"

    sensor_id = str(raw.get("id") or "").strip()
    if not sensor_id:
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:20] or "person"
        sensor_id = f"{slug}_{uuid.uuid4().hex[:6]}"
    else:
        sensor_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", sensor_id).strip("_")[:48]
        if not sensor_id:
            sensor_id = f"ps_{uuid.uuid4().hex[:8]}"

    location_entities = _normalize_entity_list(
        raw.get("location_entities"), LOCATION_DOMAINS
    )
    wifi_entities = _normalize_entity_list(raw.get("wifi_entities"), WIFI_DOMAINS)
    motion_entities = _normalize_entity_list(raw.get("motion_entities"), MOTION_DOMAINS)
    extra_entities = _normalize_entity_list(raw.get("extra_entities"), EXTRA_DOMAINS)

    # Mindestens eine Quelle muss konfiguriert sein
    if not (location_entities or wifi_entities or motion_entities or extra_entities):
        return None

    combine_mode = str(raw.get("combine_mode") or PRESENCE_COMBINE_ANY).strip().lower()
    if combine_mode not in (PRESENCE_COMBINE_ANY, PRESENCE_COMBINE_ALL):
        combine_mode = PRESENCE_COMBINE_ANY

    home_wifi_ssids = normalize_ssid_list(raw.get("home_wifi_ssids"))
    motion_timeout_minutes = _safe_int(
        raw.get("motion_timeout_minutes"), DEFAULT_PRESENCE_MOTION_TIMEOUT, 0, 240
    )
    away_delay_minutes = _safe_int(
        raw.get("away_delay_minutes"), DEFAULT_PRESENCE_AWAY_DELAY, 0, 120
    )

    return {
        "id": sensor_id,
        "name": name[:64],
        "enabled": bool(raw.get("enabled", True)),
        "combine_mode": combine_mode,
        "location_entities": location_entities,
        "wifi_entities": wifi_entities,
        "home_wifi_ssids": home_wifi_ssids,
        "motion_entities": motion_entities,
        "motion_timeout_minutes": motion_timeout_minutes,
        "extra_entities": extra_entities,
        "away_delay_minutes": away_delay_minutes,
        "include_in_anyone_home": bool(raw.get("include_in_anyone_home", True)),
    }


def normalize_presence_sensor_defs(raw: object) -> list[dict[str, Any]]:
    """Normalisiert eine geordnete Liste beliebig vieler Anwesenheitssensoren."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(raw, start=1):
        norm = normalize_presence_sensor_def(item, index=idx)
        if norm is None:
            continue
        if norm["id"] in seen_ids:
            norm["id"] = f"{norm['id'][:40]}_{idx}"
        seen_ids.add(norm["id"])
        result.append(norm)
    return result


def _friendly(hass: HomeAssistant, entity_id: str) -> str:
    st = hass.states.get(entity_id)
    if st and st.attributes.get("friendly_name"):
        return str(st.attributes["friendly_name"]).strip()
    return entity_id


def _state_timestamp_utc(state_obj: Any) -> datetime | None:
    ts = getattr(state_obj, "last_changed", None) or getattr(state_obj, "last_updated", None)
    if not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def evaluate_wifi_entity(state_obj: Any, home_ssids: list[str]) -> tuple[bool, str]:
    """Prüft, ob ein WLAN-Tracker, Companion-App-WLAN-Sensor oder Binary-Sensor verbunden ist."""
    if state_obj is None:
        return False, "unbekannt"
    eid = state_obj.entity_id
    dom = eid.split(".", 1)[0].lower()
    raw = str(state_obj.state or "").strip()
    low = raw.lower()

    if dom == "device_tracker":
        is_home = low == "home"
        return is_home, "im WLAN" if is_home else "nicht im WLAN"

    if dom == "binary_sensor":
        is_on = low == "on"
        return is_on, "verbunden" if is_on else "getrennt"

    # sensor.* (z. B. Companion App sensor.handy_wifi_connection)
    if low in _WIFI_DISCONNECTED_VALUES:
        return False, "nicht verbunden"

    if home_ssids:
        ssid_lows = {s.lower() for s in home_ssids}
        if low in ssid_lows:
            return True, f"WLAN „{raw}“"
        return False, f"anderes WLAN („{raw}“)"

    # Keine SSID-Filter gesetzt -> jeder aktive SSID-Name zählt als verbunden
    return True, f"WLAN „{raw}“"


def get_presence_sensor_candidates(
    hass: HomeAssistant,
) -> dict[str, Any]:
    """Sammelt automatisch alle relevanten Standort-, WLAN-, Bewegungs- und Zusatz-Entitäten."""
    location_items: list[dict[str, Any]] = []
    wifi_items: list[dict[str, Any]] = []
    motion_items: list[dict[str, Any]] = []
    extra_items: list[dict[str, Any]] = []
    detected_ssids: list[str] = []
    seen_ssids: set[str] = set()

    all_states = []
    for _dom in ("person", "device_tracker", "sensor", "binary_sensor", "input_boolean", "switch"):
        all_states.extend(hass.states.async_all(_dom))
    for st in all_states:
        eid = st.entity_id
        if f".{DOMAIN}" in eid:
            continue
        attrs = st.attributes or {}
        if attrs.get("restored") is True:
            continue

        dom = eid.split(".", 1)[0].lower()
        dc = str(attrs.get("device_class") or "").lower()
        friendly = str(attrs.get("friendly_name") or eid).strip()
        low_blob = f"{eid} {friendly}".lower()
        state_val = str(st.state or "").strip()

        if dom in ("person", "device_tracker"):
            tier = 0 if dom == "person" else 1
            location_items.append(
                {
                    "entity_id": eid,
                    "domain": dom,
                    "name": friendly,
                    "state": state_val,
                    "tier": tier,
                }
            )

        # WLAN-Kandidaten: Router-Tracker, Companion-App WiFi-Sensoren, Ping/WLAN Binary-Sensoren
        is_wifi_sensor = dom == "sensor" and any(
            k in low_blob for k in ("wifi", "wi_fi", "wlan", "ssid")
        )
        is_wifi_tracker = dom == "device_tracker"
        is_wifi_binary = dom == "binary_sensor" and (
            dc == "connectivity"
            or any(k in low_blob for k in ("wifi", "wlan", "ping", "handy", "phone", "iphone", "galaxy"))
        )
        if is_wifi_sensor or is_wifi_tracker or is_wifi_binary:
            tier = 0 if is_wifi_sensor else (1 if is_wifi_tracker else 2)
            wifi_items.append(
                {
                    "entity_id": eid,
                    "domain": dom,
                    "name": friendly,
                    "state": state_val,
                    "tier": tier,
                }
            )
            if is_wifi_sensor and state_val.lower() not in _WIFI_DISCONNECTED_VALUES:
                if state_val.lower() not in seen_ssids:
                    seen_ssids.add(state_val.lower())
                    detected_ssids.append(state_val)

        # Bewegungsmelder / Präsenzmelder
        if dom == "binary_sensor":
            is_motion = dc in _MOTION_DEVICE_CLASSES or any(
                k in low_blob
                for k in ("motion", "beweg", "occupancy", "präsenz", "praesenz", "presence", "pir")
            )
            tier = 0 if is_motion else 1
            motion_items.append(
                {
                    "entity_id": eid,
                    "domain": dom,
                    "name": friendly,
                    "state": state_val,
                    "device_class": dc,
                    "tier": tier,
                }
            )

        # Zusatz-Entitäten
        if dom in EXTRA_DOMAINS:
            extra_items.append(
                {
                    "entity_id": eid,
                    "domain": dom,
                    "name": friendly,
                    "state": state_val,
                }
            )

    location_items.sort(key=lambda x: (x["tier"], x["name"].lower(), x["entity_id"]))
    wifi_items.sort(key=lambda x: (x["tier"], x["name"].lower(), x["entity_id"]))
    motion_items.sort(key=lambda x: (x["tier"], x["name"].lower(), x["entity_id"]))
    extra_items.sort(key=lambda x: (x["name"].lower(), x["entity_id"]))

    return {
        "location_candidates": location_items,
        "wifi_candidates": wifi_items,
        "motion_candidates": motion_items,
        "extra_candidates": extra_items,
        "detected_ssids": detected_ssids,
    }


class PresenceSensorsManager:
    """Verwaltet beliebig viele kombinierte Anwesenheitssensoren inkl. Bewegungs-Timeout & Abwesend-Verzögerung."""

    def __init__(
        self,
        hass: HomeAssistant,
        on_update: Callable[[], None],
        on_persist: Callable[[], Any],
        sensor_defs: list[dict[str, Any]] | None = None,
    ) -> None:
        self.hass = hass
        self._on_update = on_update
        self._on_persist = on_persist

        self.sensor_defs: list[dict[str, Any]] = normalize_presence_sensor_defs(
            sensor_defs or []
        )

        # Laufzeit-Zustände
        self._last_motion_ts: dict[str, float] = {}  # {motion_entity_id: utc_ts}
        self._away_pending_since: dict[str, float] = {}  # {sensor_id: utc_ts}
        self._sensor_states: dict[str, dict[str, Any]] = {}  # {sensor_id: eval_dict}
        self._unsub_state: CALLBACK_TYPE | None = None
        self._unsub_interval: CALLBACK_TYPE | None = None
        self._unsub_exact_timer: CALLBACK_TYPE | None = None

    async def _persist(self) -> None:
        res = self._on_persist()
        if asyncio.iscoroutine(res):
            await res

    def get_all_watched_entities(self) -> list[str]:
        watched: set[str] = set()
        for sdef in self.sensor_defs:
            watched.update(sdef["location_entities"])
            watched.update(sdef["wifi_entities"])
            watched.update(sdef["motion_entities"])
            watched.update(sdef["extra_entities"])
        return sorted(watched)

    def _seed_motion_timestamps(self, persisted_motion: dict[str, float] | None) -> None:
        now_ts = _utc_now().timestamp()
        if isinstance(persisted_motion, dict):
            for eid, ts in persisted_motion.items():
                if isinstance(ts, (int, float)) and ts <= now_ts + 60:
                    self._last_motion_ts[str(eid)] = float(ts)

        # Alle aktuell aktiven oder kürzlich geänderten Bewegungsmelder einlesen
        all_motion_eids: set[str] = set()
        for sdef in self.sensor_defs:
            all_motion_eids.update(sdef["motion_entities"])

        for eid in all_motion_eids:
            st = self.hass.states.get(eid)
            if st is None:
                continue
            if st.state == "on":
                self._last_motion_ts[eid] = now_ts
            elif st.state == "off" and eid not in self._last_motion_ts:
                ch_dt = _state_timestamp_utc(st)
                if ch_dt is not None:
                    self._last_motion_ts[eid] = ch_dt.timestamp()

    def _attach_listeners(self) -> None:
        self._detach_listeners()
        watched = self.get_all_watched_entities()
        if not watched:
            return

        async def _on_state_changed(event: Event) -> None:
            eid = event.data.get("entity_id")
            new_st = event.data.get("new_state")
            old_st = event.data.get("old_state")
            now_ts = _utc_now().timestamp()

            # Bewegungsmelder-Zeitstempel präzise mitschneiden (beim AN gehen und beim Übergang AN -> AUS)
            if eid and new_st is not None:
                if new_st.state == "on":
                    self._last_motion_ts[eid] = now_ts
                elif old_st is not None and old_st.state == "on" and new_st.state == "off":
                    self._last_motion_ts[eid] = now_ts

            await self.async_evaluate()

        self._unsub_state = async_track_state_change_event(
            self.hass, watched, _on_state_changed
        )

        async def _on_tick(_now: datetime) -> None:
            await self.async_evaluate()

        self._unsub_interval = async_track_time_interval(
            self.hass, _on_tick, timedelta(seconds=30)
        )

    def _detach_listeners(self) -> None:
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None
        if self._unsub_exact_timer is not None:
            self._unsub_exact_timer()
            self._unsub_exact_timer = None

    def _schedule_next_deadline(self, next_deadline_ts: float | None) -> None:
        if self._unsub_exact_timer is not None:
            self._unsub_exact_timer()
            self._unsub_exact_timer = None
        if next_deadline_ts is None:
            return

        fire_dt = datetime.fromtimestamp(next_deadline_ts + 0.5, tz=timezone.utc)

        async def _on_deadline(_now: datetime) -> None:
            self._unsub_exact_timer = None
            await self.async_evaluate()

        self._unsub_exact_timer = async_track_point_in_utc_time(
            self.hass, _on_deadline, fire_dt
        )

    async def async_initialize(
        self,
        persisted_motion_ts: dict[str, float] | None = None,
        persisted_states: dict[str, bool] | None = None,
    ) -> None:
        """Initialisiert Bewegungs-Zeitstempel, Vorzustände und Listener."""
        self._seed_motion_timestamps(persisted_motion_ts)
        if isinstance(persisted_states, dict):
            for sdef in self.sensor_defs:
                sid = sdef["id"]
                if isinstance(persisted_states.get(sid), bool):
                    self._sensor_states[sid] = {"is_present": persisted_states[sid]}

        self._attach_listeners()
        await self.async_evaluate(fire_events=False)

    def _evaluate_single(
        self, sdef: dict[str, Any], now_ts: float
    ) -> tuple[dict[str, Any], float | None]:
        """Wertet alle konfigurierten Gruppen eines einzelnen Anwesenheitssensors aus."""
        sid = sdef["id"]
        next_deadline: float | None = None
        active_reasons: list[str] = []
        away_reasons: list[str] = []
        group_results: list[bool] = []

        # 1. Standort / GPS / Person
        loc_present: bool | None = None
        loc_details: list[str] = []
        if sdef["location_entities"]:
            loc_present = False
            for eid in sdef["location_entities"]:
                st = self.hass.states.get(eid)
                val = str(st.state or "unbekannt").strip() if st else "unbekannt"
                fname = _friendly(self.hass, eid)
                is_home = val.lower() == "home"
                loc_details.append(f"{fname}: {'Zuhause' if is_home else val}")
                if is_home:
                    loc_present = True
                    active_reasons.append(f"📍 {fname}")
            if not loc_present:
                away_reasons.append("Standort weg")
            group_results.append(loc_present)

        # 2. WLAN / Netzwerk
        wifi_present: bool | None = None
        wifi_details: list[str] = []
        if sdef["wifi_entities"]:
            wifi_present = False
            for eid in sdef["wifi_entities"]:
                st = self.hass.states.get(eid)
                fname = _friendly(self.hass, eid)
                ok, desc = evaluate_wifi_entity(st, sdef["home_wifi_ssids"])
                wifi_details.append(f"{fname}: {desc}")
                if ok:
                    wifi_present = True
                    active_reasons.append(f"📶 {fname}")
            if not wifi_present:
                away_reasons.append("nicht im WLAN")
            group_results.append(wifi_present)

        # 3. Bewegungsmelder mit einstellbarem Timeout (Zeit X ohne Bewegung)
        motion_present: bool | None = None
        motion_details: list[str] = []
        last_motion_ago_min: float | None = None
        motion_timeout_sec = sdef["motion_timeout_minutes"] * 60.0

        if sdef["motion_entities"]:
            motion_present = False
            newest_motion_ts: float | None = None

            for eid in sdef["motion_entities"]:
                st = self.hass.states.get(eid)
                fname = _friendly(self.hass, eid)
                if st is not None and st.state == "on":
                    self._last_motion_ts[eid] = now_ts
                    motion_present = True
                    newest_motion_ts = now_ts
                    motion_details.append(f"{fname}: Bewegung aktiv")
                    active_reasons.append(f"🏃 {fname}")
                else:
                    last_ts = self._last_motion_ts.get(eid)
                    if last_ts is None and st is not None:
                        ch_dt = _state_timestamp_utc(st)
                        if ch_dt is not None:
                            last_ts = ch_dt.timestamp()
                            self._last_motion_ts[eid] = last_ts

                    if last_ts is not None:
                        if newest_motion_ts is None or last_ts > newest_motion_ts:
                            newest_motion_ts = last_ts
                        elapsed = max(0.0, now_ts - last_ts)
                        ago_min = int(elapsed // 60)
                        if motion_timeout_sec > 0 and elapsed < motion_timeout_sec:
                            motion_present = True
                            rem_min = max(1, int((motion_timeout_sec - elapsed + 59) // 60))
                            motion_details.append(
                                f"{fname}: vor {ago_min} Min (aktiv noch ~{rem_min} Min)"
                            )
                            active_reasons.append(f"🏃 {fname} (vor {ago_min} Min)")
                            exp_ts = last_ts + motion_timeout_sec
                            if next_deadline is None or exp_ts < next_deadline:
                                next_deadline = exp_ts
                        else:
                            motion_details.append(f"{fname}: ruhig seit {ago_min} Min")
                    else:
                        motion_details.append(f"{fname}: keine Bewegung")

            if newest_motion_ts is not None:
                last_motion_ago_min = round(max(0.0, (now_ts - newest_motion_ts) / 60.0), 1)
            if not motion_present:
                away_reasons.append(f"keine Bewegung ≥ {sdef['motion_timeout_minutes']} Min")
            group_results.append(motion_present)

        # 4. Optionale Zusatz-Entitäten
        extra_present: bool | None = None
        extra_details: list[str] = []
        if sdef["extra_entities"]:
            extra_present = False
            for eid in sdef["extra_entities"]:
                st = self.hass.states.get(eid)
                val = str(st.state or "unbekannt").strip().lower() if st else "unbekannt"
                fname = _friendly(self.hass, eid)
                is_on = val in ("home", "on", "true")
                extra_details.append(f"{fname}: {'aktiv' if is_on else val}")
                if is_on:
                    extra_present = True
                    active_reasons.append(f"⚡ {fname}")
            if not extra_present:
                away_reasons.append("Zusatz inaktiv")
            group_results.append(extra_present)

        # Kombinationslogik anwenden
        if not group_results:
            raw_present = False
        elif sdef["combine_mode"] == PRESENCE_COMBINE_ALL:
            raw_present = all(group_results)
        else:
            # Standard (Sicherheits-/Alarmanlagen-Modus): Zuhause sobald IRGENDEINE Quelle anwesend meldet!
            raw_present = any(group_results)

        prev_entry = self._sensor_states.get(sid)
        prev_present = prev_entry.get("is_present") if isinstance(prev_entry, dict) else None

        # Abwesend-Verzögerung (away_delay_minutes) gegen kurzfristige Funk-/WLAN-Aussetzer
        away_delay_sec = sdef["away_delay_minutes"] * 60.0
        waiting_for_away = False
        away_in_min = 0

        if raw_present:
            self._away_pending_since.pop(sid, None)
            final_present = True
        else:
            if prev_present is True and away_delay_sec > 0:
                pending_since = self._away_pending_since.get(sid)
                if pending_since is None:
                    self._away_pending_since[sid] = now_ts
                    pending_since = now_ts
                elapsed_away = now_ts - pending_since
                if elapsed_away < away_delay_sec:
                    final_present = True
                    waiting_for_away = True
                    away_in_min = max(1, int((away_delay_sec - elapsed_away + 59) // 60))
                    exp_ts = pending_since + away_delay_sec
                    if next_deadline is None or exp_ts < next_deadline:
                        next_deadline = exp_ts
                else:
                    self._away_pending_since.pop(sid, None)
                    final_present = False
            else:
                self._away_pending_since.pop(sid, None)
                final_present = False

        # Verständlichen Grund zusammenbauen
        if waiting_for_away:
            reason_text = f"Wechselt in ~{away_in_min} Min auf Abwesend ({', '.join(away_reasons)})"
        elif final_present:
            reason_text = ", ".join(active_reasons[:3]) if active_reasons else "Zuhause"
        else:
            reason_text = (
                f"Abwesend ({', '.join(away_reasons)})"
                if away_reasons
                else "Alle Quellen abwesend"
            )

        result = {
            "id": sid,
            "name": sdef["name"],
            "is_present": final_present,
            "raw_present": raw_present,
            "status_text": "Zuhause" if final_present else "Abwesend",
            "reason": reason_text,
            "combine_mode": sdef["combine_mode"],
            "include_in_anyone_home": sdef["include_in_anyone_home"],
            "location_present": loc_present,
            "location_details": loc_details,
            "wifi_present": wifi_present,
            "wifi_details": wifi_details,
            "motion_present": motion_present,
            "motion_details": motion_details,
            "motion_timeout_minutes": sdef["motion_timeout_minutes"],
            "last_motion_ago_min": last_motion_ago_min,
            "extra_present": extra_present,
            "extra_details": extra_details,
            "away_delay_minutes": sdef["away_delay_minutes"],
            "waiting_for_away": waiting_for_away,
            "away_in_min": away_in_min,
            "last_changed": (
                prev_entry.get("last_changed", "")
                if isinstance(prev_entry, dict) and prev_present == final_present
                else _to_local_hhmm(_utc_now())
            ),
        }
        return result, next_deadline

    async def async_evaluate(self, fire_events: bool = True) -> dict[str, Any]:
        """Bewertet alle konfigurierten Anwesenheitssensoren sofort."""
        now_ts = _utc_now().timestamp()
        earliest_deadline: float | None = None
        state_changed = False

        for sdef in self.sensor_defs:
            sid = sdef["id"]
            if not sdef.get("enabled", True):
                continue
            prev_present = (self._sensor_states.get(sid) or {}).get("is_present")
            res, deadline = self._evaluate_single(sdef, now_ts)
            self._sensor_states[sid] = res

            if deadline is not None and (
                earliest_deadline is None or deadline < earliest_deadline
            ):
                earliest_deadline = deadline

            if prev_present is not None and prev_present != res["is_present"]:
                state_changed = True
                if fire_events:
                    self.hass.bus.async_fire(
                        EVENT_PRESENCE_SENSOR_CHANGED,
                        {
                            "sensor_id": sid,
                            "name": res["name"],
                            "is_present": res["is_present"],
                            "status": res["status_text"],
                            "reason": res["reason"],
                        },
                    )

        self._schedule_next_deadline(earliest_deadline)
        if state_changed:
            await self._persist()
        self._on_update()
        return self.get_overview_snapshot()

    def get_sensor_state(self, sensor_id: str) -> dict[str, Any]:
        if sensor_id in self._sensor_states:
            return self._sensor_states[sensor_id]
        for sdef in self.sensor_defs:
            if sdef["id"] == sensor_id:
                res, _ = self._evaluate_single(sdef, _utc_now().timestamp())
                return res
        return {
            "id": sensor_id,
            "name": sensor_id,
            "is_present": False,
            "status_text": "Abwesend",
            "reason": "Nicht konfiguriert",
        }

    def get_persisted_state_payload(self) -> dict[str, Any]:
        return {
            "motion_ts": dict(self._last_motion_ts),
            "states": {
                sid: bool(st.get("is_present", False))
                for sid, st in self._sensor_states.items()
            },
        }

    def get_overview_snapshot(self) -> dict[str, Any]:
        """Liefert die Gesamtübersicht inkl. 'Jemand zuhause' für Sensor & Dashboard-Karte."""
        sensors_list: list[dict[str, Any]] = []
        home_names: list[str] = []
        away_names: list[str] = []
        included_states: list[bool] = []

        for sdef in self.sensor_defs:
            if not sdef.get("enabled", True):
                continue
            st = self.get_sensor_state(sdef["id"])
            sensors_list.append(st)
            if st["is_present"]:
                home_names.append(st["name"])
            else:
                away_names.append(st["name"])
            if sdef.get("include_in_anyone_home", True):
                included_states.append(bool(st["is_present"]))

        anyone_home = any(included_states) if included_states else False
        total = len(sensors_list)

        if total == 0:
            status_text = "Keine Sensoren"
        elif home_names:
            names_preview = ", ".join(home_names[:3])
            if len(home_names) > 3:
                names_preview += f" (+{len(home_names) - 3})"
            status_text = f"{len(home_names)}/{total} Zuhause ({names_preview})"
        else:
            status_text = "Alle abwesend"

        return {
            "status": status_text,
            "anyone_home": anyone_home,
            "sensors_count": total,
            "home_count": len(home_names),
            "away_count": len(away_names),
            "home_names": home_names,
            "away_names": away_names,
            "sensors": sensors_list,
        }

    async def async_shutdown(self) -> None:
        self._detach_listeners()
