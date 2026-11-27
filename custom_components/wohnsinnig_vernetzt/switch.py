"""Switch-Entitäten für Benachrichtigungen und Smart-Home-Eilmeldungen."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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
    """Erstellt die Konfigurationsschalter."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            WohnsinnigVernetztPresenceSimulationSwitch(coordinator, entry.entry_id),
            WohnsinnigVernetztNotifySwitch(coordinator, entry.entry_id),
            WohnsinnigVernetztAlertsSwitch(coordinator, entry.entry_id),
            WohnsinnigVernetztBatteryPushSwitch(coordinator, entry.entry_id),
        ]
    )


class WohnsinnigVernetztNotifySwitch(WohnsinnigVernetztEntity, SwitchEntity):
    """Schaltet automatische Benachrichtigungen bei neuen Folgen ein oder aus."""

    _attr_name = "Benachrichtigungen aktiv"
    _attr_icon = "mdi:bell-ring"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "notifications_enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.notifications_enabled

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "notify_services": self.coordinator.notify_services,
        }

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_notifications_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_notifications_enabled(False)


class WohnsinnigVernetztAlertsSwitch(WohnsinnigVernetztEntity, SwitchEntity):
    """Schaltet Smart-Home-Eilmeldungen („Niels & Patrick warnen“) ein oder aus."""

    _attr_name = "Eilmeldungen aktiv"
    _attr_icon = "mdi:shield-alert-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "alerts_enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.alerts_enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_alerts_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_alerts_enabled(False)


class WohnsinnigVernetztBatteryPushSwitch(WohnsinnigVernetztEntity, SwitchEntity):
    """Schaltet proaktive Batterie-Push-Meldungen (ohne Spam) ein oder aus."""

    _attr_name = "Batterie-Push aktiv"
    _attr_icon = "mdi:battery-alert"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "battery_push_enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.battery_push_enabled

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "modus": self.coordinator.battery_push_mode,
            "uhrzeit": self.coordinator.battery_push_time,
            "grenze": f"< {self.coordinator.battery_threshold} %",
            "reset_ab": f"≥ {self.coordinator.get_battery_reset_threshold()} %",
            "bereits_gemeldet_anzahl": len(self.coordinator.notified_low_batteries),
            "bereits_gemeldet": [
                f"{info.get('name', key)} ({info.get('level', '?')} %)"
                for key, info in self.coordinator.notified_low_batteries.items()
            ],
        }

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_battery_push_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_battery_push_enabled(False)


class WohnsinnigVernetztPresenceSimulationSwitch(WohnsinnigVernetztEntity, SwitchEntity):
    """HAUPTSCHALTER für die Anwesenheitssimulation (1:1 Verlauf vor 2 Wochen ± 7 Min)."""

    _attr_name = "Anwesenheitssimulation"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "presence_simulation_enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.presence_manager.enabled

    @property
    def icon(self) -> str:
        return (
            "mdi:home-account"
            if self.coordinator.presence_manager.enabled
            else "mdi:home-outline"
        )

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.presence_manager.get_status_snapshot()
        return {
            "status": snap["status"],
            "geraete_anzahl": snap["entities_count"],
            "ausgewaehlte_geraete": snap["entity_names"],
            "versatz": f"vor {snap['days_offset']} Tagen",
            "zufall_abweichung": f"± {snap['jitter_minutes']} Min",
            "datenquelle": snap["data_source"],
            "naechste_schaltung": snap["next_event"],
            "pausierte_automationen": snap["paused_automation_names"],
            "abgewehrte_eingriffe": snap["blocked_interferences"],
        }

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_presence_simulation_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_presence_simulation_enabled(False)
