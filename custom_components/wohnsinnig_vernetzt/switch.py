"""Switch-Entität für Benachrichtigungen bei neuen Folgen."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WohnsinnigVernetztCoordinator
from .entity import WohnsinnigVernetztEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Erstellt den Benachrichtigungs-Schalter."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [WohnsinnigVernetztNotifySwitch(coordinator, entry.entry_id)]
    )


class WohnsinnigVernetztNotifySwitch(WohnsinnigVernetztEntity, SwitchEntity):
    """Schaltet automatische Benachrichtigungen bei neuen Folgen ein oder aus."""

    _attr_name = "Benachrichtigungen aktiv"
    _attr_icon = "mdi:bell-ring"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "notifications_enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.notifications_enabled

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "notify_services": self.coordinator.notify_services,
        }

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_notifications_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_notifications_enabled(False)
