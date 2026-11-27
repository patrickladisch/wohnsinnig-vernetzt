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
    DEVICE_SECTION_PRESENCE_SENSORS,
    DEVICE_SECTION_PV,
    DEVICE_SECTION_WAKEUP,
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
            # Wake-Up Light
            WohnsinnigVernetztOpenWakeUpConfigButton(coordinator, entry.entry_id),
            WohnsinnigVernetztStartWakeUpButton(coordinator, entry.entry_id),
            WohnsinnigVernetztStopWakeUpButton(coordinator, entry.entry_id),
            # PV-Überschuss
            WohnsinnigVernetztOpenPvConfigButton(coordinator, entry.entry_id),
            WohnsinnigVernetztEvaluatePvButton(coordinator, entry.entry_id),
            WohnsinnigVernetztResetPvDailyButton(coordinator, entry.entry_id),
            # Kombinierte Anwesenheitssensoren
            WohnsinnigVernetztOpenPresenceSensorsConfigButton(coordinator, entry.entry_id),
            WohnsinnigVernetztEvaluatePresenceSensorsButton(coordinator, entry.entry_id),
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

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "wv_open_config": "presence",
            "open_request_id": self.coordinator.presence_config_request_id,
            "open_request_user": self.coordinator.presence_config_request_user,
        }

    async def async_press(self) -> None:
        user_id = self._context.user_id if self._context else None
        self.coordinator.presence_config_request_id += 1
        self.coordinator.presence_config_request_user = user_id
        self.async_write_ha_state()
        self.hass.bus.async_fire(
            EVENT_OPEN_CONFIG,
            {
                "section": "presence",
                "entry_id": self._entry_id,
                "request_id": self.coordinator.presence_config_request_id,
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


class WohnsinnigVernetztOpenWakeUpConfigButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Öffnet direkt den Konfigurations-Dialog für das Wake-Up Light."""

    _device_section = DEVICE_SECTION_WAKEUP
    _attr_name = "Konfiguration öffnen"
    _attr_icon = "mdi:tune-variant"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "wakeup_open_config")

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "wv_open_config": "wakeup",
            "open_request_id": self.coordinator.wakeup_config_request_id,
            "open_request_user": self.coordinator.wakeup_config_request_user,
        }

    async def async_press(self) -> None:
        user_id = self._context.user_id if self._context else None
        self.coordinator.wakeup_config_request_id += 1
        self.coordinator.wakeup_config_request_user = user_id
        self.async_write_ha_state()
        self.hass.bus.async_fire(
            EVENT_OPEN_CONFIG,
            {
                "section": "wakeup",
                "entry_id": self._entry_id,
                "request_id": self.coordinator.wakeup_config_request_id,
                "user_id": user_id,
            },
        )


class WohnsinnigVernetztStartWakeUpButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Startet das Wake-Up Light sofort manuell (0 % → 100 % über die eingestellte Dimm-Dauer)."""

    _device_section = DEVICE_SECTION_WAKEUP
    _attr_name = "Jetzt starten"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "wakeup_start_now")

    async def async_press(self) -> None:
        await self.coordinator.wakeup_manager.async_start_now(is_scheduled=False)


class WohnsinnigVernetztStopWakeUpButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Bricht ein laufendes Wake-Up Light ab und aktiviert pausierte Automationen sofort wieder."""

    _device_section = DEVICE_SECTION_WAKEUP
    _attr_name = "Abbrechen"
    _attr_icon = "mdi:stop-circle-outline"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "wakeup_stop_now")

    async def async_press(self) -> None:
        await self.coordinator.wakeup_manager.async_stop(cancelled=True)


class WohnsinnigVernetztOpenPvConfigButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Öffnet direkt den PV-Überschuss-Dialog (Sensoren & beliebig viele Aktionen verwalten)."""

    _device_section = DEVICE_SECTION_PV
    _attr_name = "Konfiguration öffnen"
    _attr_icon = "mdi:tune-variant"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "pv_open_config")

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "wv_open_config": "pv",
            "open_request_id": self.coordinator.pv_config_request_id,
            "open_request_user": self.coordinator.pv_config_request_user,
        }

    async def async_press(self) -> None:
        user_id = self._context.user_id if self._context else None
        self.coordinator.pv_config_request_id += 1
        self.coordinator.pv_config_request_user = user_id
        self.async_write_ha_state()
        self.hass.bus.async_fire(
            EVENT_OPEN_CONFIG,
            {
                "section": "pv",
                "entry_id": self._entry_id,
                "request_id": self.coordinator.pv_config_request_id,
                "user_id": user_id,
            },
        )


class WohnsinnigVernetztEvaluatePvButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Prüft sofort alle PV-Überschuss-Bedingungen und Aktionen."""

    _device_section = DEVICE_SECTION_PV
    _attr_name = "Jetzt prüfen"
    _attr_icon = "mdi:solar-power"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "pv_evaluate_now")

    async def async_press(self) -> None:
        await self.coordinator.pv_manager.async_evaluate()


class WohnsinnigVernetztResetPvDailyButton(WohnsinnigVernetztEntity, ButtonEntity):
    """Setzt die 1×-pro-Tag-Merker aller PV-Aktionen zurück (z. B. für Geschirrspüler)."""

    _device_section = DEVICE_SECTION_PV
    _attr_name = "Tageszähler zurücksetzen"
    _attr_icon = "mdi:restore"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "pv_reset_daily")

    async def async_press(self) -> None:
        await self.coordinator.pv_manager.async_reset_daily_triggers()


class WohnsinnigVernetztOpenPresenceSensorsConfigButton(
    WohnsinnigVernetztEntity, ButtonEntity
):
    """Öffnet direkt den Dialog zum Anlegen/Bearbeiten kombinierter Anwesenheitssensoren."""

    _device_section = DEVICE_SECTION_PRESENCE_SENSORS
    _attr_name = "Konfiguration öffnen"
    _attr_icon = "mdi:tune-variant"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "presence_sensors_open_config")

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "wv_open_config": "presence_sensors",
            "open_request_id": self.coordinator.presence_sensors_config_request_id,
            "open_request_user": self.coordinator.presence_sensors_config_request_user,
        }

    async def async_press(self) -> None:
        user_id = self._context.user_id if self._context else None
        self.coordinator.presence_sensors_config_request_id += 1
        self.coordinator.presence_sensors_config_request_user = user_id
        self.async_write_ha_state()
        self.hass.bus.async_fire(
            EVENT_OPEN_CONFIG,
            {
                "section": "presence_sensors",
                "entry_id": self._entry_id,
                "request_id": self.coordinator.presence_sensors_config_request_id,
                "user_id": user_id,
            },
        )


class WohnsinnigVernetztEvaluatePresenceSensorsButton(
    WohnsinnigVernetztEntity, ButtonEntity
):
    """Prüft sofort alle kombinierten Anwesenheitssensoren neu."""

    _device_section = DEVICE_SECTION_PRESENCE_SENSORS
    _attr_name = "Jetzt prüfen"
    _attr_icon = "mdi:account-search-outline"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "presence_sensors_evaluate_now")

    async def async_press(self) -> None:
        await self.coordinator.presence_sensors_manager.async_evaluate()
