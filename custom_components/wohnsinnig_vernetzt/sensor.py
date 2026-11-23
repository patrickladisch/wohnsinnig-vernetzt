"""Sensor-Entität für Wohnsinnig vernetzt."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WohnsinnigVernetztCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Erstellt den Podcast-Sensor."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WohnsinnigVernetztSensor(coordinator, entry.entry_id)])


class WohnsinnigVernetztSensor(
    CoordinatorEntity[WohnsinnigVernetztCoordinator], SensorEntity
):
    """Zeigt die neueste Podcast-Folge und Eckdaten an."""

    _attr_has_entity_name = True
    _attr_name = "Neueste Folge"
    _attr_icon = "mdi:podcast"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_latest_episode"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Wohnsinnig vernetzt",
            "manufacturer": "Podcast RSS",
            "model": "Podcast Feed",
        }

    @property
    def native_value(self) -> str | None:
        episodes = (self.coordinator.data or {}).get("episodes", [])
        if not episodes:
            return "Keine Folgen gefunden"
        return episodes[0]["title"][:255]

    @property
    def entity_picture(self) -> str | None:
        data = self.coordinator.data or {}
        episodes = data.get("episodes", [])
        if episodes and episodes[0].get("image"):
            return episodes[0]["image"]
        return data.get("image") or None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        episodes = data.get("episodes", [])
        latest = episodes[0] if episodes else {}
        return {
            "podcast_title": data.get("title", "Wohnsinnig vernetzt"),
            "episode_count": len(episodes),
            "latest_pub_date": latest.get("pub_date", ""),
            "latest_duration": latest.get("duration", ""),
            "latest_audio_url": latest.get("audio_url", ""),
        }
