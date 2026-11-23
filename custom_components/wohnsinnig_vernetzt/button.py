"""Button-Entitäten für Test-Benachrichtigung und Feed-Refresh."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
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
    """Erstellt die Steuerelemente als Buttons."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            WohnsinnigVernetztTestNotifyButton(coordinator, entry.entry_id),
            WohnsinnigVernetztRefreshButton(coordinator, entry.entry_id),
        ]
    )


class WohnsinnigVernetztTestNotifyButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Schickt sofort eine Test-Benachrichtigung."""

    _attr_name = "Test-Benachrichtigung senden"
    _attr_icon = "mdi:bell-check"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "test_notification")

    async def async_press(self) -> None:
        await self.coordinator.async_send_test_notification()


class WohnsinnigVernetztRefreshButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Aktualisiert den RSS-Feed sofort."""

    _attr_name = "Nach neuen Folgen suchen"
    _attr_icon = "mdi:refresh"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "refresh_feed")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
