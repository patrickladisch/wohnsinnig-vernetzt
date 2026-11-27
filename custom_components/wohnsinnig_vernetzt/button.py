"""Button-Entitäten für Audio, Anwesenheitssimulation, Blueprints sowie Batterie- & Sensor-Check."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEVICE_SECTION_BLUEPRINTS,
    DEVICE_SECTION_CHECKS,
    DEVICE_SECTION_PRESENCE,
    DOMAIN,
    EVENT_OPEN_CONFIG,
)
from .coordinator import WohnsinnigVernetztCoordinator
from .entity import WohnsinnigVernetztEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Erstellt alle Buttons in ihren jeweiligen Funktionsbereichen."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            # Anwesenheitssimulation
            WohnsinnigVernetztOpenPresenceConfigButton(coordinator, entry.entry_id),
            # Blueprints
            WohnsinnigVernetztImportBlueprintButton(coordinator, entry.entry_id),
            WohnsinnigVernetztImportAllBlueprintsButton(coordinator, entry.entry_id),
            # Audio & Podcast
            WohnsinnigVernetztMarkSeenButton(coordinator, entry.entry_id),
            WohnsinnigVernetztTestNotifyButton(coordinator, entry.entry_id),
            WohnsinnigVernetztRefreshButton(coordinator, entry.entry_id),
            # Batterie- & Sensor-Check
            WohnsinnigVernetztBatteryCheckButton(coordinator, entry.entry_id),
            WohnsinnigVernetztSilentSensorsButton(coordinator, entry.entry_id),
        ]
    )


class WohnsinnigVernetztOpenPresenceConfigButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Öffnet direkt den Konfigurations-Dialog für Lampen, Schalter & Bewegungsmelder."""

    _device_section = DEVICE_SECTION_PRESENCE
    _attr_name = "Konfiguration öffnen"
    _attr_icon = "mdi:tune-variant"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "presence_open_config")

    async def async_press(self) -> None:
        user_id = self._context.user_id if self._context else None
        self.hass.bus.async_fire(
            EVENT_OPEN_CONFIG,
            {
                "section": "presence",
                "entry_id": self._entry_id,
                "user_id": user_id,
            },
        )


class WohnsinnigVernetztImportBlueprintButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Importiert den ausgewählten Blueprint direkt in Home Assistant."""

    _device_section = DEVICE_SECTION_BLUEPRINTS
    _attr_name = "Ausgewählten importieren"
    _attr_icon = "mdi:import"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "import_selected_blueprint")

    async def async_press(self) -> None:
        await self.coordinator.async_import_blueprint()


class WohnsinnigVernetztImportAllBlueprintsButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Importiert alle Blueprints von wohnsinnigvernetzt.de in einem Rutsch."""

    _device_section = DEVICE_SECTION_BLUEPRINTS
    _attr_name = "Alle importieren"
    _attr_icon = "mdi:download-multiple"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "import_all_blueprints")

    async def async_press(self) -> None:
        await self.coordinator.async_import_all_blueprints()


class WohnsinnigVernetztMarkSeenButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Bestätigt die neueste Folge (setzt den Sensor 'Neue Folge verfügbar' auf NEIN)."""

    _attr_name = "Neue Folge bestätigen"
    _attr_icon = "mdi:check-bold"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "mark_episode_seen")

    async def async_press(self) -> None:
        await self.coordinator.async_mark_latest_episode_seen()


class WohnsinnigVernetztBatteryCheckButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Prüft sofort alle Batterien unter der Grenze und listet alle betroffenen Geräte auf."""

    _device_section = DEVICE_SECTION_CHECKS
    _attr_name = "Batterie-Check ausführen"
    _attr_icon = "mdi:battery-alert-variant-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "run_battery_check")

    async def async_press(self) -> None:
        await self.coordinator.async_run_battery_check(notify=True)


class WohnsinnigVernetztSilentSensorsButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Prüft sofort alle Sensoren auf Zigbee-Freeze (> eingestellte Stunden ohne Update)."""

    _device_section = DEVICE_SECTION_CHECKS
    _attr_name = "Stille Sensoren prüfen"
    _attr_icon = "mdi:radar"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "run_silent_sensors_check")

    async def async_press(self) -> None:
        await self.coordinator.async_run_silent_sensors_check(notify=True)


class WohnsinnigVernetztTestNotifyButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Schickt sofort eine Test-Benachrichtigung inkl. Infografik & Action-Buttons."""

    _attr_name = "Test-Benachrichtigung senden"
    _attr_icon = "mdi:bell-check"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "test_notification")

    async def async_press(self) -> None:
        await self.coordinator.async_send_test_notification()


class WohnsinnigVernetztRefreshButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Aktualisiert Podcast-Feed, Blueprints, Infografiken und Eilmeldungen sofort."""

    _attr_name = "Feed & Blueprints aktualisieren"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "refresh_feed")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
