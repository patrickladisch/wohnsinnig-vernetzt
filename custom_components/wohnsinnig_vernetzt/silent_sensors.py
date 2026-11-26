"""Lokaler „Stille Sensoren“-Wächter (Zigbee-Freeze-Erkennung)."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN

# Virtuelle / Software-Integrationen ohne physische Funk-Sensoren ausschließen
_IGNORED_PLATFORMS = {
    DOMAIN,
    "sun",
    "weather",
    "met",
    "backup",
    "hassio",
    "supervisor",
    "person",
    "zone",
    "calendar",
    "workday",
    "season",
    "moon",
    "time_date",
    "local_ip",
    "systemmonitor",
    "hacs",
    "radio_browser",
    "shopping_list",
    "tod",
    "utility_meter",
    "integration",
    "statistics",
    "derivative",
    "min_max",
    "group",
    "template",
    "history_stats",
    "trend",
    "threshold",
    "bayesian",
    "mold_indicator",
    "random",
    "demo",
    "version",
    "analytics",
    "uptime",
    "dnsip",
    "speedtestdotnet",
    "feedreader",
}

# Physische Sensor-Klassen für Sensoren ohne Device-Registry-Eintrag
_PHYSICAL_DEVICE_CLASSES = {
    "temperature",
    "humidity",
    "pressure",
    "atmospheric_pressure",
    "illuminance",
    "battery",
    "moisture",
    "motion",
    "occupancy",
    "door",
    "window",
    "opening",
    "vibration",
    "power",
    "energy",
    "voltage",
    "current",
    "carbon_dioxide",
    "carbon_monoxide",
    "pm25",
    "pm10",
    "gas",
    "smoke",
    "presence",
    "signal_strength",
    "volatile_organic_compounds",
    "aqi",
    "water",
    "sound",
    "tamper",
    "garage_door",
    "lock",
}

# Statische Metadaten-Sensoren (z. B. Firmware-Datum oder Aufzählungen) nicht allein werten
_IGNORED_DEVICE_CLASSES = {
    "date",
    "timestamp",
    "enum",
}

_MONITORED_DOMAINS = {"sensor", "binary_sensor"}


def _utc_now() -> datetime:
    try:
        from homeassistant.util import dt as dt_util

        return dt_util.utcnow()
    except Exception:
        return datetime.now(timezone.utc)


def _to_local_str(dt_val: datetime) -> str:
    try:
        from homeassistant.util import dt as dt_util

        return dt_util.as_local(dt_val).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return dt_val.strftime("%d.%m.%Y %H:%M")


def _format_silent_duration(hours: float) -> tuple[str, str]:
    """Gibt (lesbare Dauer, kompakte Dauer für Dropdown) zurück."""
    whole_hours = max(1, int(hours))
    if whole_hours < 48:
        return f"{whole_hours} h", f"{whole_hours}h"
    days, rem_hours = divmod(whole_hours, 24)
    if rem_hours == 0:
        return f"{days} T", f"{days}T"
    return f"{days} T {rem_hours} h", f"{days}T"


def _build_summary_text(devices: list[dict], max_len: int = 255) -> str:
    """Erstellt einen direkt lesbaren Sensor-Text mit allen stillen Sensoren (<= 255 Zeichen)."""
    if not devices:
        return "Alle aktiv"

    entries = [f"{d['name']} ({d['duration_formatted']})" for d in devices]
    full = ", ".join(entries)
    if len(full) <= max_len:
        return full

    chosen: list[str] = []
    for idx, entry in enumerate(entries):
        remaining = len(entries) - (idx + 1)
        tail = f", +{remaining} weitere" if remaining > 0 else ""
        candidate = ", ".join([*chosen, entry]) + tail
        if len(candidate) <= max_len:
            chosen.append(entry)
        else:
            break

    if not chosen:
        return entries[0][: max_len - 1].rstrip() + "…"

    rest = len(entries) - len(chosen)
    if rest > 0:
        return f"{', '.join(chosen)}, +{rest} weitere"
    return ", ".join(chosen)


def _get_state_timestamp(state: object) -> datetime | None:
    """Nutzt bevorzugt last_reported (HA 2024.4+), sonst last_updated."""
    ts = getattr(state, "last_reported", None) or getattr(state, "last_updated", None)
    if not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def run_silent_sensors_check(
    hass: HomeAssistant, silent_hours: int = 24
) -> dict:
    """Findet physische Sensoren/Geräte, die stumm eingefroren sind (nicht unavailable, aber > X h ohne Update).

    Gruppiert nach physischem Gerät (device_id): Meldet ein Zigbee-Mehrfachsensor z. B.
    Luftfeuchte oder LQI regelmäßig, gilt das Gerät als aktiv – selbst wenn ein Türkontakt
    oder Batteriewert tagelang unverändert bleibt.
    """
    now = _utc_now()
    ent_reg = None
    dev_reg = None
    try:
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)
    except Exception:
        pass

    # Pro Gerät sammeln wir: jüngsten Heartbeat über alle aktiven Entitäten des Geräts
    # sowie die repräsentative Sensor-Entität.
    device_buckets: dict[str, dict] = {}
    device_newest_activity: dict[str, datetime] = {}

    for state in hass.states.async_all():
        entity_id = state.entity_id
        if f".{DOMAIN}" in entity_id:
            continue

        attrs = state.attributes or {}
        if attrs.get("restored") is True:
            continue
        if state.state in ("unavailable", "unknown", ""):
            continue

        ts = _get_state_timestamp(state)
        if ts is None:
            continue

        reg_entry = ent_reg.async_get(entity_id) if ent_reg is not None else None
        platform = (reg_entry.platform or "").lower() if reg_entry else ""
        if platform in _IGNORED_PLATFORMS:
            continue

        device_id = reg_entry.device_id if reg_entry else None

        # Jede aktive Entität eines Geräts zählt als Lebenszeichen (verhindert Fehlalarme!)
        if device_id:
            prev_ts = device_newest_activity.get(device_id)
            if prev_ts is None or ts > prev_ts:
                device_newest_activity[device_id] = ts

        domain = entity_id.split(".", 1)[0]
        if domain not in _MONITORED_DOMAINS:
            continue

        device_class = str(attrs.get("device_class") or "").lower()
        if device_class in _IGNORED_DEVICE_CLASSES:
            continue

        # Entitäten ohne Device-ID nur prüfen, wenn sie eine physische Sensor-Klasse haben
        if not device_id and device_class not in _PHYSICAL_DEVICE_CLASSES:
            continue

        # Bei zugeordnetem Gerät prüfen, ob das Gerät ein Service/Software-Gerät ist
        display_name = str(attrs.get("friendly_name") or entity_id).strip()
        if device_id and dev_reg is not None:
            device = dev_reg.async_get(device_id)
            if device is not None:
                entry_type = getattr(device, "entry_type", None)
                if entry_type is not None and str(entry_type).lower().endswith("service"):
                    continue
                dev_name = (device.name_by_user or device.name or "").strip()
                if dev_name:
                    display_name = dev_name

        bucket_key = f"dev:{device_id}" if device_id else f"ent:{entity_id}"
        existing = device_buckets.get(bucket_key)
        is_diagnostic = bool(
            reg_entry and getattr(reg_entry, "entity_category", None) is not None
        )

        # Bevorzuge eine nicht-diagnostische Sensor-Entität als repräsentative Entität für More-Info
        if existing is None:
            device_buckets[bucket_key] = {
                "bucket_key": bucket_key,
                "device_id": device_id,
                "name": display_name,
                "entity_id": entity_id,
                "last_ts": ts,
                "is_diagnostic": is_diagnostic,
                "last_state": str(state.state)[:40],
                "has_primary_sensor": not is_diagnostic,
            }
        else:
            if not is_diagnostic:
                existing["has_primary_sensor"] = True
            if existing["is_diagnostic"] and not is_diagnostic:
                existing["entity_id"] = entity_id
                existing["is_diagnostic"] = False
                existing["last_state"] = str(state.state)[:40]
            if ts > existing["last_ts"]:
                existing["last_ts"] = ts

    silent_list: list[dict] = []
    for item in device_buckets.values():
        # Geräte ohne einzigen Primär-Sensor (nur Diagnose-Sensoren) ignorieren
        if not item["has_primary_sensor"]:
            continue

        newest_ts = item["last_ts"]
        if item["device_id"] and item["device_id"] in device_newest_activity:
            dev_ts = device_newest_activity[item["device_id"]]
            if dev_ts > newest_ts:
                newest_ts = dev_ts

        delta_hours = (now - newest_ts).total_seconds() / 3600.0
        if delta_hours < silent_hours:
            continue

        dur_long, dur_compact = _format_silent_duration(delta_hours)
        silent_list.append(
            {
                "name": item["name"],
                "entity_id": item["entity_id"],
                "hours_silent": round(delta_hours, 1),
                "duration_formatted": dur_long,
                "compact_duration": dur_compact,
                "last_seen": _to_local_str(newest_ts),
                "last_state": item["last_state"],
            }
        )

    silent_list.sort(key=lambda d: (-d["hours_silent"], d["name"].lower()))

    count = len(silent_list)
    if count == 0:
        status = "Alle aktiv"
    elif count == 1:
        status = f"1 Sensor > {silent_hours} h"
    else:
        status = f"{count} Sensoren > {silent_hours} h"

    geraete_list = [
        f"{d['name']}: seit {d['duration_formatted']} (zuletzt {d['last_seen']})"
        for d in silent_list
    ]

    return {
        "status": status,
        "summary_text": _build_summary_text(silent_list),
        "silent_count": count,
        "silent_hours": silent_hours,
        "checked_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "geraete": geraete_list,
        "devices": silent_list,
    }
