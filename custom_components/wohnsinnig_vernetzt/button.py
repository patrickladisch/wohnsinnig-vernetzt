"""Button-Entitäten für Benachrichtigungstest, Refresh und Blueprint-Import."""

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
            WohnsinnigVernetztImportBlueprintButton(coordinator, entry.entry_id),
            WohnsinnigVernetztImportAllBlueprintsButton(coordinator, entry.entry_id),
            WohnsinnigVernetztTestNotifyButton(coordinator, entry.entry_id),
            WohnsinnigVernetztRefreshButton(coordinator, entry.entry_id),
        ]
    )


class WohnsinnigVernetztImportBlueprintButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Importiert den ausgewählten Blueprint direkt in Home Assistant."""

    _attr_name = "Ausgewählten Blueprint importieren"
    _attr_icon = "mdi:import"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "import_selected_blueprint")

    async def async_press(self) -> None:
        await self.coordinator.async_import_blueprint()


class WohnsinnigVernetztImportAllBlueprintsButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Importiert alle Blueprints von wohnsinnigvernetzt.de in einem Rutsch."""

    _attr_name = "Alle Blueprints importieren"
    _attr_icon = "mdi:download-multiple"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "import_all_blueprints")

    async def async_press(self) -> None:
        await self.coordinator.async_import_all_blueprints()


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
    """Aktualisiert Podcast-Feed und Blueprint-Liste sofort."""

    _attr_name = "Folgen & Blueprints aktualisieren"
    _attr_icon = "mdi:refresh"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "refresh_feed")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
