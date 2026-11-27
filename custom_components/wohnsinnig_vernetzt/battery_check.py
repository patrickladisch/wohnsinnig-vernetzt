"""Lokaler Batterie-Check für Wohnsinnig vernetzt (mit einstellbarer Grenze & Ausschlussliste)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN


def _parse_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("%", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _resolve_device_info(
    hass: HomeAssistant, entity_id: str, friendly_name: str
) -> tuple[str | None, str]:
    """Ermittelt (device_id, Gerätename) aus Entity- und Device-Registry."""
    try:
        ent_reg = er.async_get(hass)
        reg_entry = ent_reg.async_get(entity_id)
        if reg_entry and reg_entry.device_id:
            dev_reg = dr.async_get(hass)
            device = dev_reg.async_get(reg_entry.device_id)
            if device:
                dev_name = (device.name_by_user or device.name or "").strip()
                if dev_name:
                    return device.id, dev_name
            return reg_entry.device_id, friendly_name
    except Exception:
        pass
    return None, friendly_name


def normalize_battery_exclusions(raw: object) -> list[str]:
    """Bereinigt eine Liste ausgeschlossener Batterie-Geräte (dedup_key / device_id / entity_id)."""
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
    for item in items:
        if item not in seen:
            seen.add(item)
            cleaned.append(item)
    return cleaned


def resolve_exclusion_key(hass: HomeAssistant, identifier: str) -> str:
    """Normalisiert entity_id, device_id oder dedup_key auf einen eindeutigen Ausschluss-Key."""
    raw = (identifier or "").strip()
    if not raw:
        return ""
    if raw.startswith(("dev:", "ent:")):
        return raw

    # Falls eine entity_id übergeben wurde -> bevorzugt auf zugehörige dev:<device_id> abbilden
    if "." in raw:
        try:
            ent_reg = er.async_get(hass)
            reg_entry = ent_reg.async_get(raw)
            if reg_entry and reg_entry.device_id:
                return f"dev:{reg_entry.device_id}"
        except Exception:
            pass
        return f"ent:{raw}"

    # Andernfalls prüfen, ob es eine bekannte device_id ist
    try:
        dev_reg = dr.async_get(hass)
        if dev_reg.async_get(raw) is not None:
            return f"dev:{raw}"
    except Exception:
        pass
    return raw


def _resolve_excluded_display_name(hass: HomeAssistant, key: str) -> str:
    """Ermittelt einen lesbaren Namen für einen gespeicherten Ausschluss-Key (auch wenn offline)."""
    if key.startswith("dev:"):
        dev_id = key[4:]
        try:
            dev_reg = dr.async_get(hass)
            device = dev_reg.async_get(dev_id)
            if device:
                name = (device.name_by_user or device.name or "").strip()
                if name:
                    return name
        except Exception:
            pass
        return dev_id

    if key.startswith("ent:"):
        ent_id = key[4:]
        state = hass.states.get(ent_id)
        if state and state.attributes.get("friendly_name"):
            return str(state.attributes["friendly_name"]).strip()
        return ent_id

    return key


def _is_excluded(item: dict, excluded_set: set[str]) -> bool:
    """Prüft, ob ein Batterie-Gerät in der Ausschlussliste steht (per Key, Device-ID oder Entity-ID)."""
    if not excluded_set:
        return False
    if item["dedup_key"] in excluded_set:
        return True
    if item["entity_id"] in excluded_set or f"ent:{item['entity_id']}" in excluded_set:
        return True
    if item.get("device_id") and (
        item["device_id"] in excluded_set
        or f"dev:{item['device_id']}" in excluded_set
    ):
        return True
    for ent_id in item.get("entity_ids", ()):
        if ent_id in excluded_set or f"ent:{ent_id}" in excluded_set:
            return True
    return False


def _collect_all_battery_candidates(hass: HomeAssistant) -> dict[str, dict]:
    """Sammelt alle lokalen Batterie-Geräte (inkl. optionalem Prozentwert)."""
    all_candidates: dict[str, dict] = {}

    for state in hass.states.async_all():
        entity_id = state.entity_id
        if f".{DOMAIN}" in entity_id:
            continue

        attrs = state.attributes or {}
        if attrs.get("restored") is True:
            continue

        domain = entity_id.split(".", 1)[0]
        device_class = str(attrs.get("device_class") or "").lower()
        is_battery_sensor = domain == "sensor" and device_class == "battery"
        has_battery_attr = "battery_level" in attrs

        if not is_battery_sensor and not has_battery_attr:
            continue

        val: float | None = None
        if state.state not in ("unavailable", "unknown", ""):
            if is_battery_sensor:
                val = _parse_float(state.state)
            elif has_battery_attr:
                val = _parse_float(attrs.get("battery_level"))

        if val is not None and not (0 <= val <= 100):
            val = None

        friendly = str(attrs.get("friendly_name") or entity_id).strip()
        device_id, display_name = _resolve_device_info(hass, entity_id, friendly)
        dedup_key = f"dev:{device_id}" if device_id else f"ent:{entity_id}"

        existing = all_candidates.get(dedup_key)
        if existing is None:
            rounded = int(round(val)) if val is not None else None
            all_candidates[dedup_key] = {
                "dedup_key": dedup_key,
                "device_id": device_id,
                "name": display_name,
                "entity_id": entity_id,
                "entity_ids": {entity_id},
                "level": rounded,
                "raw_level": val,
                "level_formatted": f"{rounded} %" if rounded is not None else "unbekannt",
            }
        else:
            existing["entity_ids"].add(entity_id)
            if val is not None and (
                existing["raw_level"] is None or val < existing["raw_level"]
            ):
                rounded = int(round(val))
                existing["entity_id"] = entity_id
                existing["level"] = rounded
                existing["raw_level"] = val
                existing["level_formatted"] = f"{rounded} %"

    return all_candidates


def get_all_battery_devices(hass: HomeAssistant) -> list[dict]:
    """Liefert eine alphabetisch sortierte Liste aller erkannten Batterie-Geräte (für Options-Auswahl)."""
    candidates = _collect_all_battery_candidates(hass)
    devices = [
        {
            "dedup_key": item["dedup_key"],
            "device_id": item["device_id"],
            "name": item["name"],
            "entity_id": item["entity_id"],
            "level": item["level"],
            "level_formatted": item["level_formatted"],
        }
        for item in candidates.values()
    ]
    devices.sort(key=lambda d: (d["name"].lower(), d["entity_id"]))
    return devices


def _build_summary_text(devices: list[dict], max_len: int = 255) -> str:
    """Erstellt einen direkt lesbaren Sensor-Text mit allen schwachen Geräten (<= 255 Zeichen)."""
    if not devices:
        return "Alle OK"

    entries = [f"{d['name']} ({d['level_formatted']})" for d in devices]
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


def run_battery_check(
    hass: HomeAssistant,
    battery_threshold: int = 15,
    excluded_keys: list[str] | set[str] | None = None,
) -> dict:
    """Prüft alle lokalen Batterie-Sensoren unter dem Schwellwert (ohne ausgeschlossene Geräte)."""
    all_candidates = _collect_all_battery_candidates(hass)
    excluded_list = normalize_battery_exclusions(list(excluded_keys or []))
    excluded_set = set(excluded_list)

    all_battery_levels: dict[str, float] = {}
    excluded_devices: list[dict] = []
    matched_excluded_keys: set[str] = set()
    active_low: list[dict] = []

    for item in all_candidates.values():
        if _is_excluded(item, excluded_set):
            matched_excluded_keys.add(item["dedup_key"])
            matched_excluded_keys.add(item["entity_id"])
            matched_excluded_keys.add(f"ent:{item['entity_id']}")
            if item.get("device_id"):
                matched_excluded_keys.add(item["device_id"])
                matched_excluded_keys.add(f"dev:{item['device_id']}")
            excluded_devices.append(
                {
                    "dedup_key": item["dedup_key"],
                    "name": item["name"],
                    "level": item["level"],
                    "level_formatted": item["level_formatted"],
                    "entity_id": item["entity_id"],
                }
            )
            continue

        if item["raw_level"] is None:
            continue

        all_battery_levels[item["dedup_key"]] = item["raw_level"]

        # Strikt unter dem Schwellwert (z. B. < 15 %, also 0 % bis 14,9 %)
        if item["raw_level"] < battery_threshold:
            active_low.append(item)

    # Auch aktuell nicht geladene/offline ausgeschlossene Geräte sichtbar halten
    for key in excluded_list:
        if key not in matched_excluded_keys:
            excluded_devices.append(
                {
                    "dedup_key": key,
                    "name": _resolve_excluded_display_name(hass, key),
                    "level": None,
                    "level_formatted": "—",
                    "entity_id": key[4:] if key.startswith("ent:") else "",
                }
            )

    excluded_devices.sort(key=lambda d: d["name"].lower())

    low_batteries = sorted(
        active_low,
        key=lambda item: (item["raw_level"], item["name"].lower()),
    )

    count = len(low_batteries)
    if count == 0:
        status = "OK"
    elif count == 1:
        status = f"1 Gerät < {battery_threshold} %"
    else:
        status = f"{count} Geräte < {battery_threshold} %"

    devices_clean = [
        {
            "dedup_key": item["dedup_key"],
            "name": item["name"],
            "level": item["level"],
            "level_formatted": item["level_formatted"],
            "entity_id": item["entity_id"],
        }
        for item in low_batteries
    ]

    geraete_list = [
        f"{item['name']}: {item['level_formatted']}" for item in devices_clean
    ]

    excluded_names = [
        f"{d['name']} ({d['level_formatted']})" if d.get("level") is not None else d["name"]
        for d in excluded_devices
    ]

    return {
        "status": status,
        "summary_text": _build_summary_text(devices_clean),
        "low_battery_count": count,
        "battery_threshold": battery_threshold,
        "checked_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "geraete": geraete_list,
        "devices": devices_clean,
        "excluded_count": len(excluded_devices),
        "excluded_names": excluded_names,
        "excluded_devices": excluded_devices,
        "all_battery_levels": all_battery_levels,
    }


def get_battery_exclusion_lists(
    hass: HomeAssistant,
    excluded_keys: list[str] | set[str] | None = None,
    battery_threshold: int = 15,
) -> tuple[list[dict], list[dict]]:
    """Liefert (aktive_geraete, ausgeschlossene_geraete) für die Geräte-Konfigurations-Dropdowns.

    Aktive Geräte unter dem Schwellwert stehen zuerst, danach alphabetisch sortiert.
    """
    all_candidates = _collect_all_battery_candidates(hass)
    excluded_list = normalize_battery_exclusions(list(excluded_keys or []))
    excluded_set = set(excluded_list)

    active_devices: list[dict] = []
    excluded_devices: list[dict] = []
    matched_excluded_keys: set[str] = set()

    for item in all_candidates.values():
        entry = {
            "dedup_key": item["dedup_key"],
            "name": item["name"],
            "entity_id": item["entity_id"],
            "level": item["level"],
            "raw_level": item["raw_level"],
            "level_formatted": item["level_formatted"],
            "is_low": item["raw_level"] is not None and item["raw_level"] < battery_threshold,
        }
        if _is_excluded(item, excluded_set):
            matched_excluded_keys.add(item["dedup_key"])
            matched_excluded_keys.add(item["entity_id"])
            matched_excluded_keys.add(f"ent:{item['entity_id']}")
            if item.get("device_id"):
                matched_excluded_keys.add(item["device_id"])
                matched_excluded_keys.add(f"dev:{item['device_id']}")
            excluded_devices.append(entry)
        else:
            active_devices.append(entry)

    for key in excluded_list:
        if key not in matched_excluded_keys:
            excluded_devices.append(
                {
                    "dedup_key": key,
                    "name": _resolve_excluded_display_name(hass, key),
                    "entity_id": key[4:] if key.startswith("ent:") else "",
                    "level": None,
                    "raw_level": None,
                    "level_formatted": "—",
                    "is_low": False,
                }
            )

    # Schwache Batterien zuerst (niedrigste zuerst), danach übrige alphabetisch
    active_devices.sort(
        key=lambda d: (
            0 if d["is_low"] else 1,
            d["raw_level"] if (d["is_low"] and d["raw_level"] is not None) else 999.0,
            d["name"].lower(),
        )
    )
    excluded_devices.sort(key=lambda d: d["name"].lower())
    return active_devices, excluded_devices
