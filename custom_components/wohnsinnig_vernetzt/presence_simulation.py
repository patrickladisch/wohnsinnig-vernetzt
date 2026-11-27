"""Anwesenheitssimulation (1:1 Verlauf von vor 14 Tagen ± 7 Min) inkl. Bewegungsmelder-Schutz."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from functools import partial
import logging
from pathlib import Path
import random
import re
import time as time_mod
from typing import Any

import yaml

from homeassistant.core import CALLBACK_TYPE, Context, Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_PRESENCE_AUTO_PAUSE_MOTION,
    DEFAULT_PRESENCE_DAYS_OFFSET,
    DEFAULT_PRESENCE_JITTER_MINUTES,
    DOMAIN,
    EVENT_PRESENCE_INTERFERENCE_BLOCKED,
    PRESENCE_HISTORY_KEEP_DAYS,
    PRESENCE_HISTORY_STORAGE_KEY,
    PRESENCE_HISTORY_STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

ALLOWED_PRESENCE_DOMAINS = ("light", "switch")
MAX_EVENTS_PER_ENTITY = 2500
MAX_CORRECTIONS_PER_MINUTE = 6
ENFORCE_DEBOUNCE_SECONDS = 0.8
OWN_ACTION_GRACE_SECONDS = 2.5

_MOTION_KEYWORDS = (
    "motion",
    "beweg",
    "occupancy",
    "presence",
    "präsenz",
    "praesenz",
    "anwesenheit",
    "pir",
)
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
    "anwesenheitssimulation",
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


def _to_local_str(dt_val: datetime) -> str:
    try:
        from homeassistant.util import dt as dt_util

        return dt_util.as_local(dt_val).strftime("%d.%m. %H:%M")
    except Exception:
        return dt_val.strftime("%d.%m. %H:%M")


def normalize_presence_entities(raw: object) -> list[str]:
    """Bereinigt und filtert ausgewählte Lampen & Schalter (nur light.* und switch.*)."""
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
        if "." not in eid:
            continue
        dom = eid.split(".", 1)[0].lower()
        if dom not in ALLOWED_PRESENCE_DOMAINS:
            continue
        if f".{DOMAIN}" in eid:
            continue
        if eid not in seen:
            seen.add(eid)
            cleaned.append(eid)
    return cleaned


def normalize_automation_entities(raw: object) -> list[str]:
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


def _extract_light_attrs(domain: str, attrs: dict[str, Any]) -> dict[str, Any]:
    """Extrahiert relevante Licht-Attribute für naturgetreue 1:1-Wiedergabe."""
    if domain != "light" or not isinstance(attrs, dict):
        return {}
    out: dict[str, Any] = {}
    brightness = attrs.get("brightness")
    if isinstance(brightness, (int, float)) and 1 <= int(brightness) <= 255:
        out["brightness"] = int(brightness)
    kelvin = attrs.get("color_temp_kelvin")
    if isinstance(kelvin, (int, float)) and 1000 <= int(kelvin) <= 10000:
        out["color_temp_kelvin"] = int(kelvin)
    elif isinstance(attrs.get("rgb_color"), (list, tuple)) and len(attrs["rgb_color"]) == 3:
        out["rgb_color"] = [int(c) for c in attrs["rgb_color"]]
    return out


def compute_entity_replay_plan(
    events: list[dict[str, Any]],
    now_ts: float,
    window_hours: float = 24.0,
    days_offset: int = DEFAULT_PRESENCE_DAYS_OFFSET,
    jitter_minutes: int = DEFAULT_PRESENCE_JITTER_MINUTES,
    rng: random.Random | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Berechnet Anfangszustand & geplante Schaltvorgänge (+-jitter) für eine Entität.

    Garantiert chronologische Reihenfolge (kurze AN->AUS-Phasen werden durch den
    Zufalls-Versatz niemals vertauscht!).
    """
    if not events:
        return None, []

    rand = rng or random
    shift_sec = days_offset * 86400.0
    source_start = now_ts - shift_sec
    source_end = source_start + window_hours * 3600.0
    jitter_sec = max(0, int(jitter_minutes) * 60)

    sorted_events = sorted(events, key=lambda item: float(item["ts"]))

    # 1. Zustand exakt zum Startpunkt (vor `days_offset` Tagen)
    initial_event: dict[str, Any] | None = None
    window_events: list[dict[str, Any]] = []

    for ev in sorted_events:
        ts = float(ev["ts"])
        if ts <= source_start:
            initial_event = ev
        elif ts <= source_end:
            window_events.append(ev)

    # 2. Organischen Zufalls-Versatz (± jitter_minutes) anwenden & Reihenfolge schützen
    planned: list[dict[str, Any]] = []
    prev_orig_ts: float | None = float(initial_event["ts"]) if initial_event else None
    prev_sched_ts: float | None = None

    for ev in window_events:
        orig_ts = float(ev["ts"])
        offset_sec = rand.randint(-jitter_sec, jitter_sec) if jitter_sec > 0 else 0
        sched_ts = orig_ts + shift_sec + offset_sec

        if prev_sched_ts is not None and sched_ts <= prev_sched_ts:
            orig_gap = max(5.0, orig_ts - (prev_orig_ts or orig_ts))
            sched_ts = prev_sched_ts + min(orig_gap, 60.0)
            offset_sec = int(round(sched_ts - (orig_ts + shift_sec)))

        prev_orig_ts = orig_ts
        prev_sched_ts = sched_ts

        # Falls der negative Jitter ein Ereignis knapp in die Vergangenheit schiebt,
        # wird es direkt zum aktuellen Anfangszustand!
        if sched_ts <= now_ts:
            initial_event = ev
            continue

        planned.append(
            {
                "sched_ts": sched_ts,
                "orig_ts": orig_ts,
                "offset_min": int(round(offset_sec / 60.0)),
                "state": ev["state"],
                "attrs": dict(ev.get("attrs") or {}),
            }
        )

    initial_state = (
        {"state": initial_event["state"], "attrs": dict(initial_event.get("attrs") or {})}
        if initial_event
        else None
    )
    return initial_state, planned


def _collect_strings(obj: Any, out: list[str]) -> None:
    """Sammelt rekursiv alle Strings in einer YAML-Automationsstruktur."""
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


def detect_motion_automations_from_yaml(
    automations_yaml_path: Path,
    target_tokens: set[str],
    motion_entity_ids: set[str],
    automation_id_to_entity: dict[str, str],
    automation_alias_to_entity: dict[str, str],
) -> list[str]:
    """Erkennt Bewegungsmelder-Automationen in automations.yaml, die Ziel-Lampen steuern."""
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

        # Sicherheits-Automationen (Rauch, Wasser, Alarm, etc.) niemals anfassen!
        if any(bad in header_low for bad in _SAFETY_EXCLUDE_KEYWORDS):
            continue

        strings: list[str] = []
        _collect_strings(auto, strings)
        blob_lower = " ".join(strings).lower()
        exact_set = {s.strip() for s in strings}

        # 1. Steuert diese Automation eine unserer ausgewählten Lampen/Schalter (oder deren Gerät/Bereich)?
        hits_target = any(
            (tok in exact_set) or (tok.lower() in blob_lower)
            for tok in target_tokens
        )
        if not hits_target:
            continue

        # 2. Ist ein Bewegungsmelder / Präsenzmelder beteiligt?
        hits_motion_entity = any(mid in exact_set for mid in motion_entity_ids)
        hits_motion_kw = any(kw in blob_lower for kw in _MOTION_KEYWORDS)
        if not (hits_motion_entity or hits_motion_kw):
            continue

        # 3. Passende automation.* entity_id auflösen
        entity_id = None
        if auto_id and auto_id in automation_id_to_entity:
            entity_id = automation_id_to_entity[auto_id]
        elif alias and alias.lower() in automation_alias_to_entity:
            entity_id = automation_alias_to_entity[alias.lower()]

        if entity_id and entity_id not in seen:
            seen.add(entity_id)
            matched.append(entity_id)

    return matched


class PresenceSimulationManager:
    """Verwaltet 21-Tage-Verlauf, 14-Tage-Replay (±7 Min) und Bewegungsmelder-Schutz."""

    def __init__(
        self,
        hass: HomeAssistant,
        on_update: Callable[[], None],
        entities: list[str] | None = None,
        manual_pause_automations: list[str] | None = None,
        auto_pause_motion: bool = DEFAULT_PRESENCE_AUTO_PAUSE_MOTION,
        jitter_minutes: int = DEFAULT_PRESENCE_JITTER_MINUTES,
    ) -> None:
        self.hass = hass
        self._on_update = on_update

        self.entities: list[str] = normalize_presence_entities(entities)
        self.manual_pause_automations: list[str] = normalize_automation_entities(
            manual_pause_automations
        )
        self.auto_pause_motion: bool = bool(auto_pause_motion)
        self.jitter_minutes: int = max(0, min(30, int(jitter_minutes)))

        self._history_store: Store[dict] = Store(
            hass, PRESENCE_HISTORY_STORAGE_VERSION, PRESENCE_HISTORY_STORAGE_KEY
        )
        self._history_loaded: bool = False
        self._history_dirty: bool = False
        self._history_started_at: float | None = None
        self._history: dict[str, list[dict[str, Any]]] = {}

        # Laufzeit-Status der Simulation
        self.enabled: bool = False
        self.paused_automations: list[str] = []
        self.expected_states: dict[str, dict[str, Any]] = {}
        self.scheduled_events: list[dict[str, Any]] = []
        self.data_source_info: str = "Bereit"
        self.blocked_interferences: int = 0
        self.last_interference: str = ""
        self.last_action_info: str = ""

        # Interne Listener, Timer & Schutzmechanismen
        self._unsub_state_listener: CALLBACK_TYPE | None = None
        self._unsub_timers: list[CALLBACK_TYPE] = []
        self._unsub_replan_timer: CALLBACK_TYPE | None = None
        self._unsub_save_timer: CALLBACK_TYPE | None = None
        self._enforce_tasks: dict[str, asyncio.Task] = {}
        self._own_context_ids: deque[str] = deque(maxlen=250)
        self._last_sim_action_ts: dict[str, float] = {}
        self._correction_timestamps: dict[str, deque[float]] = {}

    async def async_initialize(
        self,
        was_enabled: bool = False,
        persisted_paused_automations: list[str] | None = None,
    ) -> None:
        """Lädt den 21-Tage-Verlauf, richtet Aufzeichnung ein und setzt ggf. nach Neustart fort."""
        await self._async_load_history()
        self.paused_automations = normalize_automation_entities(
            persisted_paused_automations
        )

        # Backfill aus HA-Recorder (sofern vorhanden), damit 14-Tage-Daten sofort nutzbar sind
        if self.entities:
            await self._async_backfill_from_recorder(self.entities)

        self._attach_state_listener()

        if was_enabled and self.entities:
            await self.async_turn_on(is_restore=True)
        elif not was_enabled and self.paused_automations:
            # Sicherheits-Aufräumen, falls HA während Abschaltung abstürzte
            await self._async_restore_paused_automations()

    async def _async_load_history(self) -> None:
        if self._history_loaded:
            return
        stored = await self._history_store.async_load()
        if isinstance(stored, dict):
            raw_entities = stored.get("entities")
            if isinstance(raw_entities, dict):
                for eid, ev_list in raw_entities.items():
                    if isinstance(ev_list, list):
                        self._history[str(eid)] = [
                            ev
                            for ev in ev_list
                            if isinstance(ev, dict)
                            and "ts" in ev
                            and ev.get("state") in ("on", "off")
                        ]
            started = stored.get("started_at")
            if isinstance(started, (int, float)):
                self._history_started_at = float(started)

        if self._history_started_at is None:
            self._history_started_at = _utc_now().timestamp()
            self._history_dirty = True

        self._prune_history()
        self._history_loaded = True

    def _prune_history(self) -> None:
        cutoff = (_utc_now() - timedelta(days=PRESENCE_HISTORY_KEEP_DAYS)).timestamp()
        for eid in list(self._history.keys()):
            kept = [ev for ev in self._history[eid] if float(ev["ts"]) >= cutoff]
            if len(kept) > MAX_EVENTS_PER_ENTITY:
                kept = kept[-MAX_EVENTS_PER_ENTITY:]
            self._history[eid] = kept

    async def async_save_history(self) -> None:
        self._prune_history()
        await self._history_store.async_save(
            {
                "started_at": self._history_started_at or _utc_now().timestamp(),
                "entities": self._history,
            }
        )
        self._history_dirty = False

    def _schedule_history_save(self) -> None:
        self._history_dirty = True
        if self._unsub_save_timer is not None:
            return

        async def _do_save(_now: datetime) -> None:
            self._unsub_save_timer = None
            if self._history_dirty:
                await self.async_save_history()

        self._unsub_save_timer = async_track_point_in_utc_time(
            self.hass, _do_save, _utc_now() + timedelta(minutes=3)
        )

    async def _async_query_recorder_history(
        self, entity_ids: list[str], start_dt: datetime, end_dt: datetime
    ) -> dict[str, list[dict[str, Any]]]:
        """Fragt sicher Home Assistants Recorder-Verlauf ab (optional, fehlertolerant)."""
        if not entity_ids or "recorder" not in self.hass.config.components:
            return {}
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.history import (
                get_significant_states,
            )

            fn = partial(
                get_significant_states,
                self.hass,
                start_dt,
                end_dt,
                entity_ids=entity_ids,
                include_start_time_state=True,
                significant_changes_only=True,
                minimal_response=False,
            )
            states_map = await get_instance(self.hass).async_add_executor_job(fn)
        except Exception as err:
            _LOGGER.debug("Recorder-Verlauf nicht verfügbar: %s", err)
            return {}

        result: dict[str, list[dict[str, Any]]] = {}
        for eid, state_list in (states_map or {}).items():
            dom = eid.split(".", 1)[0]
            converted: list[dict[str, Any]] = []
            last_state_val: str | None = None
            for st in state_list:
                val = getattr(st, "state", None)
                if val not in ("on", "off"):
                    continue
                if val == last_state_val and dom != "light":
                    continue
                ts_dt = getattr(st, "last_changed", None) or getattr(
                    st, "last_updated", None
                )
                if not isinstance(ts_dt, datetime):
                    continue
                if ts_dt.tzinfo is None:
                    ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                attrs = (
                    _extract_light_attrs(dom, getattr(st, "attributes", {}) or {})
                    if val == "on"
                    else {}
                )
                converted.append(
                    {
                        "ts": round(ts_dt.timestamp(), 1),
                        "state": val,
                        "attrs": attrs,
                    }
                )
                last_state_val = val
            if converted:
                result[eid] = converted
        return result

    async def _async_backfill_from_recorder(self, entity_ids: list[str]) -> None:
        """Übernimmt einmalig vorhandene Recorder-Daten (bis 16 Tage zurück) in unseren 21-Tage-Speicher."""
        now = _utc_now()
        start_dt = now - timedelta(days=16)
        rec_map = await self._async_query_recorder_history(entity_ids, start_dt, now)
        if not rec_map:
            return

        changed = False
        earliest_ts = self._history_started_at or now.timestamp()

        for eid, rec_events in rec_map.items():
            existing = self._history.get(eid, [])
            existing_keys = {(int(ev["ts"]), ev["state"]) for ev in existing}
            merged = list(existing)
            for ev in rec_events:
                k = (int(ev["ts"]), ev["state"])
                if k not in existing_keys:
                    merged.append(ev)
                    existing_keys.add(k)
                    changed = True
                if float(ev["ts"]) < earliest_ts:
                    earliest_ts = float(ev["ts"])
            merged.sort(key=lambda item: float(item["ts"]))
            self._history[eid] = merged[-MAX_EVENTS_PER_ENTITY:]

        if earliest_ts < (self._history_started_at or now.timestamp()):
            self._history_started_at = earliest_ts
            changed = True

        if changed:
            await self.async_save_history()

    def get_history_span_days(self) -> float:
        """Gibt an, wie viele Tage Verlaufsdaten bereits vorliegen."""
        now_ts = _utc_now().timestamp()
        earliest = self._history_started_at or now_ts
        for eid in self.entities:
            evs = self._history.get(eid)
            if evs:
                first_ts = float(evs[0]["ts"])
                if first_ts < earliest:
                    earliest = first_ts
        return round(max(0.0, (now_ts - earliest) / 86400.0), 1)

    def _attach_state_listener(self) -> None:
        if self._unsub_state_listener is not None:
            self._unsub_state_listener()
            self._unsub_state_listener = None

        if not self.entities:
            return

        self._unsub_state_listener = async_track_state_change_event(
            self.hass, self.entities, self._handle_entity_state_changed
        )

    async def _handle_entity_state_changed(self, event: Event) -> None:
        """Zwei Aufgaben: passiv aufzeichnen (wenn AUS) ODER vor Bewegungsmeldern schützen (wenn AN)."""
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not entity_id or new_state is None:
            return

        new_val = new_state.state
        if new_val not in ("on", "off"):
            return

        # MODUS 1: Simulation ist AUS -> Echtes menschliches Schaltverhalten für in 14 Tagen mitschneiden
        if not self.enabled:
            old_val = old_state.state if old_state is not None else None
            dom = entity_id.split(".", 1)[0]
            if old_val == new_val and dom != "light":
                return
            attrs = (
                _extract_light_attrs(dom, new_state.attributes or {})
                if new_val == "on"
                else {}
            )
            bucket = self._history.setdefault(entity_id, [])
            if (
                bucket
                and bucket[-1]["state"] == new_val
                and bucket[-1].get("attrs", {}) == attrs
            ):
                return
            bucket.append(
                {
                    "ts": round(_utc_now().timestamp(), 1),
                    "state": new_val,
                    "attrs": attrs,
                }
            )
            if len(bucket) > MAX_EVENTS_PER_ENTITY:
                del bucket[:-MAX_EVENTS_PER_ENTITY]
            self._schedule_history_save()
            return

        # MODUS 2: Simulation ist AN -> ECHTZEIT-ZUSTANDSWÄCHTER gegen Bewegungsmelder & externe Eingriffe!
        expected = self.expected_states.get(entity_id)
        if not expected:
            return
        if new_val == expected["state"]:
            return

        # Eigene Schaltbefehle der Simulation niemals blockieren
        ctx = event.context
        if ctx is not None:
            if ctx.id in self._own_context_ids or (
                ctx.parent_id and ctx.parent_id in self._own_context_ids
            ):
                return

        if (
            time_mod.monotonic() - self._last_sim_action_ts.get(entity_id, 0.0)
            < OWN_ACTION_GRACE_SECONDS
        ):
            return

        # Rate-Limiting gegen Hardware-Ping-Pong (max. 6 Korrekturen pro Minute pro Lampe)
        now_mono = time_mod.monotonic()
        hist_q = self._correction_timestamps.setdefault(entity_id, deque())
        while hist_q and now_mono - hist_q[0] > 60.0:
            hist_q.popleft()
        if len(hist_q) >= MAX_CORRECTIONS_PER_MINUTE:
            _LOGGER.warning(
                "Anwesenheitssimulation: Zu viele externe Schaltversuche auf %s (>%d/Min), pausiere Korrektur kurz.",
                entity_id,
                MAX_CORRECTIONS_PER_MINUTE,
            )
            return
        hist_q.append(now_mono)

        # Bestehenden Korrektur-Task für diese Entität ersetzen (0,8 s Debounce)
        old_task = self._enforce_tasks.pop(entity_id, None)
        if old_task and not old_task.done():
            old_task.cancel()

        friendly = str(new_state.attributes.get("friendly_name") or entity_id)
        self._enforce_tasks[entity_id] = self.hass.async_create_task(
            self._async_enforce_expected_state(
                entity_id, friendly, new_val, dict(expected)
            )
        )

    async def _async_enforce_expected_state(
        self,
        entity_id: str,
        friendly_name: str,
        unwanted_state: str,
        expected: dict[str, Any],
    ) -> None:
        """Stellt den 1:1-Simulationszustand nach einem Bewegungsmelder-Eingriff sofort wieder her."""
        try:
            await asyncio.sleep(ENFORCE_DEBOUNCE_SECONDS)
            if not self.enabled:
                return
            current_expected = self.expected_states.get(entity_id)
            if not current_expected or current_expected["state"] != expected["state"]:
                return
            cur_st = self.hass.states.get(entity_id)
            if cur_st is not None and cur_st.state == expected["state"]:
                return

            await self._async_apply_state(
                entity_id, expected["state"], expected.get("attrs") or {}
            )

            self.blocked_interferences += 1
            now_hhmm = _to_local_hhmm(_utc_now())
            target_de = "AN" if expected["state"] == "on" else "AUS"
            unwanted_de = "AN" if unwanted_state == "on" else "AUS"
            self.last_interference = (
                f"{now_hhmm} · {friendly_name} (extern {unwanted_de} → korrigiert auf {target_de})"
            )
            self.hass.bus.async_fire(
                EVENT_PRESENCE_INTERFERENCE_BLOCKED,
                {
                    "entity_id": entity_id,
                    "name": friendly_name,
                    "blocked_state": unwanted_state,
                    "restored_state": expected["state"],
                },
            )
            self._on_update()
        except asyncio.CancelledError:
            return
        finally:
            self._enforce_tasks.pop(entity_id, None)

    async def _async_apply_state(
        self, entity_id: str, target_state: str, attrs: dict[str, Any]
    ) -> None:
        """Schaltet eine Lampe oder einen Schalter mit eigenem Simulation-Context."""
        domain = entity_id.split(".", 1)[0]
        if domain not in ALLOWED_PRESENCE_DOMAINS:
            return

        service = "turn_on" if target_state == "on" else "turn_off"
        service_data: dict[str, Any] = {"entity_id": entity_id}

        if domain == "light" and target_state == "on" and attrs:
            if "brightness" in attrs:
                service_data["brightness"] = attrs["brightness"]
            if "color_temp_kelvin" in attrs:
                service_data["color_temp_kelvin"] = attrs["color_temp_kelvin"]
            elif "rgb_color" in attrs:
                service_data["rgb_color"] = attrs["rgb_color"]

        ctx = Context()
        self._own_context_ids.append(ctx.id)
        self._last_sim_action_ts[entity_id] = time_mod.monotonic()

        try:
            await self.hass.services.async_call(
                domain, service, service_data, blocking=False, context=ctx
            )
        except Exception as err:
            _LOGGER.warning(
                "Anwesenheitssimulation: %s.%s für %s fehlgeschlagen: %s",
                domain,
                service,
                entity_id,
                err,
            )

    async def _async_detect_motion_automations(self) -> list[str]:
        """Sammelt Ziel-Tokens (Entity/Device/Area) und findet passende Bewegungsmelder-Automationen."""
        if not self.auto_pause_motion or not self.entities:
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

        motion_entity_ids: set[str] = set()
        for st in self.hass.states.async_all("binary_sensor"):
            dc = str((st.attributes or {}).get("device_class") or "").lower()
            if dc in ("motion", "occupancy", "presence"):
                motion_entity_ids.add(st.entity_id)

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
            detect_motion_automations_from_yaml,
            auto_yaml,
            target_tokens,
            motion_entity_ids,
            auto_id_map,
            auto_alias_map,
        )

    async def _async_pause_interfering_automations(self) -> None:
        """Pausiert ausgewählte + automatisch erkannte Bewegungsmelder-Automationen inkl. stop_actions."""
        auto_detected = await self._async_detect_motion_automations()
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
                    "Konnte Bewegungsmelder-Automation %s nicht pausieren: %s",
                    auto_eid,
                    err,
                )

        self.paused_automations = paused

    async def _async_restore_paused_automations(self) -> None:
        """Aktiviert alle von der Simulation pausierten Bewegungsmelder-Automationen wieder."""
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
                    "Konnte Automation %s nicht wieder aktivieren: %s", auto_eid, err
                )

    def _cancel_all_timers(self) -> None:
        for unsub in self._unsub_timers:
            unsub()
        self._unsub_timers.clear()
        if self._unsub_replan_timer is not None:
            self._unsub_replan_timer()
            self._unsub_replan_timer = None
        for task in list(self._enforce_tasks.values()):
            if not task.done():
                task.cancel()
        self._enforce_tasks.clear()

    async def _async_plan_window(self, apply_initial: bool = True) -> None:
        """Plant die nächsten 24 Stunden anhand des Verlaufs von vor 14 Tagen (± jitter)."""
        self._cancel_all_timers()
        now = _utc_now()
        now_ts = now.timestamp()

        # Ergänzend Recorder für das genaue 14-Tage-Fenster abfragen
        rec_14 = await self._async_query_recorder_history(
            self.entities,
            now - timedelta(days=DEFAULT_PRESENCE_DAYS_OFFSET + 1),
            now - timedelta(days=DEFAULT_PRESENCE_DAYS_OFFSET - 1),
        )

        # Prüfen, welche Entitäten 14-Tage-Daten haben; falls nicht, 7-Tage-Fallback prüfen
        rec_7: dict[str, list[dict[str, Any]]] | None = None
        used_14 = 0
        used_7 = 0
        used_none = 0
        all_planned: list[dict[str, Any]] = []

        for eid in self.entities:
            combined_events = list(self._history.get(eid, []))
            if eid in rec_14:
                existing_keys = {(int(e["ts"]), e["state"]) for e in combined_events}
                for ev in rec_14[eid]:
                    k = (int(ev["ts"]), ev["state"])
                    if k not in existing_keys:
                        combined_events.append(ev)
                        existing_keys.add(k)

            init_st, planned = compute_entity_replay_plan(
                combined_events,
                now_ts=now_ts,
                window_hours=24.0,
                days_offset=DEFAULT_PRESENCE_DAYS_OFFSET,
                jitter_minutes=self.jitter_minutes,
            )

            if init_st is not None or planned:
                used_14 += 1
            else:
                # Bridge-Fallback auf vor 7 Tagen (gleicher Wochentag), solange 14-Tage-Verlauf noch wächst
                if rec_7 is None:
                    rec_7 = await self._async_query_recorder_history(
                        self.entities,
                        now - timedelta(days=8),
                        now - timedelta(days=6),
                    )
                if eid in rec_7:
                    existing_keys = {(int(e["ts"]), e["state"]) for e in combined_events}
                    for ev in rec_7[eid]:
                        k = (int(ev["ts"]), ev["state"])
                        if k not in existing_keys:
                            combined_events.append(ev)
                            existing_keys.add(k)
                init_st, planned = compute_entity_replay_plan(
                    combined_events,
                    now_ts=now_ts,
                    window_hours=24.0,
                    days_offset=7,
                    jitter_minutes=self.jitter_minutes,
                )
                if init_st is not None or planned:
                    used_7 += 1
                else:
                    used_none += 1

            # Anfangszustand setzen (oder aktuellen Zustand einfrieren, wenn keine Historie vorhanden)
            if init_st is not None:
                self.expected_states[eid] = init_st
                if apply_initial:
                    await self._async_apply_state(
                        eid, init_st["state"], init_st.get("attrs") or {}
                    )
            else:
                cur = self.hass.states.get(eid)
                if cur and cur.state in ("on", "off"):
                    dom = eid.split(".", 1)[0]
                    self.expected_states[eid] = {
                        "state": cur.state,
                        "attrs": (
                            _extract_light_attrs(dom, cur.attributes or {})
                            if cur.state == "on"
                            else {}
                        ),
                    }

            friendly = eid
            cur_st = self.hass.states.get(eid)
            if cur_st and cur_st.attributes.get("friendly_name"):
                friendly = str(cur_st.attributes["friendly_name"])

            for item in planned:
                sched_dt = datetime.fromtimestamp(item["sched_ts"], tz=timezone.utc)
                all_planned.append(
                    {
                        **item,
                        "entity_id": eid,
                        "name": friendly,
                        "time_str": _to_local_str(sched_dt),
                        "hhmm": _to_local_hhmm(sched_dt),
                    }
                )

        all_planned.sort(key=lambda item: float(item["sched_ts"]))
        self.scheduled_events = all_planned

        # Datenquelle verständlich ausweisen
        span_days = self.get_history_span_days()
        if used_14 > 0 and used_7 == 0:
            self.data_source_info = "Verlauf von vor 14 Tagen"
        elif used_14 > 0 and used_7 > 0:
            self.data_source_info = f"14 Tage ({used_14}) + 7-Tage-Fallback ({used_7})"
        elif used_7 > 0:
            self.data_source_info = (
                f"Fallback: vor 7 Tagen (14-Tage-Verlauf: {span_days}/14 Tage)"
            )
        else:
            self.data_source_info = (
                f"Noch keine Verlaufsdaten (zeichnet auf: {span_days}/14 Tage)"
            )

        # Alle geplanten Schaltvorgänge mit HA-UTC-Timern einplanen
        for ev in all_planned:
            fire_dt = datetime.fromtimestamp(float(ev["sched_ts"]), tz=timezone.utc)

            async def _execute_event(_now: datetime, ev_data: dict = ev) -> None:
                if not self.enabled:
                    return
                eid = ev_data["entity_id"]
                self.expected_states[eid] = {
                    "state": ev_data["state"],
                    "attrs": dict(ev_data.get("attrs") or {}),
                }
                await self._async_apply_state(
                    eid, ev_data["state"], ev_data.get("attrs") or {}
                )
                state_de = "AN" if ev_data["state"] == "on" else "AUS"
                self.last_action_info = (
                    f"{_to_local_hhmm(_utc_now())} · {ev_data['name']} → {state_de}"
                )
                self.scheduled_events = [
                    x
                    for x in self.scheduled_events
                    if not (
                        x["entity_id"] == eid and x["sched_ts"] == ev_data["sched_ts"]
                    )
                ]
                self._on_update()

            self._unsub_timers.append(
                async_track_point_in_utc_time(self.hass, _execute_event, fire_dt)
            )

        # Rollierend nach 23,5 Stunden neu planen für mehrwöchige Urlaube
        async def _replan(_now: datetime) -> None:
            if self.enabled:
                await self._async_plan_window(apply_initial=False)
                self._on_update()

        self._unsub_replan_timer = async_track_point_in_utc_time(
            self.hass, _replan, now + timedelta(hours=23, minutes=30)
        )

    async def async_turn_on(self, is_restore: bool = False) -> None:
        """Aktiviert den Hauptschalter: pausiert Bewegungsmelder, startet 1:1-Replay & State Guard."""
        if not self.entities:
            raise HomeAssistantError(
                "Bitte wähle zuerst unter Konfigurieren → Anwesenheitssimulation "
                "mindestens eine Lampe oder einen Schalter aus."
            )

        await self._async_load_history()
        self.enabled = True
        if not is_restore:
            self.blocked_interferences = 0
            self.last_interference = ""

        # Zuerst Bewegungsmelder-Automationen pausieren, damit sie beim Einschalten nicht stören
        await self._async_pause_interfering_automations()
        await self._async_plan_window(apply_initial=True)
        self._attach_state_listener()
        self._on_update()

    async def async_turn_off(self) -> None:
        """Deaktiviert den Hauptschalter und stellt alle pausierten Bewegungsmelder-Automationen wieder her."""
        self.enabled = False
        self._cancel_all_timers()
        self.scheduled_events = []
        self.expected_states = {}
        await self._async_restore_paused_automations()
        self._attach_state_listener()
        self._on_update()

    async def async_shutdown(self) -> None:
        """Räumt Timer und Listener beim Entladen/Neustart sauber auf (ohne Urlaubs-Status zu löschen)."""
        self._cancel_all_timers()
        if self._unsub_state_listener is not None:
            self._unsub_state_listener()
            self._unsub_state_listener = None
        if self._unsub_save_timer is not None:
            self._unsub_save_timer()
            self._unsub_save_timer = None
        if self._history_dirty:
            await self.async_save_history()

    def get_status_snapshot(self) -> dict[str, Any]:
        """Liefert kompakten Status + Attribute für Sensor und Dashboard-Karte."""
        next_ev = self.scheduled_events[0] if self.scheduled_events else None
        next_str = ""
        if next_ev:
            st_de = "AN" if next_ev["state"] == "on" else "AUS"
            sign = "+" if next_ev["offset_min"] >= 0 else ""
            next_str = (
                f"{next_ev['hhmm']} · {next_ev['name']} → {st_de} "
                f"({sign}{next_ev['offset_min']} Min)"
            )

        upcoming_formatted = []
        upcoming_structured = []
        for ev in self.scheduled_events[:15]:
            st_de = "AN" if ev["state"] == "on" else "AUS"
            sign = "+" if ev["offset_min"] >= 0 else ""
            upcoming_formatted.append(
                f"{ev['time_str']} · {ev['name']} → {st_de} ({sign}{ev['offset_min']} Min)"
            )
            upcoming_structured.append(
                {
                    "time": ev["time_str"],
                    "hhmm": ev["hhmm"],
                    "name": ev["name"],
                    "entity_id": ev["entity_id"],
                    "state": ev["state"],
                    "state_de": st_de,
                    "offset_min": ev["offset_min"],
                }
            )

        if not self.entities:
            status_text = "Keine Geräte gewählt"
        elif not self.enabled:
            status_text = "Inaktiv"
        elif next_ev:
            status_text = f"Aktiv · Nächste: {next_ev['hhmm']}"
        else:
            status_text = "Aktiv (Wächter läuft)"

        entity_names: list[str] = []
        for eid in self.entities:
            st = self.hass.states.get(eid)
            entity_names.append(
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
            "status": status_text,
            "entities": list(self.entities),
            "entity_names": entity_names,
            "entities_count": len(self.entities),
            "days_offset": DEFAULT_PRESENCE_DAYS_OFFSET,
            "jitter_minutes": self.jitter_minutes,
            "auto_pause_motion": self.auto_pause_motion,
            "data_source": self.data_source_info,
            "history_days": self.get_history_span_days(),
            "next_event": next_str,
            "scheduled_count": len(self.scheduled_events),
            "upcoming_formatted": upcoming_formatted,
            "upcoming": upcoming_structured,
            "paused_automations": list(self.paused_automations),
            "paused_automation_names": paused_names,
            "blocked_interferences": self.blocked_interferences,
            "last_interference": self.last_interference,
            "last_action": self.last_action_info,
        }
