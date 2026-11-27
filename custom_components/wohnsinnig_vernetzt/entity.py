"""Basis-Entität und 7-Bereiche-Gerätestruktur für Wohnsinnig vernetzt."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEVICE_CONFIG_URL,
    DEVICE_INTEGRATION_CONFIG_URL,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DEVICE_SECTION_AUDIO,
    DEVICE_SECTION_BLUEPRINTS,
    DEVICE_SECTION_CHECKS,
    DEVICE_SECTION_PRESENCE,
    DEVICE_SECTION_PRESENCE_SENSORS,
    DEVICE_SECTION_PV,
    DEVICE_SECTION_WAKEUP,
    DOMAIN,
)
from .coordinator import WohnsinnigVernetztCoordinator

SECTION_DEVICE_SPECS: dict[str, dict[str, str]] = {
    DEVICE_SECTION_AUDIO: {
        "name": DEVICE_NAME,
        "model": DEVICE_MODEL,
        "config_url": DEVICE_CONFIG_URL,
    },
    DEVICE_SECTION_PRESENCE: {
        "name": "Wohnsinnig vernetzt – Anwesenheitssimulation",
        "model": "Anwesenheitssimulation (14 Tage ± 7 Min)",
        "config_url": DEVICE_INTEGRATION_CONFIG_URL,
    },
    DEVICE_SECTION_BLUEPRINTS: {
        "name": "Wohnsinnig vernetzt – Blueprints",
        "model": "Blueprint-Manager & Updates",
        "config_url": DEVICE_CONFIG_URL,
    },
    DEVICE_SECTION_CHECKS: {
        "name": "Wohnsinnig vernetzt – Batterie- & Sensor-Check",
        "model": "Batterie-Check & Stille Sensoren",
        "config_url": DEVICE_INTEGRATION_CONFIG_URL,
    },
    DEVICE_SECTION_WAKEUP: {
        "name": "Wohnsinnig vernetzt – Wake-Up Light",
        "model": "Sonnenaufgang & Wake-Up Light",
        "config_url": DEVICE_INTEGRATION_CONFIG_URL,
    },
    DEVICE_SECTION_PV: {
        "name": "Wohnsinnig vernetzt – PV-Überschuss",
        "model": "PV-Überschuss & Solar-Manager",
        "config_url": DEVICE_INTEGRATION_CONFIG_URL,
    },
    DEVICE_SECTION_PRESENCE_SENSORS: {
        "name": "Wohnsinnig vernetzt – Anwesenheitssensoren",
        "model": "Kombinierte Anwesenheitssensoren",
        "config_url": DEVICE_INTEGRATION_CONFIG_URL,
    },
}


def get_section_device_identifier(entry_id: str, section: str) -> tuple[str, str]:
    """Gibt den eindeutigen Device-Identifier für einen der 4 Bereiche zurück."""
    if section == DEVICE_SECTION_AUDIO:
        return (DOMAIN, entry_id)
    return (DOMAIN, f"{entry_id}_{section}")


def build_section_device_info(entry_id: str, section: str) -> DeviceInfo:
    """Erstellt die DeviceInfo für den jeweiligen Funktionsbereich."""
    spec = SECTION_DEVICE_SPECS.get(section, SECTION_DEVICE_SPECS[DEVICE_SECTION_AUDIO])
    identifier = get_section_device_identifier(entry_id, section)
    if section == DEVICE_SECTION_AUDIO:
        return DeviceInfo(
            identifiers={identifier},
            name=spec["name"],
            model=spec["model"],
            manufacturer=DEVICE_MANUFACTURER,
            configuration_url=spec["config_url"],
        )
    return DeviceInfo(
        identifiers={identifier},
        name=spec["name"],
        model=spec["model"],
        manufacturer=DEVICE_MANUFACTURER,
        configuration_url=spec["config_url"],
        via_device=(DOMAIN, entry_id),
    )


class WohnsinnigVernetztEntity(CoordinatorEntity[WohnsinnigVernetztCoordinator]):
    """Gemeinsame Basisklasse für alle Entitäten der Integration."""

    _attr_has_entity_name = True
    _device_section: str = DEVICE_SECTION_AUDIO

    def __init__(
        self,
        coordinator: WohnsinnigVernetztCoordinator,
        entry_id: str,
        key: str,
        section: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        target_section = section or self._device_section
        self._attr_device_info = build_section_device_info(entry_id, target_section)
