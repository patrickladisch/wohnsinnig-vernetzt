"""Native Update-Entität für installierte Wohnsinnig-vernetzt-Blueprints."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
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
    """Erstellt die Blueprint-Update-Entität."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [WohnsinnigVernetztBlueprintsUpdateEntity(coordinator, entry.entry_id)]
    )


class WohnsinnigVernetztBlueprintsUpdateEntity(
    WohnsinnigVernetztEntity, UpdateEntity
):
    """Prüft installierte Blueprints gegen wohnsinnigvernetzt.de und installiert Updates per Klick."""

    _attr_name = "Blueprints: Updates"
    _attr_title = "Wohnsinnig vernetzt Blueprints"
    _attr_icon = "mdi:file-refresh-outline"
    _attr_release_url = "https://www.wohnsinnigvernetzt.de/"
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "blueprints_update")
        self._attr_in_progress = False

    def _stats(self) -> tuple[list[dict], list[dict]]:
        bps = self.coordinator.get_blueprints()
        installed = [bp for bp in bps if bp.get("installed")]
        outdated = [bp for bp in installed if bp.get("update_available")]
        return installed, outdated

    @property
    def installed_version(self) -> str:
        installed, outdated = self._stats()
        if not installed:
            return "Keine installiert"
        if not outdated:
            return f"{len(installed)} aktuell"
        up_to_date = len(installed) - len(outdated)
        return f"{up_to_date}/{len(installed)} aktuell"

    @property
    def latest_version(self) -> str:
        installed, outdated = self._stats()
        if not installed:
            return "Keine installiert"
        if not outdated:
            return f"{len(installed)} aktuell"
        suffix = "Update" if len(outdated) == 1 else "Updates"
        return f"{len(outdated)} {suffix} verfügbar"

    @property
    def release_summary(self) -> str | None:
        _, outdated = self._stats()
        if not outdated:
            return "Alle installierten Wohnsinnig-vernetzt-Blueprints sind auf dem neuesten Stand."
        names = ", ".join(bp["title"] for bp in outdated[:5])
        if len(outdated) > 5:
            names += f" (+{len(outdated) - 5} weitere)"
        return f"Aktualisierte Blueprints verfügbar: {names}"

    async def async_release_notes(self) -> str | None:
        installed, outdated = self._stats()
        if not installed:
            return "Du hast noch keine Blueprints von Wohnsinnig vernetzt importiert."
        if not outdated:
            return "Alle installierten Blueprints entsprechen dem aktuellen Stand auf wohnsinnigvernetzt.de."

        lines = ["### Aktualisierte Blueprints auf wohnsinnigvernetzt.de\n"]
        for bp in outdated:
            desc = f" – {bp['description']}" if bp.get("description") else ""
            lines.append(f"- **{bp['title']}**{desc}")
        lines.append("\nKlicke auf **Installieren**, um alle veralteten Dateien direkt zu aktualisieren.")
        return "\n".join(lines)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        installed, outdated = self._stats()
        return {
            "installed_count": len(installed),
            "outdated_count": len(outdated),
            "outdated_blueprints": [bp["title"] for bp in outdated],
        }

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Lädt alle veralteten installierten Blueprints neu herunter und aktualisiert HA."""
        self._attr_in_progress = True
        self.async_write_ha_state()
        try:
            await self.coordinator.async_update_outdated_blueprints()
        finally:
            self._attr_in_progress = False
            self.async_write_ha_state()
