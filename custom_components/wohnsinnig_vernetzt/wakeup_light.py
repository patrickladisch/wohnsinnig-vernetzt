"""Wake-Up Light & Sonnenaufgangs-Steuerung mit Handy-Wecker (Next Alarm) & Automations-Pause."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone
import logging
from pathlib import Path
from typing import Any

import yaml

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)

from .const import (
    DEFAULT_WAKEUP_ALARM_ENTITY,
    DEFAULT_WAKEUP_AUTO_OFF_MINUTES,
    DEFAULT_WAKEUP_AUTO_PAUSE,
    DEFAULT_WAKEUP_DAYS,
    DEFAULT_WAKEUP_DURATION,
    DEFAULT_WAKEUP_MODE,
    DEFAULT_WAKEUP_SUNRISE_COLOR,
    DEFAULT_WAKEUP_TIME,
    DOMAIN,
    EVENT_WAKEUP_AUTO_OFF,
    EVENT_WAKEUP_CANCELLED,
    EVENT_WAKEUP_COMPLETED,
    EVENT_WAKEUP_STARTED,
    WAKEUP_ALARM_MANUAL,
    WAKEUP_DAYS_DAILY,
    WAKEUP_DAYS_WEEKEND,
    WAKEUP_DAYS_WORKDAYS,
    WAKEUP_MODE_REACH_100,
    WAKEUP_MODE_START_AT,
)

_LOGGER = logging.getLogger(__name__)

_SAFETY_EXCLUDE_KEYWORDS = (
    "rauch",
    "smoke",
    "feuer",
    "fire",
    "wasser",
    "water",
    "alarm",
    "notfall",
    "emergency",
    "sirene",
    "siren",
    "leck",
    "leak",
    "gas",
    "co2",
    "einbruch",
    DOMAIN,
)


class _SafeYamlLoader(yaml.SafeLoader):
    """YAML-Loader, der HA-Tags wie !secret, !input oder !include ignoriert."""


def _ignore_tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return f"!{suffix} {loader.construct_scalar(node)}"
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


_SafeYamlLoader.add_multi_constructor("!", _ignore_tag)


def _local_now() -> datetime:
    try:
        from homeassistant.util import dt as dt_util

        return dt_util.now()
    except Exception:
        return datetime.now().astimezone()


def _as_local(dt_val: datetime) -> datetime:
    try:
        from homeassistant.util import dt as dt_util

        return dt_util.as_local(dt_val)
    except Exception:
        return dt_val.astimezone()


def _as_utc(dt_val: datetime) -> datetime:
    try:
        from homeassistant.util import dt as dt_util

        return dt_util.as_utc(dt_val)
    except Exception:
        return dt_val.astimezone(timezone.utc)


def normalize_wakeup_lights(raw: object) -> list[str]:
    """Bereinigt ausgewählte Lampen (nur light.* Entitäten)."""
    if not raw:
        return []
    if isinstance(raw, str):
        items = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, (list, tuple, set)):
        items = [str(part).strip() for part in raw if str(part).strip()]
    else:
        return []

    seen: set[str] = set()
    cleaned: list[str] = []
    for eid in items:
        if eid.startswith("light.") and f".{DOMAIN}" not in eid and eid not in seen:
            seen.add(eid)
            cleaned.append(eid)
    return cleaned


def normalize_wakeup_automations(raw: object) -> list[str]:
    """Bereinigt eine Liste von automation.* Entitäten."""
    if not raw:
        return []
    if isinstance(raw, str):
        items = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, (list, tuple, set)):
        items = [str(part).strip() for part in raw if str(part).strip()]
    else:
        return []

    seen: set[str] = set()
    cleaned: list[str] = []
    for eid in items:
        if eid.startswith("automation.") and eid not in seen:
            seen.add(eid)
            cleaned.append(eid)
    return cleaned


def normalize_wakeup_alarm_entity(raw: object) -> str:
    """Bereinigt eine ausgewählte Wecker-Entität (sensor.* oder input_datetime.*)."""
    val = str(raw or "").strip()
    if not val or val == WAKEUP_ALARM_MANUAL:
        return WAKEUP_ALARM_MANUAL
    if val.startswith(("sensor.", "input_datetime.")):
        return val
    return WAKEUP_ALARM_MANUAL


def parse_wakeup_time(raw: str | time | None, fallback: str = DEFAULT_WAKEUP_TIME) -> time:
    """Parst 'HH:MM' oder datetime.time sicher."""
    if isinstance(raw, time):
        return time(hour=raw.hour, minute=raw.minute, second=0)
    text = str(raw or fallback).strip()
    parts = text.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour=hour, minute=minute, second=0)
    except (ValueError, IndexError):
        pass
    fb = fallback.split(":")
    return time(hour=int(fb[0]), minute=int(fb[1]), second=0)


def parse_alarm_sensor_datetime(
    state_obj: Any, now_local: datetime | None = None
) -> datetime | None:
    """Liest den nächsten Weckzeitpunkt aus einem Next-Alarm-Sensor oder input_datetime aus.

    Gibt ein lokales datetime-Objekt zurück oder None, wenn kein aktiver Wecker in der Zukunft steht.
    """
    if state_obj is None:
        return None

    now = now_local or _local_now()
    raw_state = str(getattr(state_obj, "state", "") or "").strip()
    attrs = getattr(state_obj, "attributes", {}) or {}
    entity_id = str(getattr(state_obj, "entity_id", "") or "")

    if not raw_state or raw_state.lower() in ("unavailable", "unknown", "none"):
        return None

    # 1. input_datetime (z. B. iOS Kurzbefehl / manueller Helfer)
    if entity_id.startswith("input_datetime."):
        has_date = bool(attrs.get("has_date"))
        has_time = bool(attrs.get("has_time", True))
        if not has_time:
            return None
        try:
            if has_date:
                dt_naive = datetime.fromisoformat(raw_state.replace(" ", "T"))
                alarm_dt = dt_naive.replace(tzinfo=now.tzinfo)
            else:
                t_val = parse_wakeup_time(raw_state)
                alarm_dt = now.replace(
                    hour=t_val.hour,
                    minute=t_val.minute,
                    second=0,
                    microsecond=0,
                )
                if alarm_dt <= now:
                    alarm_dt = alarm_dt + timedelta(days=1)
            return alarm_dt if alarm_dt > now else None
        except ValueError:
            return None

    # 2. ISO-8601 Timestamp-Sensor (Android Companion App next_alarm, Echo, Google Home, etc.)
    parsed_dt: datetime | None = None
    try:
        iso_str = raw_state.replace("Z", "+00:00")
        parsed_dt = datetime.fromisoformat(iso_str)
    except ValueError:
        parsed_dt = None

    # Fallback: Android Companion App Attribut 'Time in Milliseconds'
    if parsed_dt is None:
        ms_val = attrs.get("Time in Milliseconds")
        if isinstance(ms_val, (int, float)) and ms_val > 0:
            try:
                parsed_dt = datetime.fromtimestamp(float(ms_val) / 1000.0, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                parsed_dt = None

    if parsed_dt is None:
        return None

    if parsed_dt.tzinfo is None:
        alarm_local = parsed_dt.replace(tzinfo=now.tzinfo)
    else:
        alarm_local = _as_local(parsed_dt)

    if alarm_local <= now:
        return None
    return alarm_local


def _has_mobile_app_identifier(identifiers: object) -> bool:
    """Prüft sicher, ob ein Device-Identifier zu mobile_app gehört (ohne Tuple-Unpack-Crash)."""
    if not identifiers:
        return False
    for ident in identifiers:
        if isinstance(ident, (tuple, list)) and len(ident) >= 1 and ident[0] == "mobile_app":
            return True
    return False


def get_alarm_sensor_candidates(
    hass: HomeAssistant, current_entity: str = ""
) -> list[dict[str, Any]]:
    """Findet automatisch alle Handy-Wecker (Companion App next_alarm) sowie weitere Wecker-Sensoren.

    Sortiert Handys (mobile_app) ganz nach oben, gefolgt von sonstigen Next-Alarm-Sensoren
    und input_datetime-Helfern.
    """
    ent_reg = None
    dev_reg = None
    try:
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)
    except Exception:
        pass

    now = _local_now()
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    all_states = [
        *hass.states.async_all("sensor"),
        *hass.states.async_all("input_datetime"),
    ]

    for st in all_states:
        try:
            eid = st.entity_id
            if f".{DOMAIN}" in eid:
                continue
            attrs = st.attributes or {}
            if attrs.get("restored") is True:
                continue

            domain = eid.split(".", 1)[0]
            dc = str(attrs.get("device_class") or "").lower()
            friendly = str(attrs.get("friendly_name") or eid).strip()
            low_id = eid.lower()
            low_name = friendly.lower()

            reg_entry = ent_reg.async_get(eid) if ent_reg is not None else None
            platform = (reg_entry.platform or "").lower() if reg_entry else ""

            device_name = ""
            is_mobile_app = platform == "mobile_app"
            if reg_entry and reg_entry.device_id and dev_reg is not None:
                dev = dev_reg.async_get(reg_entry.device_id)
                if dev is not None:
                    device_name = (dev.name_by_user or dev.name or "").strip()
                    if _has_mobile_app_identifier(getattr(dev, "identifiers", None)):
                        is_mobile_app = True

            tier: int | None = None
            is_alarm_named = (
                "next_alarm" in low_id
                or "naechster_wecker" in low_id
                or "alarm" in low_id
                or "wecker" in low_name
                or "alarm" in low_name
            )
            if domain == "sensor" and (dc == "timestamp" or "next_alarm" in low_id or "naechster_wecker" in low_id):
                if is_mobile_app and is_alarm_named:
                    tier = 0  # Handy-Wecker (Companion App)
                elif is_alarm_named:
                    tier = 1  # Sonstiger Next-Alarm-Sensor (z. B. Echo, Google Home)
            elif domain == "input_datetime" and bool(attrs.get("has_time", True)):
                if any(k in low_id or k in low_name for k in ("wecker", "alarm", "wake", "aufwach")):
                    tier = 2  # Expliziter Wecker-Helfer (z. B. iOS Shortcut)
                else:
                    tier = 3  # Allgemeiner Zeit-Helfer

            if tier is None and eid == current_entity:
                tier = 4
            if tier is None:
                continue

            alarm_dt = parse_alarm_sensor_datetime(st, now_local=now)
            alarm_preview = alarm_dt.strftime("%d.%m. %H:%M") if alarm_dt else "Kein Wecker"

            if tier == 0:
                short_name = (
                    device_name
                    or friendly.replace("Next alarm", "").replace("Nächster Wecker", "").strip(" -:")
                    or eid
                )
                display_label = f"📱 {short_name} ({alarm_preview})"
                compact_name = f"📱 {short_name}"
            elif tier == 1:
                short_name = device_name or friendly
                display_label = f"⏰ {short_name} ({alarm_preview})"
                compact_name = f"⏰ {short_name}"
            else:
                short_name = friendly
                display_label = f"📅 {short_name} ({alarm_preview})"
                compact_name = f"📅 {short_name}"

            candidates.append(
                {
                    "entity_id": eid,
                    "tier": tier,
                    "name": short_name,
                    "friendly_name": friendly,
                    "display_label": display_label,
                    "compact_name": compact_name,
                    "alarm_preview": alarm_preview,
                    "has_alarm": alarm_dt is not None,
                    "is_mobile_app": is_mobile_app,
                }
            )
            seen.add(eid)
        except Exception as err:
            _LOGGER.debug("Wecker-Kandidat übersprungen: %s", err)
            continue

    if current_entity and current_entity not in seen:
        candidates.append(
            {
                "entity_id": current_entity,
                "tier": 5,
                "name": current_entity,
                "friendly_name": current_entity,
                "display_label": f"⏰ {current_entity}",
                "compact_name": f"⏰ {current_entity}",
                "alarm_preview": "Nicht gefunden",
                "has_alarm": False,
                "is_mobile_app": False,
            }
        )

    candidates.sort(key=lambda item: (item["tier"], item["name"].lower(), item["entity_id"]))
    return candidates


def _weekday_matches(weekday_idx: int, rule: str) -> bool:
    """Prüft, ob ein Wochentag (0=Mo .. 6=So) zur gewählten Regel passt."""
    if rule == WAKEUP_DAYS_WORKDAYS:
        return 0 <= weekday_idx <= 4
    if rule == WAKEUP_DAYS_WEEKEND:
        return weekday_idx in (5, 6)
    return True


def compute_next_wakeup_window(
    now_local: datetime,
    mode: str,
    target_time: time,
    duration_minutes: int,
    weekdays: str = WAKEUP_DAYS_DAILY,
) -> tuple[datetime, datetime]:
    """Berechnet das nächste (start_dt, end_dt)-Zeitfenster in lokaler Zeitzone (manuelle Uhrzeit)."""
    dur = timedelta(minutes=max(1, min(120, int(duration_minutes))))
    base_date = now_local.date()

    for day_offset in range(0, 10):
        cand_date = base_date + timedelta(days=day_offset)
        cand_dt = now_local.replace(
            year=cand_date.year,
            month=cand_date.month,
            day=cand_date.day,
            hour=target_time.hour,
            minute=target_time.minute,
            second=0,
            microsecond=0,
        )

        if mode == WAKEUP_MODE_START_AT:
            start_dt = cand_dt
            end_dt = cand_dt + dur
            ref_weekday = start_dt.weekday()
        else:
            end_dt = cand_dt
            start_dt = cand_dt - dur
            ref_weekday = end_dt.weekday()

        if not _weekday_matches(ref_weekday, weekdays):
            continue
        if start_dt > now_local:
            return start_dt, end_dt

    fallback_start = now_local + timedelta(days=1)
    return fallback_start, fallback_start + dur


def compute_alarm_wakeup_window(
    alarm_local: datetime,
    mode: str,
    duration_minutes: int,
) -> tuple[datetime, datetime]:
    """Berechnet (start_dt, end_dt) aus einem konkreten Handy-Wecker-Zeitpunkt."""
    dur = timedelta(minutes=max(1, min(120, int(duration_minutes))))
    if mode == WAKEUP_MODE_START_AT:
        return alarm_local, alarm_local + dur
    return alarm_local - dur, alarm_local


def compute_dimming_step_values(
    progress: float,
    min_kelvin: int | None = None,
    max_kelvin: int | None = None,
    sunrise_color: bool = True,
) -> tuple[int, int | None]:
    """Berechnet (brightness 1..255, optional color_temp_kelvin) für einen Fortschritt 0.0..1.0."""
    p = max(0.0, min(1.0, float(progress)))
    if p <= 0.0:
        brightness = 1
    elif p >= 1.0:
        brightness = 255
    else:
        curved = p ** 1.7
        brightness = max(1, min(255, int(round(1 + curved * 254))))

    kelvin: int | None = None
    if sunrise_color and min_kelvin and max_kelvin and max_kelvin > min_kelvin:
        start_k = max(min_kelvin, 2000)
        end_k = min(max_kelvin, 4200)
        if end_k < start_k:
            start_k = min_kelvin
            end_k = max_kelvin
        kelvin = int(round(start_k + p * (end_k - start_k)))

    return brightness, kelvin


def choose_step_interval_seconds(duration_minutes: int) -> int:
    """Wählt ein schonendes Schritt-Intervall passend zur Gesamtdauer."""
    if duration_minutes <= 5:
        return 5
    if duration_minutes <= 15:
        return 10
    if duration_minutes <= 45:
        return 15
    return 30


def _collect_strings(obj: Any, out: list[str]) -> None:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                out.append(k)
            _collect_strings(v, out)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _collect_strings(item, out)


def detect_lamp_automations_from_yaml(
    automations_yaml_path: Path,
    target_tokens: set[str],
    automation_id_to_entity: dict[str, str],
    automation_alias_to_entity: dict[str, str],
) -> list[str]:
    """Findet ALLE Automationen in automations.yaml, die ausgewählte Lampen betreffen.

    Sicherheits-Automationen (Rauch, Feuer, Wasser, Alarm, Gas, Notfall) bleiben immer aktiv.
    """
    if not target_tokens or not automations_yaml_path.is_file():
        return []

    try:
        raw_text = automations_yaml_path.read_text(encoding="utf-8", errors="replace")
        parsed = yaml.load(raw_text, Loader=_SafeYamlLoader)
    except Exception:
        return []

    if not isinstance(parsed, list):
        return []

    matched: list[str] = []
    seen: set[str] = set()

    for auto in parsed:
        if not isinstance(auto, dict):
            continue

        alias = str(auto.get("alias") or "").strip()
        auto_id = str(auto.get("id") or "").strip()
        header_low = f"{alias} {auto_id}".lower()

        if any(bad in header_low for bad in _SAFETY_EXCLUDE_KEYWORDS):
            continue

        strings: list[str] = []
        _collect_strings(auto, strings)
        blob_lower = " ".join(strings).lower()
        exact_set = {s.strip() for s in strings}

        hits_target = any(
            (tok in exact_set) or (tok.lower() in blob_lower)
            for tok in target_tokens
        )
        if not hits_target:
            continue

        entity_id = None
        if auto_id and auto_id in automation_id_to_entity:
            entity_id = automation_id_to_entity[auto_id]
        elif alias and alias.lower() in automation_alias_to_entity:
            entity_id = automation_alias_to_entity[alias.lower()]

        if entity_id and entity_id not in seen:
            seen.add(entity_id)
            matched.append(entity_id)

    return matched


class WakeUpLightManager:
    """Verwaltet Zeitplan (Handy-Wecker oder feste Zeit), sanftes Hochdimmen & Automations-Pause."""

    def __init__(
        self,
        hass: HomeAssistant,
        on_update: Callable[[], None],
        on_persist: Callable[[], Any],
        entities: list[str] | None = None,
        alarm_entity: str = DEFAULT_WAKEUP_ALARM_ENTITY,
        mode: str = DEFAULT_WAKEUP_MODE,
        wakeup_time: str = DEFAULT_WAKEUP_TIME,
        duration_minutes: int = DEFAULT_WAKEUP_DURATION,
        auto_off_minutes: int = DEFAULT_WAKEUP_AUTO_OFF_MINUTES,
        weekdays: str = DEFAULT_WAKEUP_DAYS,
        auto_pause: bool = DEFAULT_WAKEUP_AUTO_PAUSE,
        manual_pause_automations: list[str] | None = None,
        sunrise_color: bool = DEFAULT_WAKEUP_SUNRISE_COLOR,
    ) -> None:
        self.hass = hass
        self._on_update = on_update
        self._on_persist = on_persist

        self.entities: list[str] = normalize_wakeup_lights(entities)
        self.alarm_entity: str = normalize_wakeup_alarm_entity(alarm_entity)
        self.mode: str = (
            mode
            if mode in (WAKEUP_MODE_REACH_100, WAKEUP_MODE_START_AT)
            else DEFAULT_WAKEUP_MODE
        )
        self.wakeup_time: str = parse_wakeup_time(wakeup_time).strftime("%H:%M")
        self.duration_minutes: int = max(1, min(120, int(duration_minutes or DEFAULT_WAKEUP_DURATION)))
        self.auto_off_minutes: int = max(0, min(180, int(auto_off_minutes or 0)))
        self.weekdays: str = (
            weekdays
            if weekdays in (WAKEUP_DAYS_DAILY, WAKEUP_DAYS_WORKDAYS, WAKEUP_DAYS_WEEKEND)
            else DEFAULT_WAKEUP_DAYS
        )
        self.auto_pause: bool = bool(auto_pause)
        self.manual_pause_automations: list[str] = normalize_wakeup_automations(
            manual_pause_automations
        )
        self.sunrise_color: bool = bool(sunrise_color)

        self.enabled: bool = False
        self.is_running: bool = False
        self.progress_percent: int = 0
        self.current_brightness_percent: int = 0
        self.remaining_minutes: int = 0
        self.next_start_dt: datetime | None = None
        self.next_end_dt: datetime | None = None
        self.next_alarm_dt: datetime | None = None
        self.active_start_dt: datetime | None = None
        self.active_end_dt: datetime | None = None
        self.auto_off_at_dt: datetime | None = None
        self.last_run_info: str = ""
        self.paused_automations: list[str] = []

        self._handled_alarm_ts: int | None = None
        self._active_alarm_ts: int | None = None
        self._unsub_schedule: CALLBACK_TYPE | None = None
        self._unsub_auto_off: CALLBACK_TYPE | None = None
        self._unsub_alarm_listener: CALLBACK_TYPE | None = None
        self._dim_task: asyncio.Task | None = None

    def get_time_obj(self) -> time:
        return parse_wakeup_time(self.wakeup_time)

    def _get_alarm_display_name(self) -> str:
        if not self.alarm_entity:
            return ""
        for cand in get_alarm_sensor_candidates(self.hass, self.alarm_entity):
            if cand["entity_id"] == self.alarm_entity:
                return cand["name"]
        st = self.hass.states.get(self.alarm_entity)
        if st and st.attributes.get("friendly_name"):
            return str(st.attributes["friendly_name"])
        return self.alarm_entity

    def _attach_alarm_listener(self) -> None:
        if self._unsub_alarm_listener is not None:
            self._unsub_alarm_listener()
            self._unsub_alarm_listener = None

        if not self.alarm_entity:
            return

        async def _handle_alarm_state_changed(_event: Event) -> None:
            # Wenn gerade schon gedimmt wird, nicht abbrechen (Android aktualisiert next_alarm kurz vor Klingeln)
            if self.is_running:
                return
            self._schedule_next(allow_immediate_start=True)
            self._on_update()

        self._unsub_alarm_listener = async_track_state_change_event(
            self.hass, [self.alarm_entity], _handle_alarm_state_changed
        )

    async def async_initialize(
        self,
        was_enabled: bool = False,
        persisted_paused_automations: list[str] | None = None,
    ) -> None:
        """Stellt nach Neustart pausierte Automationen sauber wieder her und plant den Wecker."""
        stale_paused = normalize_wakeup_automations(persisted_paused_automations)
        if stale_paused:
            self.paused_automations = stale_paused
            await self._async_restore_paused_automations()
            await self._persist()

        self.enabled = bool(was_enabled) and bool(self.entities)
        self._attach_alarm_listener()
        self._schedule_next(allow_immediate_start=False)
        self._on_update()

    async def _persist(self) -> None:
        res = self._on_persist()
        if asyncio.iscoroutine(res):
            await res

    def _cancel_schedule(self) -> None:
        if self._unsub_schedule is not None:
            self._unsub_schedule()
            self._unsub_schedule = None
        self.next_start_dt = None
        self.next_end_dt = None
        self.next_alarm_dt = None

    def _schedule_next(self, allow_immediate_start: bool = False) -> None:
        """Plant den nächsten automatischen Start (Handy-Wecker ODER feste Uhrzeit)."""
        self._cancel_schedule()
        if not self.entities:
            return

        now_local = _local_now()

        # MODUS A: Dynamischer Handy-Wecker (Next Alarm Sensor)
        if self.alarm_entity:
            st = self.hass.states.get(self.alarm_entity)
            alarm_local = parse_alarm_sensor_datetime(st, now_local=now_local)
            self.next_alarm_dt = alarm_local
            if alarm_local is None:
                # Kein Wecker am Handy gestellt -> Licht bleibt aus!
                return

            start_local, end_local = compute_alarm_wakeup_window(
                alarm_local=alarm_local,
                mode=self.mode,
                duration_minutes=self.duration_minutes,
            )
            self.next_start_dt = start_local
            self.next_end_dt = end_local

            if not self.enabled or self.is_running:
                return

            alarm_ts = int(alarm_local.timestamp())
            if self._handled_alarm_ts == alarm_ts:
                return

            if start_local > now_local:
                async def _trigger_alarm_wakeup(_now: datetime, expected_ts: int = alarm_ts) -> None:
                    self._unsub_schedule = None
                    if not self.enabled or self.is_running:
                        return
                    self._active_alarm_ts = expected_ts
                    await self.async_start_now(is_scheduled=True)

                self._unsub_schedule = async_track_point_in_utc_time(
                    self.hass, _trigger_alarm_wakeup, _as_utc(start_local)
                )
            elif allow_immediate_start and start_local <= now_local < end_local:
                # Nutzer hat gerade einen nahen Handy-Wecker gestellt (bereits im Dimm-Fenster) -> sofort sanft starten!
                rem_sec = (end_local - now_local).total_seconds()
                rem_min = max(1, int(round(rem_sec / 60.0)))
                self._active_alarm_ts = alarm_ts
                self.hass.async_create_task(
                    self.async_start_now(duration_override=rem_min, is_scheduled=True)
                )
            return

        # MODUS B: Feste Uhrzeit (manuell)
        if not self.enabled:
            return

        start_local, end_local = compute_next_wakeup_window(
            now_local=now_local,
            mode=self.mode,
            target_time=self.get_time_obj(),
            duration_minutes=self.duration_minutes,
            weekdays=self.weekdays,
        )
        self.next_start_dt = start_local
        self.next_end_dt = end_local

        async def _trigger_scheduled(_now: datetime) -> None:
            self._unsub_schedule = None
            if not self.enabled:
                return
            await self.async_start_now(is_scheduled=True)

        self._unsub_schedule = async_track_point_in_utc_time(
            self.hass, _trigger_scheduled, _as_utc(start_local)
        )

    async def async_set_enabled(self, enabled: bool) -> None:
        """Aktiviert oder deaktiviert den Wake-Up-Light-Zeitplan."""
        if enabled and not self.entities:
            raise HomeAssistantError(
                "Bitte wähle zuerst unter „Konfiguration öffnen“ mindestens eine Lampe aus."
            )
        self.enabled = bool(enabled)
        if not self.enabled and (self.is_running or self.auto_off_at_dt is not None):
            await self.async_stop(cancelled=True)
        self._schedule_next(allow_immediate_start=self.enabled)
        await self._persist()
        self._on_update()

    async def async_set_alarm_entity(self, entity_id: str) -> None:
        """Wählt einen Handy-Wecker (Next Alarm Sensor) oder wechselt auf feste Uhrzeit."""
        self.alarm_entity = normalize_wakeup_alarm_entity(entity_id)
        self._handled_alarm_ts = None
        self._attach_alarm_listener()
        self._schedule_next(allow_immediate_start=False)
        await self._persist()
        self._on_update()

    async def async_set_mode(self, mode: str) -> None:
        if mode not in (WAKEUP_MODE_REACH_100, WAKEUP_MODE_START_AT):
            return
        self.mode = mode
        self._schedule_next(allow_immediate_start=False)
        await self._persist()
        self._on_update()

    async def async_set_time(self, new_time: time) -> None:
        self.wakeup_time = time(new_time.hour, new_time.minute).strftime("%H:%M")
        self._schedule_next(allow_immediate_start=False)
        await self._persist()
        self._on_update()

    async def async_set_duration(self, minutes: int) -> None:
        self.duration_minutes = max(1, min(120, int(minutes)))
        self._schedule_next(allow_immediate_start=False)
        await self._persist()
        self._on_update()

    def _cancel_auto_off(self) -> None:
        if self._unsub_auto_off is not None:
            self._unsub_auto_off()
            self._unsub_auto_off = None
        self.auto_off_at_dt = None

    def _schedule_auto_off(self, minutes: int) -> None:
        """Plant das automatische Ausschalten der Wake-Up-Lampen nach Erreichen von 100 %."""
        self._cancel_auto_off()
        delay_min = max(0, min(180, int(minutes)))
        if delay_min <= 0 or not self.entities:
            return

        off_local = _local_now() + timedelta(minutes=delay_min)
        self.auto_off_at_dt = off_local

        async def _execute_auto_off(_now: datetime) -> None:
            self._unsub_auto_off = None
            self.auto_off_at_dt = None
            turned_off: list[str] = []
            for eid in self.entities:
                st = self.hass.states.get(eid)
                if st is not None and st.state != "on":
                    continue
                attrs = (st.attributes or {}) if st is not None else {}
                supported_modes = set(attrs.get("supported_color_modes") or [])
                svc_data: dict[str, Any] = {"entity_id": eid}
                if supported_modes != {"onoff"}:
                    svc_data["transition"] = 3
                try:
                    await self.hass.services.async_call(
                        "light", "turn_off", svc_data, blocking=False
                    )
                    turned_off.append(eid)
                except Exception as err:
                    _LOGGER.warning("Wake-Up Light Auto-Aus %s Fehler: %s", eid, err)

            self.last_run_info = f"Auto-Aus um {_local_now().strftime('%H:%M')}"
            self.hass.bus.async_fire(
                EVENT_WAKEUP_AUTO_OFF,
                {
                    "entities": turned_off,
                    "auto_off_minutes": delay_min,
                },
            )
            self._on_update()

        self._unsub_auto_off = async_track_point_in_utc_time(
            self.hass, _execute_auto_off, _as_utc(off_local)
        )

    async def async_set_auto_off_minutes(self, minutes: int) -> None:
        """Stellt die optionale Auto-Aus-Zeit nach 100 % ein (0 = deaktiviert)."""
        self.auto_off_minutes = max(0, min(180, int(minutes)))
        if self.auto_off_minutes == 0 and self.auto_off_at_dt is not None:
            self._cancel_auto_off()
        await self._persist()
        self._on_update()

    async def async_set_weekdays(self, weekdays: str) -> None:
        if weekdays not in (
            WAKEUP_DAYS_DAILY,
            WAKEUP_DAYS_WORKDAYS,
            WAKEUP_DAYS_WEEKEND,
        ):
            return
        self.weekdays = weekdays
        self._schedule_next(allow_immediate_start=False)
        await self._persist()
        self._on_update()

    async def async_set_auto_pause(self, auto_pause: bool) -> None:
        self.auto_pause = bool(auto_pause)
        await self._persist()
        self._on_update()

    async def async_set_sunrise_color(self, sunrise_color: bool) -> None:
        self.sunrise_color = bool(sunrise_color)
        await self._persist()
        self._on_update()

    async def _async_detect_lamp_automations(self) -> list[str]:
        """Ermittelt alle Automationen, die ausgewählte Lampen (Entity/Device/Area) steuern."""
        if not self.auto_pause or not self.entities:
            return []

        target_tokens: set[str] = set(self.entities)
        try:
            ent_reg = er.async_get(self.hass)
            dev_reg = dr.async_get(self.hass)
            for eid in self.entities:
                reg_entry = ent_reg.async_get(eid)
                if not reg_entry:
                    continue
                if reg_entry.area_id:
                    target_tokens.add(reg_entry.area_id)
                if reg_entry.device_id:
                    target_tokens.add(reg_entry.device_id)
                    dev = dev_reg.async_get(reg_entry.device_id)
                    if dev and dev.area_id:
                        target_tokens.add(dev.area_id)
        except Exception:
            pass

        auto_id_map: dict[str, str] = {}
        auto_alias_map: dict[str, str] = {}
        for st in self.hass.states.async_all("automation"):
            attrs = st.attributes or {}
            if attrs.get("id"):
                auto_id_map[str(attrs["id"]).strip()] = st.entity_id
            if attrs.get("friendly_name"):
                auto_alias_map[str(attrs["friendly_name"]).strip().lower()] = st.entity_id

        auto_yaml = Path(self.hass.config.config_dir) / "automations.yaml"
        return await self.hass.async_add_executor_job(
            detect_lamp_automations_from_yaml,
            auto_yaml,
            target_tokens,
            auto_id_map,
            auto_alias_map,
        )

    async def _async_pause_lamp_automations(self) -> None:
        """Pausiert alle betroffenen Lampen-Automationen (inkl. stop_actions) während des Dimmens."""
        auto_detected = await self._async_detect_lamp_automations()
        candidates = list(
            dict.fromkeys([*self.manual_pause_automations, *auto_detected])
        )
        paused: list[str] = list(self.paused_automations)

        for auto_eid in candidates:
            st = self.hass.states.get(auto_eid)
            if st is None or st.state != "on":
                continue
            try:
                await self.hass.services.async_call(
                    "automation",
                    "turn_off",
                    {"entity_id": auto_eid, "stop_actions": True},
                    blocking=False,
                )
                if auto_eid not in paused:
                    paused.append(auto_eid)
            except Exception as err:
                _LOGGER.warning(
                    "Wake-Up Light: Automation %s konnte nicht pausiert werden: %s",
                    auto_eid,
                    err,
                )

        self.paused_automations = paused
        await self._persist()

    async def _async_restore_paused_automations(self) -> None:
        """Aktiviert alle vom Wake-Up Light pausierten Automationen wieder."""
        to_restore = list(self.paused_automations)
        self.paused_automations = []
        for auto_eid in to_restore:
            try:
                await self.hass.services.async_call(
                    "automation",
                    "turn_on",
                    {"entity_id": auto_eid},
                    blocking=False,
                )
            except Exception as err:
                _LOGGER.warning(
                    "Wake-Up Light: Automation %s konnte nicht reaktiviert werden: %s",
                    auto_eid,
                    err,
                )

    async def _async_apply_dimming_step(
        self, progress: float, transition_sec: int
    ) -> None:
        """Setzt Helligkeit (und optional Farbtemperatur) für alle ausgewählten Lampen."""
        for eid in self.entities:
            st = self.hass.states.get(eid)
            attrs = (st.attributes or {}) if st is not None else {}
            supported_modes = set(attrs.get("supported_color_modes") or [])

            if supported_modes == {"onoff"}:
                if progress <= 0.05 or progress >= 1.0:
                    try:
                        await self.hass.services.async_call(
                            "light", "turn_on", {"entity_id": eid}, blocking=False
                        )
                    except Exception as err:
                        _LOGGER.warning("Wake-Up Light %s Fehler: %s", eid, err)
                continue

            supports_kelvin = "color_temp" in supported_modes or (
                attrs.get("min_color_temp_kelvin") is not None
                and attrs.get("max_color_temp_kelvin") is not None
            )
            min_k = attrs.get("min_color_temp_kelvin") if supports_kelvin else None
            max_k = attrs.get("max_color_temp_kelvin") if supports_kelvin else None

            brightness, kelvin = compute_dimming_step_values(
                progress=progress,
                min_kelvin=int(min_k) if isinstance(min_k, (int, float)) else None,
                max_kelvin=int(max_k) if isinstance(max_k, (int, float)) else None,
                sunrise_color=self.sunrise_color,
            )

            service_data: dict[str, Any] = {
                "entity_id": eid,
                "brightness": brightness,
            }
            if transition_sec > 0:
                service_data["transition"] = transition_sec
            if kelvin is not None:
                service_data["color_temp_kelvin"] = kelvin

            try:
                await self.hass.services.async_call(
                    "light", "turn_on", service_data, blocking=False
                )
            except Exception as err:
                _LOGGER.warning("Wake-Up Light %s Fehler: %s", eid, err)

    async def async_start_now(
        self,
        duration_override: int | None = None,
        auto_off_override: int | None = None,
        is_scheduled: bool = False,
    ) -> None:
        """Startet den Sonnenaufgang (0 % → 100 %) und pausiert alle betroffenen Automationen."""
        if not self.entities:
            raise HomeAssistantError(
                "Bitte wähle zuerst unter „Konfiguration öffnen“ mindestens eine Lampe aus."
            )

        self._cancel_auto_off()

        if self._dim_task and not self._dim_task.done():
            self._dim_task.cancel()
            try:
                await self._dim_task
            except asyncio.CancelledError:
                pass

        dur_min = (
            max(1, min(120, int(duration_override)))
            if duration_override is not None
            else self.duration_minutes
        )
        eff_auto_off = (
            max(0, min(180, int(auto_off_override)))
            if auto_off_override is not None
            else self.auto_off_minutes
        )

        self.is_running = True
        self.progress_percent = 0
        self.current_brightness_percent = 1
        self.remaining_minutes = dur_min
        now_local = _local_now()
        self.active_start_dt = now_local
        self.active_end_dt = now_local + timedelta(minutes=dur_min)

        await self._async_pause_lamp_automations()

        self.hass.bus.async_fire(
            EVENT_WAKEUP_STARTED,
            {
                "entities": list(self.entities),
                "duration_minutes": dur_min,
                "auto_off_minutes": eff_auto_off,
                "paused_automations": list(self.paused_automations),
                "alarm_entity": self.alarm_entity,
                "scheduled": is_scheduled,
            },
        )

        self._dim_task = self.hass.async_create_task(
            self._async_run_sunrise_loop(dur_min, eff_auto_off)
        )
        self._on_update()

    async def _async_run_sunrise_loop(
        self, duration_minutes: int, auto_off_minutes: int = 0
    ) -> None:
        """Dimmt schrittweise von 1/255 (~0 %) auf 255/255 (100 %) hoch."""
        total_seconds = max(60, duration_minutes * 60)
        step_sec = choose_step_interval_seconds(duration_minutes)
        start_mono = asyncio.get_running_loop().time()

        try:
            await self._async_apply_dimming_step(0.0, transition_sec=1)
            self._on_update()

            while True:
                elapsed = asyncio.get_running_loop().time() - start_mono
                remaining = total_seconds - elapsed
                if remaining <= 0:
                    break

                sleep_for = min(float(step_sec), remaining)
                await asyncio.sleep(sleep_for)

                elapsed_now = asyncio.get_running_loop().time() - start_mono
                progress = min(1.0, elapsed_now / total_seconds)
                brightness, _ = compute_dimming_step_values(
                    progress=progress, sunrise_color=False
                )
                self.progress_percent = int(round(progress * 100))
                self.current_brightness_percent = max(
                    1, int(round((brightness / 255.0) * 100))
                )
                self.remaining_minutes = max(
                    0, int((max(0.0, total_seconds - elapsed_now) + 59) // 60)
                )

                next_transition = min(step_sec, max(1, int(round(sleep_for))))
                await self._async_apply_dimming_step(
                    progress, transition_sec=next_transition
                )
                self._on_update()

                if progress >= 1.0:
                    break

            await self._async_apply_dimming_step(1.0, transition_sec=2)
            self.progress_percent = 100
            self.current_brightness_percent = 100
            self.remaining_minutes = 0
            if auto_off_minutes > 0:
                self._schedule_auto_off(auto_off_minutes)
                off_hhmm = self.auto_off_at_dt.strftime("%H:%M") if self.auto_off_at_dt else ""
                self.last_run_info = f"100 % erreicht – Auto-Aus um {off_hhmm}"
            else:
                self.last_run_info = f"Abgeschlossen um {_local_now().strftime('%H:%M')}"

            self.hass.bus.async_fire(
                EVENT_WAKEUP_COMPLETED,
                {
                    "entities": list(self.entities),
                    "duration_minutes": duration_minutes,
                    "auto_off_minutes": auto_off_minutes,
                },
            )
        except asyncio.CancelledError:
            self.last_run_info = f"Abgebrochen um {_local_now().strftime('%H:%M')}"
            self.hass.bus.async_fire(
                EVENT_WAKEUP_CANCELLED,
                {"entities": list(self.entities)},
            )
            raise
        finally:
            if self._active_alarm_ts is not None:
                self._handled_alarm_ts = self._active_alarm_ts
                self._active_alarm_ts = None
            self.is_running = False
            self.active_start_dt = None
            self.active_end_dt = None
            self._dim_task = None
            await self._async_restore_paused_automations()
            await self._persist()
            if self.enabled:
                self._schedule_next(allow_immediate_start=False)
            self._on_update()

    async def async_stop(self, cancelled: bool = True) -> None:
        """Bricht einen laufenden Sonnenaufgang oder Auto-Aus-Timer ab und reaktiviert Automationen."""
        had_auto_off = self.auto_off_at_dt is not None
        self._cancel_auto_off()

        if self._dim_task and not self._dim_task.done():
            self._dim_task.cancel()
            try:
                await self._dim_task
            except asyncio.CancelledError:
                pass
        else:
            self.is_running = False
            self.progress_percent = 0
            self.remaining_minutes = 0
            if had_auto_off and cancelled:
                self.last_run_info = f"Auto-Aus abgebrochen um {_local_now().strftime('%H:%M')}"
            if self.paused_automations:
                await self._async_restore_paused_automations()
                await self._persist()
            self._on_update()

    async def async_shutdown(self) -> None:
        """Beendet Timer, Auto-Aus, Alarm-Listener & laufenden Task sauber beim Entladen/Neustart."""
        self._cancel_schedule()
        self._cancel_auto_off()
        if self._unsub_alarm_listener is not None:
            self._unsub_alarm_listener()
            self._unsub_alarm_listener = None
        if self._dim_task and not self._dim_task.done():
            self._dim_task.cancel()
            try:
                await self._dim_task
            except asyncio.CancelledError:
                pass

    def get_status_snapshot(self) -> dict[str, Any]:
        """Liefert alle Statusdaten für Sensor, Switch und Dashboard-Karte."""
        now_local = _local_now()
        alarm_name = self._get_alarm_display_name()
        alarm_time_full = ""
        alarm_hhmm = ""
        has_phone_alarm = False

        if self.alarm_entity:
            st = self.hass.states.get(self.alarm_entity)
            alarm_dt = parse_alarm_sensor_datetime(st, now_local=now_local)
            if alarm_dt is not None:
                has_phone_alarm = True
                alarm_time_full = alarm_dt.strftime("%d.%m. %H:%M")
                alarm_hhmm = alarm_dt.strftime("%H:%M")

        if self.is_running and self.active_start_dt and self.active_end_dt:
            start_str = self.active_start_dt.strftime("%H:%M")
            end_str = self.active_end_dt.strftime("%H:%M")
            next_start_full = self.active_start_dt.strftime("%d.%m. %H:%M")
        elif self.alarm_entity:
            if has_phone_alarm:
                st = self.hass.states.get(self.alarm_entity)
                alarm_dt = parse_alarm_sensor_datetime(st, now_local=now_local)
                if alarm_dt is not None:
                    p_start, p_end = compute_alarm_wakeup_window(
                        alarm_dt, self.mode, self.duration_minutes
                    )
                    start_str = p_start.strftime("%H:%M")
                    end_str = p_end.strftime("%H:%M")
                    next_start_full = p_start.strftime("%d.%m. %H:%M")
                else:
                    start_str, end_str, next_start_full = "", "", ""
            else:
                start_str, end_str, next_start_full = "", "", ""
        elif self.enabled and self.next_start_dt and self.next_end_dt:
            start_str = self.next_start_dt.strftime("%H:%M")
            end_str = self.next_end_dt.strftime("%H:%M")
            next_start_full = self.next_start_dt.strftime("%d.%m. %H:%M")
        else:
            p_start, p_end = compute_next_wakeup_window(
                now_local=now_local,
                mode=self.mode,
                target_time=self.get_time_obj(),
                duration_minutes=self.duration_minutes,
                weekdays=self.weekdays,
            )
            start_str = p_start.strftime("%H:%M")
            end_str = p_end.strftime("%H:%M")
            next_start_full = ""

        auto_off_pending = self.auto_off_at_dt is not None
        auto_off_hhmm = self.auto_off_at_dt.strftime("%H:%M") if self.auto_off_at_dt else ""
        auto_off_full = self.auto_off_at_dt.strftime("%d.%m. %H:%M") if self.auto_off_at_dt else ""

        if not self.entities:
            status_text = "Keine Lampen gewählt"
        elif self.is_running:
            status_text = f"Dimmt · {self.current_brightness_percent} %"
        elif auto_off_pending:
            status_text = f"Auto-Aus um {auto_off_hhmm}"
        elif not self.enabled:
            status_text = "Aus"
        elif self.alarm_entity:
            if has_phone_alarm:
                status_text = f"📱 Wecker · {start_str} → {end_str}"
            else:
                status_text = "📱 Kein Wecker gestellt"
        else:
            status_text = f"Geplant · {start_str} → {end_str}"

        lamp_names: list[str] = []
        for eid in self.entities:
            st = self.hass.states.get(eid)
            lamp_names.append(
                str(st.attributes.get("friendly_name") or eid) if st else eid
            )

        paused_names: list[str] = []
        for aid in self.paused_automations:
            st = self.hass.states.get(aid)
            paused_names.append(
                str(st.attributes.get("friendly_name") or aid) if st else aid
            )

        return {
            "enabled": self.enabled,
            "is_running": self.is_running,
            "status": status_text,
            "entities": list(self.entities),
            "lamp_names": lamp_names,
            "lamps_count": len(self.entities),
            "alarm_entity": self.alarm_entity,
            "alarm_name": alarm_name,
            "alarm_source": f"📱 {alarm_name}" if self.alarm_entity else "🕒 Feste Uhrzeit",
            "has_phone_alarm": has_phone_alarm,
            "alarm_time_full": alarm_time_full,
            "alarm_hhmm": alarm_hhmm,
            "mode": self.mode,
            "wakeup_time": self.wakeup_time,
            "duration_minutes": self.duration_minutes,
            "auto_off_minutes": self.auto_off_minutes,
            "auto_off_pending": auto_off_pending,
            "auto_off_hhmm": auto_off_hhmm,
            "auto_off_full": auto_off_full,
            "weekdays": self.weekdays,
            "auto_pause": self.auto_pause,
            "sunrise_color": self.sunrise_color,
            "start_hhmm": start_str,
            "end_hhmm": end_str,
            "next_start": next_start_full,
            "progress_percent": self.progress_percent,
            "brightness_percent": self.current_brightness_percent,
            "remaining_minutes": self.remaining_minutes,
            "paused_automations": list(self.paused_automations),
            "paused_automation_names": paused_names,
            "last_run": self.last_run_info,
        }
