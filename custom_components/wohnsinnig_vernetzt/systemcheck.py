"""Lokaler Wohnsinnig-vernetzt-Systemcheck (100 % lokal, ohne Cloud)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_IGNORED_UNAVAILABLE_DOMAINS = {
    "button",
    "event",
    "scene",
    "script",
    "automation",
    "tts",
    "stt",
    "conversation",
    "update",
    "notify",
}


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


def run_systemcheck(
    hass: HomeAssistant, battery_threshold: int = 15
) -> dict:
    """Prüft die lokale Home-Assistant-Instanz auf häufige Smart-Home-Probleme."""
    unavailable: list[dict] = []
    orphaned: list[dict] = []
    low_batteries: list[dict] = []
    seen_battery_entities: set[str] = set()

    for state in hass.states.async_all():
        entity_id = state.entity_id
        domain = entity_id.split(".", 1)[0]
        attrs = state.attributes or {}
        friendly = str(attrs.get("friendly_name") or entity_id)

        if f".{DOMAIN}" in entity_id:
            continue

        # 1. Verwaiste Entitäten (restored: true)
        if attrs.get("restored") is True:
            orphaned.append({"entity_id": entity_id, "name": friendly})
            continue

        # 2. Nicht verfügbare Entitäten
        if state.state == "unavailable" and domain not in _IGNORED_UNAVAILABLE_DOMAINS:
            unavailable.append({"entity_id": entity_id, "name": friendly})
            continue

        # 3. Schwache Batterien (Sensor, Binary Sensor oder battery_level Attribut)
        device_class = str(attrs.get("device_class") or "").lower()

        if domain == "binary_sensor" and device_class == "battery" and state.state == "on":
            low_batteries.append(
                {"entity_id": entity_id, "name": friendly, "level": "schwach"}
            )
            seen_battery_entities.add(entity_id)
            continue

        if domain == "sensor" and device_class == "battery":
            val = _parse_float(state.state)
            if val is not None and 0 <= val <= battery_threshold:
                low_batteries.append(
                    {
                        "entity_id": entity_id,
                        "name": friendly,
                        "level": f"{int(round(val))} %",
                    }
                )
                seen_battery_entities.add(entity_id)
                continue

        if "battery_level" in attrs and entity_id not in seen_battery_entities:
            val = _parse_float(attrs.get("battery_level"))
            if val is not None and 0 <= val <= battery_threshold:
                low_batteries.append(
                    {
                        "entity_id": entity_id,
                        "name": friendly,
                        "level": f"{int(round(val))} %",
                    }
                )
                seen_battery_entities.add(entity_id)

    unavailable.sort(key=lambda item: item["name"].lower())
    orphaned.sort(key=lambda item: item["name"].lower())
    low_batteries.sort(key=lambda item: item["name"].lower())

    total_issues = len(unavailable) + len(low_batteries) + len(orphaned)
    if total_issues == 0:
        status = "OK"
    elif total_issues == 1:
        status = "1 Hinweis"
    else:
        status = f"{total_issues} Hinweise"

    return {
        "status": status,
        "total_issues": total_issues,
        "unavailable_count": len(unavailable),
        "low_battery_count": len(low_batteries),
        "orphaned_count": len(orphaned),
        "battery_threshold": battery_threshold,
        "checked_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "unavailable_entities": [
            f"{item['name']} ({item['entity_id']})" for item in unavailable[:50]
        ],
        "low_battery_entities": [
            f"{item['name']}: {item['level']} ({item['entity_id']})"
            for item in low_batteries[:50]
        ],
        "orphaned_entities": [
            f"{item['name']} ({item['entity_id']})" for item in orphaned[:50]
        ],
    }
