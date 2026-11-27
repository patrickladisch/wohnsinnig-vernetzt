"""Number-Entitäten für Batterie-Grenze (%) und Stille-Sensoren-Grenze (h)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfTime
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
    """Erstellt die einstellbaren Schwellwerte unter Konfiguration."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            WohnsinnigVernetztBatteryThresholdNumber(coordinator, entry.entry_id),
            WohnsinnigVernetztSilentHoursNumber(coordinator, entry.entry_id),
        ]
    )


class WohnsinnigVernetztBatteryThresholdNumber(WohnsinnigVernetztEntity, NumberEntity):
    """Stellt die Batterie-Warngrenze (Standard: 15 %) direkt ein."""

    _device_section = DEVICE_SECTION_CHECKS
    _attr_name = "Batterie-Grenze"
    _attr_icon = "mdi:battery-alert-variant-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 5
    _attr_native_max_value = 50
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "battery_threshold")

    @property
    def native_value(self) -> float:
        return float(self.coordinator.battery_threshold)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_battery_threshold(int(round(value)))


class WohnsinnigVernetztSilentHoursNumber(WohnsinnigVernetztEntity, NumberEntity):
    """Stellt ein, ab wie vielen Stunden ohne Update ein Sensor als still gilt."""

    _device_section = DEVICE_SECTION_CHECKS
    _attr_name = "Stille-Sensoren-Grenze"
    _attr_icon = "mdi:timer-sand"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 1
    _attr_native_max_value = 168
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "silent_hours_threshold")

    @property
    def native_value(self) -> float:
        return float(self.coordinator.silent_hours)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_silent_hours(int(round(value)))
