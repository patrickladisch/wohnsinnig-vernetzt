"""Time-Entität für die tägliche Uhrzeit des gebündelten Batterie-Push."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_SECTION_CHECKS, DOMAIN
from .coordinator import WohnsinnigVernetztCoordinator
from .entity import WohnsinnigVernetztEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Erstellt die Uhrzeit-Einstellung für den gebündelten Batterie-Push."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [WohnsinnigVernetztBatteryPushTimeEntity(coordinator, entry.entry_id)]
    )


class WohnsinnigVernetztBatteryPushTimeEntity(WohnsinnigVernetztEntity, TimeEntity):
    """Legt die feste Tageszeit für gebündelte Batterie-Push-Meldungen fest."""

    _device_section = DEVICE_SECTION_CHECKS
    _attr_name = "Batterie-Push Uhrzeit"
    _attr_icon = "mdi:clock-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "battery_push_time")

    @property
    def native_value(self) -> time:
        return self.coordinator.get_battery_push_time_obj()

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_set_battery_push_time(value)
