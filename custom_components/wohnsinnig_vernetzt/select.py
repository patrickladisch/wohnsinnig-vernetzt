"""Select-Entität zur Auswahl aus allen Podcast-Folgen."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
    """Erstellt das Episoden-Dropdown."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WohnsinnigVernetztEpisodeSelect(coordinator, entry.entry_id)])


class WohnsinnigVernetztEpisodeSelect(WohnsinnigVernetztEntity, SelectEntity):
    """Dropdown mit allen verfügbaren Podcast-Folgen."""

    _attr_name = "Folge auswählen"
    _attr_icon = "mdi:format-list-bulleted"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "episode_select")

    def _option_map(self) -> dict[str, dict]:
        episodes = (self.coordinator.data or {}).get("episodes", [])
        mapping: dict[str, dict] = {}
        for ep in episodes:
            label = ep["title"][:240]
            if ep.get("pub_date"):
                candidate = f"{label} ({ep['pub_date']})"
            else:
                candidate = label
            candidate = candidate[:255]
            if candidate in mapping:
                candidate = f"{candidate[:248]} #{len(mapping) + 1}"
            mapping[candidate] = ep
        return mapping

    @property
    def options(self) -> list[str]:
        opts = list(self._option_map().keys())
        return opts or ["Keine Folgen verfügbar"]

    @property
    def current_option(self) -> str | None:
        mapping = self._option_map()
        if not mapping:
            return "Keine Folgen verfügbar"
        selected = self.coordinator.get_selected_episode()
        if selected:
            for label, ep in mapping.items():
                if ep["guid"] == selected["guid"]:
                    return label
        return next(iter(mapping.keys()))

    @property
    def extra_state_attributes(self) -> dict:
        ep = self.coordinator.get_selected_episode() or {}
        return {
            "title": ep.get("title", ""),
            "pub_date": ep.get("pub_date", ""),
            "duration": ep.get("duration", ""),
            "audio_url": ep.get("audio_url", ""),
            "description": ep.get("description", ""),
        }

    async def async_select_option(self, option: str) -> None:
        mapping = self._option_map()
        ep = mapping.get(option)
        if ep:
            await self.coordinator.async_set_selected_episode(ep["guid"])
