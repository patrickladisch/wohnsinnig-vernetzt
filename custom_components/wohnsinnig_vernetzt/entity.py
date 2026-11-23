"""Basis-Entität für Wohnsinnig vernetzt."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WohnsinnigVernetztCoordinator


class WohnsinnigVernetztEntity(CoordinatorEntity[WohnsinnigVernetztCoordinator]):
    """Gemeinsame Basisklasse für alle Entitäten der Integration."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WohnsinnigVernetztCoordinator,
        entry_id: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Wohnsinnig vernetzt",
            manufacturer="Wohnsinnig vernetzt Podcast",
            model="Podcast RSS Feed",
            configuration_url="https://www.wohnsinnigvernetzt.de",
        )
