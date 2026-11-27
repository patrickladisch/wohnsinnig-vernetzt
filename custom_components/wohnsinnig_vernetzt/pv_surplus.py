"""PV-Überschuss & Solar-Manager mit beliebig vielen Aktionen, Wolkenfilter & Hysterese."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
import re
import time as time_mod
from typing import Any
import uuid

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import (
    DEFAULT_PV_BATTERY_ENTITY,
    DEFAULT_PV_INVERT_SURPLUS,
    DEFAULT_PV_SURPLUS_ENTITY,
    DOMAIN,
    EVENT_PV_ACTION_STOPPED,
    EVENT_PV_ACTION_TRIGGERED,
    PV_ACTION_ACTIVATE_SCENE,
    PV_ACTION_PRESS_BUTTON,
    PV_ACTION_RUN_SCRIPT,
    PV_ACTION_TRIGGER_AUTOMATION,
    PV_ACTION_TURN_ON,
    PV_TRIGGER_BATTERY,
    PV_TRIGGER_BOTH,
    PV_TRIGGER_EITHER,
    PV_TRIGGER_SURPLUS,
)

_LOGGER = logging.getLogger(__name__)

TURN_ON_DOMAINS = ("switch", "input_boolean", "light", "fan", "climate", "humidifier")
ALL_TARGET_DOMAINS = (
    "switch",
    "button",
    "script",
    "scene",
    "automation",
    "input_boolean",
    "light",
    "fan",
    "climate",
    "humidifier",
)

VALID_TRIGGER_MODES = (
    PV_TRIGGER_SURPLUS,
    PV_TRIGGER_BATTERY,
    PV_TRIGGER_EITHER,
    PV_TRIGGER_BOTH,
)
VALID_ACTION_TYPES = (
    PV_ACTION_TURN_ON,
    PV_ACTION_PRESS_BUTTON,
    PV_ACTION_RUN_SCRIPT,
    PV_ACTION_ACTIVATE_SCENE,
    PV_ACTION_TRIGGER_AUTOMATION,
)

_PV_POWER_HINTS = (
    "pv",
    "solar",
    "grid",
    "netz",
    "einspeis",
    "export",
    "surplus",
    "ueberschuss",
    "überschuss",
    "feed",
    "inverter",
    "wechselrichter",
    "balkon",
    "fronius",
    "sma",
    "huawei",
    "sungrow",
    "kostal",
    "growatt",
    "solaredge",
    "victron",
    "goodwe",
    "senec",
    "ecoflow",
    "shelly_3em",
    "power",
)
_PV_BATTERY_HINTS = (
    "pv",
    "solar",
    "speicher",
    "akku",
    "storage",
    "soc",
    "house_battery",
    "hausakku",
    "inverter",
    "wechselrichter",
    "byd",
    "luna",
    "sungrow",
    "fronius",
    "sma",
    "victron",
    "senec",
    "powerwall",
    "battery",
)


def _local_now() -> datetime:
    try:
        from homeassistant.util import dt as dt_util

        return dt_util.now()
    except Exception:
        return datetime.now().astimezone()


def _today_str() -> str:
    return _local_now().strftime("%Y-%m-%d")


def _parse_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("%", "").replace(",", ".")
        match = re.match(r"^-?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def read_surplus_watts(state_obj: Any, invert: bool = False) -> float | None:
    """Liest die aktuelle PV-Überschussleistung in Watt (rechnet kW/mW/MW automatisch um)."""
    if state_obj is None:
        return None
    raw_state = str(getattr(state_obj, "state", "") or "").strip()
    if not raw_state or raw_state.lower() in ("unavailable", "unknown", "none"):
        return None

    val = _parse_float(raw_state)
    if val is None:
        return None

    attrs = getattr(state_obj, "attributes", {}) or {}
    unit = str(attrs.get("unit_of_measurement") or "W").strip().lower()
    if unit == "kw":
        val *= 1000.0
    elif unit == "mw":
        # Unterscheidung mW (Milliwatt) vs MW (Megawatt) anhand originaler Groß-/Kleinschreibung
        raw_unit = str(attrs.get("unit_of_measurement") or "W").strip()
        if raw_unit == "MW":
            val *= 1_000_000.0
        else:
            val /= 1000.0

    if invert:
        val = -val
    return round(val, 1)


def read_battery_soc(state_obj: Any) -> float | None:
    """Liest den PV-Akku-Ladestand (0–100 %)."""
    if state_obj is None:
        return None
    raw_state = str(getattr(state_obj, "state", "") or "").strip()
    if not raw_state or raw_state.lower() in ("unavailable", "unknown", "none"):
        return None
    val = _parse_float(raw_state)
    if val is None or not (0.0 <= val <= 100.0):
        return None
    return round(val, 1)


def normalize_sensor_entity(raw: object) -> str:
    val = str(raw or "").strip()
    if val.startswith(("sensor.", "input_number.")):
        return val
    return ""


def infer_action_type(target_entity: str, requested: str = "") -> str:
    """Ermittelt einen gültigen Aktionstyp passend zur Ziel-Entität."""
    req = str(requested or "").strip().lower()
    if req in VALID_ACTION_TYPES:
        return req
    dom = target_entity.split(".", 1)[0].lower() if "." in target_entity else ""
    if dom == "button":
        return PV_ACTION_PRESS_BUTTON
    if dom == "script":
        return PV_ACTION_RUN_SCRIPT
    if dom == "scene":
        return PV_ACTION_ACTIVATE_SCENE
    if dom == "automation":
        return PV_ACTION_TRIGGER_AUTOMATION
    return PV_ACTION_TURN_ON


def normalize_pv_rule(raw: dict[str, Any], index: int = 1) -> dict[str, Any] | None:
    """Validiert und normalisiert eine einzelne PV-Überschuss-Aktion."""
    if not isinstance(raw, dict):
        return None

    target_entity = str(raw.get("target_entity") or "").strip()
    if "." not in target_entity:
        return None
    dom = target_entity.split(".", 1)[0].lower()
    if dom not in ALL_TARGET_DOMAINS:
        return None

    rule_id = str(raw.get("id") or "").strip()
    if not rule_id:
        rule_id = f"pv_{uuid.uuid4().hex[:8]}"

    name = str(raw.get("name") or "").strip()
    if not name:
        name = f"Aktion {index}"

    trigger_mode = str(raw.get("trigger_mode") or PV_TRIGGER_EITHER).strip().lower()
    if trigger_mode not in VALID_TRIGGER_MODES:
        trigger_mode = PV_TRIGGER_EITHER

    action_type = infer_action_type(target_entity, str(raw.get("action_type") or ""))

    def _safe_int(key: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(hi, int(round(float(raw.get(key, default))))))
        except (TypeError, ValueError):
            return default

    min_surplus_w = _safe_int("min_surplus_w", 500, 0, 50000)
    min_battery_soc = _safe_int("min_battery_soc", 80, 1, 100)
    delay_on_minutes = _safe_int("delay_on_minutes", 2, 0, 60)

    auto_off = bool(raw.get("auto_off", False)) and action_type == PV_ACTION_TURN_ON
    off_surplus_w = _safe_int("off_surplus_w", 0, -20000, 50000)
    off_battery_soc = _safe_int("off_battery_soc", max(5, min_battery_soc - 10), 0, 100)
    delay_off_minutes = _safe_int("delay_off_minutes", 5, 0, 60)

    return {
        "id": rule_id[:48],
        "name": name[:80],
        "enabled": bool(raw.get("enabled", True)),
        "trigger_mode": trigger_mode,
        "min_surplus_w": min_surplus_w,
        "min_battery_soc": min_battery_soc,
        "delay_on_minutes": delay_on_minutes,
        "action_type": action_type,
        "target_entity": target_entity,
        "auto_off": auto_off,
        "off_surplus_w": off_surplus_w,
        "off_battery_soc": off_battery_soc,
        "delay_off_minutes": delay_off_minutes,
        "once_per_day": bool(raw.get("once_per_day", False)),
    }


def normalize_pv_rules(raw: object) -> list[dict[str, Any]]:
    """Normalisiert eine geordnete Liste von PV-Überschuss-Aktionen."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(raw, start=1):
        norm = normalize_pv_rule(item, index=idx)
        if norm is None:
            continue
        if norm["id"] in seen_ids:
            norm["id"] = f"{norm['id'][:38]}_{idx}"
        seen_ids.add(norm["id"])
        result.append(norm)
    return result


def evaluate_on_condition(
    rule: dict[str, Any],
    surplus_w: float | None,
    battery_soc: float | None,
) -> tuple[bool, str]:
    """Prüft, ob die Einschalt-/Auslösebedingung einer Regel erfüllt ist."""
    mode = rule["trigger_mode"]
    surplus_ok = surplus_w is not None and surplus_w >= rule["min_surplus_w"]
    battery_ok = battery_soc is not None and battery_soc >= rule["min_battery_soc"]

    if mode == PV_TRIGGER_SURPLUS:
        return surplus_ok, (
            f"Überschuss {int(round(surplus_w))} W ≥ {rule['min_surplus_w']} W"
            if surplus_ok and surplus_w is not None
            else ""
        )

    if mode == PV_TRIGGER_BATTERY:
        return battery_ok, (
            f"PV-Akku {int(round(battery_soc))} % ≥ {rule['min_battery_soc']} %"
            if battery_ok and battery_soc is not None
            else ""
        )

    if mode == PV_TRIGGER_BOTH:
        ok = surplus_ok and battery_ok
        return ok, (
            f"Überschuss {int(round(surplus_w))} W & Akku {int(round(battery_soc))} %"
            if ok and surplus_w is not None and battery_soc is not None
            else ""
        )

    # PV_TRIGGER_EITHER (Überschuss ODER PV-Akku)
    if surplus_ok and battery_ok and surplus_w is not None and battery_soc is not None:
        return True, f"Überschuss {int(round(surplus_w))} W & Akku {int(round(battery_soc))} %"
    if surplus_ok and surplus_w is not None:
        return True, f"Überschuss {int(round(surplus_w))} W ≥ {rule['min_surplus_w']} W"
    if battery_ok and battery_soc is not None:
        return True, f"PV-Akku {int(round(battery_soc))} % ≥ {rule['min_battery_soc']} %"
    return False, ""


def evaluate_off_condition(
    rule: dict[str, Any],
    surplus_w: float | None,
    battery_soc: float | None,
) -> bool:
    """Prüft die Abschaltbedingung (mit Hysterese), sofern auto_off aktiv ist."""
    if not rule.get("auto_off") or rule.get("action_type") != PV_ACTION_TURN_ON:
        return False

    mode = rule["trigger_mode"]
    surplus_low = surplus_w is not None and surplus_w <= rule["off_surplus_w"]
    battery_low = battery_soc is not None and battery_soc <= rule["off_battery_soc"]

    if mode == PV_TRIGGER_SURPLUS:
        return surplus_low
    if mode == PV_TRIGGER_BATTERY:
        return battery_low
    if mode == PV_TRIGGER_BOTH:
        return surplus_low or battery_low

    # PV_TRIGGER_EITHER: Nur abschalten, wenn KEINE der verfügbaren Quellen mehr ausreicht!
    has_any_sensor = surplus_w is not None or battery_soc is not None
    if not has_any_sensor:
        return False
    s_down = True if surplus_w is None else surplus_low
    b_down = True if battery_soc is None else battery_low
    return s_down and b_down


def get_pv_sensor_candidates(
    hass: HomeAssistant,
    current_surplus: str = "",
    current_battery: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Findet Leistungs-Sensoren (W/kW) und PV-Akku-Sensoren (%) für die Konfigurations-Dropdowns."""
    power_sensors: list[dict[str, Any]] = []
    battery_sensors: list[dict[str, Any]] = []
    seen_p: set[str] = set()
    seen_b: set[str] = set()

    for st in hass.states.async_all(["sensor", "input_number"]):
        eid = st.entity_id
        if f".{DOMAIN}" in eid:
            continue
        attrs = st.attributes or {}
        if attrs.get("restored") is True:
            continue

        dc = str(attrs.get("device_class") or "").lower()
        unit = str(attrs.get("unit_of_measurement") or "").strip()
        unit_low = unit.lower()
        friendly = str(attrs.get("friendly_name") or eid).strip()
        low_blob = f"{eid} {friendly}".lower()

        # Power / Surplus sensor candidate
        if dc == "power" or unit_low in ("w", "kw", "mw") or eid == current_surplus:
            is_pv_hint = any(h in low_blob for h in _PV_POWER_HINTS)
            tier = 0 if is_pv_hint else 1
            val_preview = f"{st.state} {unit}".strip() if st.state not in ("unknown", "unavailable") else st.state
            power_sensors.append(
                {
                    "entity_id": eid,
                    "name": friendly,
                    "tier": tier,
                    "preview": val_preview,
                    "label": f"{'☀️ ' if tier == 0 else '⚡ '}{friendly} ({val_preview})",
                }
            )
            seen_p.add(eid)

        # Battery SoC sensor candidate
        if (
            dc == "battery"
            or (unit == "%" and any(h in low_blob for h in _PV_BATTERY_HINTS))
            or eid == current_battery
        ):
            is_pv_bat = any(
                h in low_blob
                for h in ("pv", "solar", "speicher", "hausakku", "storage", "soc", "byd", "luna", "sungrow", "fronius", "sma", "victron", "senec", "powerwall", "wechselrichter", "inverter")
            )
            tier = 0 if is_pv_bat else 1
            val_preview = f"{st.state} {unit}".strip() if st.state not in ("unknown", "unavailable") else st.state
            battery_sensors.append(
                {
                    "entity_id": eid,
                    "name": friendly,
                    "tier": tier,
                    "preview": val_preview,
                    "label": f"{'🔋 ' if tier == 0 else '🪫 '}{friendly} ({val_preview})",
                }
            )
            seen_b.add(eid)

    if current_surplus and current_surplus not in seen_p:
        power_sensors.append(
            {
                "entity_id": current_surplus,
                "name": current_surplus,
                "tier": 2,
                "preview": "nicht gefunden",
                "label": f"⚡ {current_surplus}",
            }
        )
    if current_battery and current_battery not in seen_b:
        battery_sensors.append(
            {
                "entity_id": current_battery,
                "name": current_battery,
                "tier": 2,
                "preview": "nicht gefunden",
                "label": f"🔋 {current_battery}",
            }
        )

    power_sensors.sort(key=lambda x: (x["tier"], x["name"].lower(), x["entity_id"]))
    battery_sensors.sort(key=lambda x: (x["tier"], x["name"].lower(), x["entity_id"]))
    return power_sensors, battery_sensors


def get_pv_target_candidates(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Liefert alle steuerbaren Ziel-Entitäten für PV-Überschuss-Aktionen."""
    items: list[dict[str, Any]] = []
    for st in hass.states.async_all(list(ALL_TARGET_DOMAINS)):
        eid = st.entity_id
        if f".{DOMAIN}" in eid:
            continue
        attrs = st.attributes or {}
        if attrs.get("restored") is True:
            continue
        dom = eid.split(".", 1)[0]
        friendly = str(attrs.get("friendly_name") or eid).strip()
        items.append(
            {
                "entity_id": eid,
                "domain": dom,
                "name": friendly,
                "state": st.state,
            }
        )
    items.sort(key=lambda x: (x["name"].lower(), x["entity_id"]))
    return items


class PvSurplusManager:
    """Überwacht PV-Überschuss & PV-Akku und steuert beliebig viele Aktionen mit Wolkenfilter."""

    def __init__(
        self,
        hass: HomeAssistant,
        on_update: Callable[[], None],
        on_persist: Callable[[], Any],
        surplus_entity: str = DEFAULT_PV_SURPLUS_ENTITY,
        battery_entity: str = DEFAULT_PV_BATTERY_ENTITY,
        invert_surplus: bool = DEFAULT_PV_INVERT_SURPLUS,
        rules: list[dict[str, Any]] | None = None,
    ) -> None:
        self.hass = hass
        self._on_update = on_update
        self._on_persist = on_persist

        self.surplus_entity: str = normalize_sensor_entity(surplus_entity)
        self.battery_entity: str = normalize_sensor_entity(battery_entity)
        self.invert_surplus: bool = bool(invert_surplus)
        self.rules: list[dict[str, Any]] = normalize_pv_rules(rules or [])

        # Laufzeit- & Persistenz-Zustände
        self.enabled: bool = False
        self.triggered_today: dict[str, str] = {}  # {rule_id: "YYYY-MM-DD"}
        self.active_rule_ids: set[str] = set()  # aktuell durch PV eingeschaltete turn_on-Regeln
        self.last_triggered_at: dict[str, str] = {}  # {rule_id: "HH:MM"}
        self.last_event_info: str = ""

        # Wolkenfilter-Zeitstempel (monotonic)
        self._on_met_since: dict[str, float] = {}
        self._off_met_since: dict[str, float] = {}
        self._unsub_state: CALLBACK_TYPE | None = None
        self._unsub_interval: CALLBACK_TYPE | None = None

    async def _persist(self) -> None:
        res = self._on_persist()
        if asyncio.iscoroutine(res):
            await res

    def get_current_surplus_w(self) -> float | None:
        if not self.surplus_entity:
            return None
        return read_surplus_watts(
            self.hass.states.get(self.surplus_entity), invert=self.invert_surplus
        )

    def get_current_battery_soc(self) -> float | None:
        if not self.battery_entity:
            return None
        return read_battery_soc(self.hass.states.get(self.battery_entity))

    def _cleanup_old_daily_flags(self) -> bool:
        today = _today_str()
        stale = [rid for rid, day in self.triggered_today.items() if day != today]
        for rid in stale:
            self.triggered_today.pop(rid, None)
        return bool(stale)

    def _attach_listeners(self) -> None:
        self._detach_listeners()

        watched = [e for e in (self.surplus_entity, self.battery_entity) if e]
        if watched:
            async def _on_sensor_change(_event: Event) -> None:
                await self.async_evaluate()

            self._unsub_state = async_track_state_change_event(
                self.hass, watched, _on_sensor_change
            )

        if self.enabled and self.rules:
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

    async def async_initialize(
        self,
        was_enabled: bool = False,
        persisted_triggered_today: dict[str, str] | None = None,
        persisted_active_rule_ids: list[str] | None = None,
    ) -> None:
        """Lädt gespeicherte Tageszähler & aktive Regeln und startet die PV-Überwachung."""
        valid_ids = {r["id"] for r in self.rules}
        if isinstance(persisted_triggered_today, dict):
            today = _today_str()
            self.triggered_today = {
                str(k): str(v)
                for k, v in persisted_triggered_today.items()
                if str(k) in valid_ids and str(v) == today
            }
        if isinstance(persisted_active_rule_ids, list):
            self.active_rule_ids = {
                str(rid) for rid in persisted_active_rule_ids if str(rid) in valid_ids
            }

        self.enabled = bool(was_enabled) and bool(self.rules)
        self._attach_listeners()
        if self.enabled:
            await self.async_evaluate()
        else:
            self._on_update()

    async def async_set_enabled(self, enabled: bool) -> None:
        """Hauptschalter für die PV-Überschuss-Steuerung."""
        if enabled and not self.rules:
            raise HomeAssistantError(
                "Bitte füge zuerst unter „Konfiguration öffnen“ mindestens eine PV-Aktion hinzu."
            )
        if enabled and not (self.surplus_entity or self.battery_entity):
            raise HomeAssistantError(
                "Bitte wähle zuerst unter „Konfiguration öffnen“ einen PV-Überschuss- oder PV-Akku-Sensor aus."
            )

        self.enabled = bool(enabled)
        self._on_met_since.clear()
        self._off_met_since.clear()
        self._attach_listeners()
        await self._persist()
        if self.enabled:
            await self.async_evaluate()
        else:
            self._on_update()

    async def async_reset_daily_triggers(self) -> None:
        """Setzt alle „1× pro Tag“-Merker zurück."""
        self.triggered_today = {}
        await self._persist()
        if self.enabled:
            await self.async_evaluate()
        else:
            self._on_update()

    async def _async_execute_action(
        self, rule: dict[str, Any], reason: str, manual: bool = False
    ) -> bool:
        """Führt die konfigurierte Ziel-Aktion einer Regel in Home Assistant aus."""
        target = rule["target_entity"]
        dom = target.split(".", 1)[0]
        action_type = rule["action_type"]

        # Bei turn_on prüfen, ob das Ziel bereits eingeschaltet ist
        if action_type == PV_ACTION_TURN_ON:
            cur = self.hass.states.get(target)
            if cur is not None and cur.state == "on" and not manual:
                self.active_rule_ids.add(rule["id"])
                return False

        try:
            if action_type == PV_ACTION_PRESS_BUTTON or dom == "button":
                await self.hass.services.async_call(
                    "button", "press", {"entity_id": target}, blocking=False
                )
            elif action_type == PV_ACTION_RUN_SCRIPT or dom == "script":
                await self.hass.services.async_call(
                    "script", "turn_on", {"entity_id": target}, blocking=False
                )
            elif action_type == PV_ACTION_ACTIVATE_SCENE or dom == "scene":
                await self.hass.services.async_call(
                    "scene", "turn_on", {"entity_id": target}, blocking=False
                )
            elif action_type == PV_ACTION_TRIGGER_AUTOMATION or dom == "automation":
                await self.hass.services.async_call(
                    "automation", "trigger", {"entity_id": target}, blocking=False
                )
            else:
                await self.hass.services.async_call(
                    dom, "turn_on", {"entity_id": target}, blocking=False
                )
        except Exception as err:
            _LOGGER.warning(
                "PV-Überschuss Aktion '%s' (%s) fehlgeschlagen: %s",
                rule["name"],
                target,
                err,
            )
            return False

        now_hhmm = _local_now().strftime("%H:%M")
        self.last_triggered_at[rule["id"]] = now_hhmm
        self.last_event_info = f"{now_hhmm} · {rule['name']} gestartet ({reason})"

        if action_type == PV_ACTION_TURN_ON:
            self.active_rule_ids.add(rule["id"])
        if rule.get("once_per_day"):
            self.triggered_today[rule["id"]] = _today_str()

        self.hass.bus.async_fire(
            EVENT_PV_ACTION_TRIGGERED,
            {
                "rule_id": rule["id"],
                "name": rule["name"],
                "target_entity": target,
                "action_type": action_type,
                "reason": reason,
                "manual": manual,
            },
        )
        return True

    async def _async_stop_action(self, rule: dict[str, Any]) -> bool:
        """Schaltet eine per PV eingeschaltete turn_on-Entität bei Unterschreiten wieder aus."""
        target = rule["target_entity"]
        dom = target.split(".", 1)[0]
        if rule["action_type"] != PV_ACTION_TURN_ON or dom not in TURN_ON_DOMAINS:
            self.active_rule_ids.discard(rule["id"])
            return False

        cur = self.hass.states.get(target)
        if cur is not None and cur.state == "off":
            self.active_rule_ids.discard(rule["id"])
            return False

        try:
            await self.hass.services.async_call(
                dom, "turn_off", {"entity_id": target}, blocking=False
            )
        except Exception as err:
            _LOGGER.warning(
                "PV-Überschuss Auto-Aus '%s' (%s) fehlgeschlagen: %s",
                rule["name"],
                target,
                err,
            )
            return False

        self.active_rule_ids.discard(rule["id"])
        now_hhmm = _local_now().strftime("%H:%M")
        self.last_event_info = f"{now_hhmm} · {rule['name']} automatisch ausgeschaltet"
        self.hass.bus.async_fire(
            EVENT_PV_ACTION_STOPPED,
            {
                "rule_id": rule["id"],
                "name": rule["name"],
                "target_entity": target,
            },
        )
        return True

    async def async_trigger_rule_now(self, rule_id: str) -> None:
        """Löst eine einzelne konfigurierte PV-Aktion sofort zum Testen aus."""
        for rule in self.rules:
            if rule["id"] == rule_id:
                await self._async_execute_action(
                    rule, reason="Manuell ausgelöst", manual=True
                )
                await self._persist()
                self._on_update()
                return
        raise HomeAssistantError("PV-Aktion nicht gefunden.")

    async def async_evaluate(self) -> dict[str, Any]:
        """Prüft alle aktivierten PV-Aktionen in Prioritätsreihenfolge inkl. Wolkenfilter."""
        dirty = self._cleanup_old_daily_flags()

        if not self.enabled or not self.rules:
            if dirty:
                await self._persist()
            self._on_update()
            return self.get_status_snapshot()

        surplus_w = self.get_current_surplus_w()
        battery_soc = self.get_current_battery_soc()
        now_mono = time_mod.monotonic()
        today = _today_str()

        for rule in self.rules:
            rid = rule["id"]
            if not rule.get("enabled", True):
                self._on_met_since.pop(rid, None)
                self._off_met_since.pop(rid, None)
                continue

            # Synchronisieren, falls ein Gerät manuell ausgeschaltet wurde
            if rid in self.active_rule_ids and rule["action_type"] == PV_ACTION_TURN_ON:
                cur_st = self.hass.states.get(rule["target_entity"])
                if cur_st is not None and cur_st.state == "off":
                    self.active_rule_ids.discard(rid)
                    dirty = True

            already_done_today = (
                bool(rule.get("once_per_day"))
                and self.triggered_today.get(rid) == today
            )
            is_active = rid in self.active_rule_ids

            # 1. Einschalten / Auslösen prüfen
            if not is_active and not already_done_today:
                on_ok, reason = evaluate_on_condition(rule, surplus_w, battery_soc)
                if on_ok:
                    self._off_met_since.pop(rid, None)
                    since = self._on_met_since.get(rid)
                    if since is None:
                        self._on_met_since[rid] = now_mono
                        since = now_mono
                    elapsed_min = (now_mono - since) / 60.0
                    if elapsed_min >= rule["delay_on_minutes"]:
                        self._on_met_since.pop(rid, None)
                        executed = await self._async_execute_action(rule, reason=reason)
                        if executed or rid in self.active_rule_ids:
                            dirty = True
                else:
                    self._on_met_since.pop(rid, None)

            # 2. Optionales Auto-Aus mit Hysterese & Nachlaufzeit prüfen
            elif is_active and rule.get("auto_off"):
                self._on_met_since.pop(rid, None)
                off_ok = evaluate_off_condition(rule, surplus_w, battery_soc)
                if off_ok:
                    since_off = self._off_met_since.get(rid)
                    if since_off is None:
                        self._off_met_since[rid] = now_mono
                        since_off = now_mono
                    elapsed_off_min = (now_mono - since_off) / 60.0
                    if elapsed_off_min >= rule["delay_off_minutes"]:
                        self._off_met_since.pop(rid, None)
                        if await self._async_stop_action(rule):
                            dirty = True
                else:
                    self._off_met_since.pop(rid, None)

        if dirty:
            await self._persist()
        self._on_update()
        return self.get_status_snapshot()

    async def async_shutdown(self) -> None:
        self._detach_listeners()

    def _describe_rule_trigger(self, rule: dict[str, Any]) -> str:
        mode = rule["trigger_mode"]
        w = rule["min_surplus_w"]
        b = rule["min_battery_soc"]
        if mode == PV_TRIGGER_SURPLUS:
            return f"☀️ ≥ {w} W"
        if mode == PV_TRIGGER_BATTERY:
            return f"🔋 ≥ {b} %"
        if mode == PV_TRIGGER_BOTH:
            return f"☀️ ≥ {w} W & 🔋 ≥ {b} %"
        return f"☀️ ≥ {w} W oder 🔋 ≥ {b} %"

    def get_status_snapshot(self) -> dict[str, Any]:
        """Liefert alle Live-Daten für Sensoren, Hauptschalter und Dashboard-Karte."""
        surplus_w = self.get_current_surplus_w()
        battery_soc = self.get_current_battery_soc()
        today = _today_str()
        now_mono = time_mod.monotonic()

        rules_status: list[dict[str, Any]] = []
        active_count = 0
        enabled_rules_count = 0

        for idx, rule in enumerate(self.rules, start=1):
            rid = rule["id"]
            if rule.get("enabled", True):
                enabled_rules_count += 1

            target_st = self.hass.states.get(rule["target_entity"])
            target_name = (
                str(target_st.attributes.get("friendly_name") or rule["target_entity"])
                if target_st
                else rule["target_entity"]
            )
            target_state = target_st.state if target_st else "unknown"

            is_active = rid in self.active_rule_ids and (
                rule["action_type"] != PV_ACTION_TURN_ON or target_state == "on"
            )
            if is_active:
                active_count += 1

            done_today = bool(rule.get("once_per_day")) and self.triggered_today.get(rid) == today

            if not rule.get("enabled", True):
                state_key = "paused"
                state_label = "Pausiert"
            elif is_active:
                if rid in self._off_met_since:
                    rem = max(
                        0,
                        int(
                            round(
                                rule["delay_off_minutes"]
                                - (now_mono - self._off_met_since[rid]) / 60.0
                            )
                        ),
                    )
                    state_key = "stopping"
                    state_label = f"Aktiv (Aus in ~{rem} Min)"
                else:
                    state_key = "active"
                    state_label = "Aktiv"
            elif done_today:
                state_key = "done"
                state_label = "Heute erledigt"
            elif rid in self._on_met_since:
                rem = max(
                    0,
                    int(
                        round(
                            rule["delay_on_minutes"]
                            - (now_mono - self._on_met_since[rid]) / 60.0
                        )
                    ),
                )
                state_key = "waiting"
                state_label = f"Startet in ~{rem} Min"
            else:
                state_key = "idle"
                state_label = "Bereit"

            rules_status.append(
                {
                    "id": rid,
                    "priority": idx,
                    "name": rule["name"],
                    "enabled": rule.get("enabled", True),
                    "trigger_summary": self._describe_rule_trigger(rule),
                    "action_type": rule["action_type"],
                    "target_entity": rule["target_entity"],
                    "target_name": target_name,
                    "auto_off": rule.get("auto_off", False),
                    "once_per_day": rule.get("once_per_day", False),
                    "state_key": state_key,
                    "state_label": state_label,
                    "last_triggered": self.last_triggered_at.get(rid, ""),
                }
            )

        if not self.rules:
            status_text = "Keine Aktionen"
        elif not self.surplus_entity and not self.battery_entity:
            status_text = "Sensoren wählen"
        elif not self.enabled:
            status_text = "Aus"
        elif active_count > 0:
            status_text = f"Aktiv · {active_count}/{enabled_rules_count} laufen"
        else:
            parts = []
            if surplus_w is not None:
                parts.append(f"{int(round(surplus_w))} W")
            if battery_soc is not None:
                parts.append(f"Akku {int(round(battery_soc))} %")
            status_text = f"Bereit · {' | '.join(parts)}" if parts else "Bereit"

        return {
            "enabled": self.enabled,
            "status": status_text,
            "surplus_entity": self.surplus_entity,
            "battery_entity": self.battery_entity,
            "invert_surplus": self.invert_surplus,
            "surplus_w": surplus_w,
            "battery_soc": battery_soc,
            "rules_count": len(self.rules),
            "enabled_rules_count": enabled_rules_count,
            "active_count": active_count,
            "rules_status": rules_status,
            "rules_summary": [
                f"{r['name']} ({r['trigger_summary']}) → {r['state_label']}"
                for r in rules_status
            ],
            "last_event": self.last_event_info,
        }
