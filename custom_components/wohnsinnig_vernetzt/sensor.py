"""Sensor-Entitäten für Wohnsinnig vernetzt."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
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
    """Erstellt die Podcast- und Blueprint-Sensoren."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            WohnsinnigVernetztLatestSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztEpisodesSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztBlueprintsSensor(coordinator, entry.entry_id),
        ]
    )


class WohnsinnigVernetztLatestSensor(WohnsinnigVernetztEntity, SensorEntity):
    """Zeigt die neueste Podcast-Folge an."""

    _attr_name = "Neueste Folge"
    _attr_icon = "mdi:podcast"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "latest_episode")

    @property
    def native_value(self) -> str | None:
        episodes = (self.coordinator.data or {}).get("episodes", [])
        if not episodes:
            return "Keine Folgen gefunden"
        return episodes[0]["title"][:255]

    @property
    def entity_picture(self) -> str | None:
        data = self.coordinator.data or {}
        if self.coordinator.logo_url:
            return self.coordinator.logo_url
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


class WohnsinnigVernetztEpisodesSensor(WohnsinnigVernetztEntity, SensorEntity):
    """Zeigt die Anzahl und eine vollständige Liste aller Podcast-Folgen."""

    _attr_name = "Alle Folgen"
    _attr_icon = "mdi:playlist-music"
    _attr_native_unit_of_measurement = "Folgen"
    _unrecorded_attributes = frozenset({"episodes"})

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "all_episodes")

    @property
    def native_value(self) -> int:
        return len((self.coordinator.data or {}).get("episodes", []))

    @property
    def extra_state_attributes(self) -> dict:
        episodes = (self.coordinator.data or {}).get("episodes", [])
        compact = [
            {
                "title": ep["title"],
                "pub_date": ep["pub_date"],
                "duration": ep["duration"],
                "audio_url": ep["audio_url"],
            }
            for ep in episodes
        ]
        return {
            "total_episodes": len(episodes),
            "episodes": compact,
        }


class WohnsinnigVernetztBlueprintsSensor(WohnsinnigVernetztEntity, SensorEntity):
    """Zeigt alle verfügbaren Blueprints von wohnsinnigvernetzt.de inkl. Import-Status."""

    _attr_name = "Blueprints"
    _attr_icon = "mdi:file-code-outline"
    _attr_native_unit_of_measurement = "Blueprints"
    _unrecorded_attributes = frozenset({"blueprints"})

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "blueprints_catalog")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.get_blueprints())

    @property
    def extra_state_attributes(self) -> dict:
        bps = self.coordinator.get_blueprints()
        return {
            "source_url": self.coordinator.blueprints_url,
            "installed_count": sum(1 for bp in bps if bp.get("installed")),
            "blueprints": [
                {
                    "title": bp["title"],
                    "description": bp.get("description", ""),
                    "url": bp["url"],
                    "installed": bp.get("installed", False),
                    "installed_path": bp.get("installed_path", ""),
                }
                for bp in bps
            ],
        }
