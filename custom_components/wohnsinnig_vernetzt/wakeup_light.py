"""Wake-Up Light & Sonnenaufgangs-Steuerung mit automatischer Automations-Pause."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone
import logging
from pathlib import Path
from typing import Any

import yaml

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_point_in_utc_time

from .const import (
    DEFAULT_WAKEUP_AUTO_PAUSE,
    DEFAULT_WAKEUP_DAYS,
    DEFAULT_WAKEUP_DURATION,
    DEFAULT_WAKEUP_MODE,
    DEFAULT_WAKEUP_SUNRISE_COLOR,
    DEFAULT_WAKEUP_TIME,
    DOMAIN,
    EVENT_WAKEUP_CANCELLED,
    EVENT_WAKEUP_COMPLETED,
    EVENT_WAKEUP_STARTED,
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
    """Berechnet das nächste (start_dt, end_dt)-Zeitfenster in lokaler Zeitzone.

    - mode == 'reach_100': end_dt liegt auf target_time (an passendem Wochentag), start_dt = end_dt - duration.
    - mode == 'start_at': start_dt liegt auf target_time (an passendem Wochentag), end_dt = start_dt + duration.
    """
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
    """Verwaltet Zeitplan, sanftes Hochdimmen (0 % → 100 %) und Automations-Pause."""

    def __init__(
        self,
        hass: HomeAssistant,
        on_update: Callable[[], None],
        on_persist: Callable[[], Any],
        entities: list[str] | None = None,
        mode: str = DEFAULT_WAKEUP_MODE,
        wakeup_time: str = DEFAULT_WAKEUP_TIME,
        duration_minutes: int = DEFAULT_WAKEUP_DURATION,
        weekdays: str = DEFAULT_WAKEUP_DAYS,
        auto_pause: bool = DEFAULT_WAKEUP_AUTO_PAUSE,
        manual_pause_automations: list[str] | None = None,
        sunrise_color: bool = DEFAULT_WAKEUP_SUNRISE_COLOR,
    ) -> None:
        self.hass = hass
        self._on_update = on_update
        self._on_persist = on_persist

        self.entities: list[str] = normalize_wakeup_lights(entities)
        self.mode: str = (
            mode
            if mode in (WAKEUP_MODE_REACH_100, WAKEUP_MODE_START_AT)
            else DEFAULT_WAKEUP_MODE
        )
        self.wakeup_time: str = parse_wakeup_time(wakeup_time).strftime("%H:%M")
        self.duration_minutes: int = max(1, min(120, int(duration_minutes or DEFAULT_WAKEUP_DURATION)))
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
        self.active_start_dt: datetime | None = None
        self.active_end_dt: datetime | None = None
        self.last_run_info: str = ""
        self.paused_automations: list[str] = []

        self._unsub_schedule: CALLBACK_TYPE | None = None
        self._dim_task: asyncio.Task | None = None

    def get_time_obj(self) -> time:
        return parse_wakeup_time(self.wakeup_time)

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
        self._schedule_next()
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

    def _schedule_next(self) -> None:
        """Plant den nächsten automatischen Start des Sonnenaufgangs."""
        self._cancel_schedule()
        if not self.enabled or not self.entities:
            return

        now_local = _local_now()
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
        if not self.enabled and self.is_running:
            await self.async_stop(cancelled=True)
        self._schedule_next()
        await self._persist()
        self._on_update()

    async def async_set_mode(self, mode: str) -> None:
        if mode not in (WAKEUP_MODE_REACH_100, WAKEUP_MODE_START_AT):
            return
        self.mode = mode
        self._schedule_next()
        await self._persist()
        self._on_update()

    async def async_set_time(self, new_time: time) -> None:
        self.wakeup_time = time(new_time.hour, new_time.minute).strftime("%H:%M")
        self._schedule_next()
        await self._persist()
        self._on_update()

    async def async_set_duration(self, minutes: int) -> None:
        self.duration_minutes = max(1, min(120, int(minutes)))
        self._schedule_next()
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
        self._schedule_next()
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
        self, duration_override: int | None = None, is_scheduled: bool = False
    ) -> None:
        """Startet den Sonnenaufgang (0 % → 100 %) und pausiert alle betroffenen Automationen."""
        if not self.entities:
            raise HomeAssistantError(
                "Bitte wähle zuerst unter „Konfiguration öffnen“ mindestens eine Lampe aus."
            )

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
                "paused_automations": list(self.paused_automations),
                "scheduled": is_scheduled,
            },
        )

        self._dim_task = self.hass.async_create_task(
            self._async_run_sunrise_loop(dur_min)
        )
        self._on_update()

    async def _async_run_sunrise_loop(self, duration_minutes: int) -> None:
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
            self.last_run_info = f"Abgeschlossen um {_local_now().strftime('%H:%M')}"

            self.hass.bus.async_fire(
                EVENT_WAKEUP_COMPLETED,
                {
                    "entities": list(self.entities),
                    "duration_minutes": duration_minutes,
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
            self.is_running = False
            self.active_start_dt = None
            self.active_end_dt = None
            self._dim_task = None
            await self._async_restore_paused_automations()
            await self._persist()
            if self.enabled:
                self._schedule_next()
            self._on_update()

    async def async_stop(self, cancelled: bool = True) -> None:
        """Bricht einen laufenden Sonnenaufgang ab und reaktiviert alle pausierten Automationen."""
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
            if self.paused_automations:
                await self._async_restore_paused_automations()
                await self._persist()
            self._on_update()

    async def async_shutdown(self) -> None:
        """Beendet Timer & laufenden Task sauber beim Entladen/Neustart."""
        self._cancel_schedule()
        if self._dim_task and not self._dim_task.done():
            self._dim_task.cancel()
            try:
                await self._dim_task
            except asyncio.CancelledError:
                pass

    def get_status_snapshot(self) -> dict[str, Any]:
        """Liefert alle Statusdaten für Sensor und Dashboard-Karte."""
        now_local = _local_now()
        if self.is_running and self.active_start_dt and self.active_end_dt:
            start_str = self.active_start_dt.strftime("%H:%M")
            end_str = self.active_end_dt.strftime("%H:%M")
            next_start_full = self.active_start_dt.strftime("%d.%m. %H:%M")
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

        if not self.entities:
            status_text = "Keine Lampen gewählt"
        elif self.is_running:
            status_text = f"Dimmt · {self.current_brightness_percent} %"
        elif self.enabled:
            status_text = f"Geplant · {start_str} → {end_str}"
        else:
            status_text = "Aus"

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
            "mode": self.mode,
            "wakeup_time": self.wakeup_time,
            "duration_minutes": self.duration_minutes,
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
