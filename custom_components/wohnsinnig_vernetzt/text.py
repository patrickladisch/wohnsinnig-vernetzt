"""Text-Entität zur Eingabe von Feedback direkt auf der Geräteseite."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
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
    """Erstellt das Feedback-Textfeld."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WohnsinnigVernetztFeedbackText(coordinator, entry.entry_id)])


class WohnsinnigVernetztFeedbackText(WohnsinnigVernetztEntity, TextEntity):
    """Textfeld für Feedback-Nachrichten an den Podcast."""

    _attr_name = "Feedback-Nachricht"
    _attr_icon = "mdi:message-text-outline"
    _attr_native_max = 255

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "feedback_message")

    @property
    def native_value(self) -> str:
        return self.coordinator.feedback_draft

    async def async_set_value(self, value: str) -> None:
        self.coordinator.feedback_draft = value.strip()
        self.async_write_ha_state()
