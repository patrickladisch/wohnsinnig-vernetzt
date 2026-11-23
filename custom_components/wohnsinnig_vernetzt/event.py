"""Event-Entität für neu erschienene Podcast-Folgen."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_NEW_EPISODE
from .coordinator import WohnsinnigVernetztCoordinator
from .entity import WohnsinnigVernetztEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Erstellt die Event-Entität für neue Episoden."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WohnsinnigVernetztNewEpisodeEvent(coordinator, entry.entry_id)])


class WohnsinnigVernetztNewEpisodeEvent(WohnsinnigVernetztEntity, EventEntity):
    """Protokolliert jede neu erschienene Podcast-Folge."""

    _attr_name = "Neue Folge"
    _attr_icon = "mdi:new-box"
    _attr_event_types = ["new_episode"]

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "new_episode_event")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_NEW_EPISODE, self._handle_new_episode
            )
        )

    @callback
    def _handle_new_episode(self, episode: dict) -> None:
        self._trigger_event(
            "new_episode",
            {
                "title": episode.get("title", ""),
                "pub_date": episode.get("pub_date", ""),
                "duration": episode.get("duration", ""),
                "audio_url": episode.get("audio_url", ""),
            },
        )
        self.async_write_ha_state()
