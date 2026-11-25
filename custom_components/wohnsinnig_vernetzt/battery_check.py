"""Lokaler Batterie-Check für Wohnsinnig vernetzt (nur Batterien unter Schwellwert)."""

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
    hass: HomeAssistant, battery_threshold: int = 15
) -> dict:
    """Prüft alle lokalen Batterie-Sensoren und meldet ausschließlich Geräte unter dem Schwellwert."""
    candidates: dict[str, dict] = {}

    for state in hass.states.async_all():
        entity_id = state.entity_id
        if f".{DOMAIN}" in entity_id:
            continue

        attrs = state.attributes or {}
        if attrs.get("restored") is True:
            continue
        if state.state in ("unavailable", "unknown", ""):
            continue

        domain = entity_id.split(".", 1)[0]
        device_class = str(attrs.get("device_class") or "").lower()
        val: float | None = None

        if domain == "sensor" and device_class == "battery":
            val = _parse_float(state.state)
        elif "battery_level" in attrs:
            val = _parse_float(attrs.get("battery_level"))

        # Strikt unter dem Schwellwert (z. B. < 15 %, also 0 % bis 14,9 %)
        if val is None or not (0 <= val < battery_threshold):
            continue

        friendly = str(attrs.get("friendly_name") or entity_id).strip()
        device_id, display_name = _resolve_device_info(hass, entity_id, friendly)
        dedup_key = f"dev:{device_id}" if device_id else f"ent:{entity_id}"
        rounded = int(round(val))

        existing = candidates.get(dedup_key)
        if existing is None or val < existing["raw_level"]:
            candidates[dedup_key] = {
                "name": display_name,
                "entity_id": entity_id,
                "level": rounded,
                "raw_level": val,
                "level_formatted": f"{rounded} %",
            }

    low_batteries = sorted(
        candidates.values(),
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

    return {
        "status": status,
        "summary_text": _build_summary_text(devices_clean),
        "low_battery_count": count,
        "battery_threshold": battery_threshold,
        "checked_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "geraete": geraete_list,
        "devices": devices_clean,
    }
