"""Binary-Sensor-Entitäten für kombinierte Anwesenheitssensoren (Personen & Jemand zuhause)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_SECTION_PRESENCE_SENSORS, DOMAIN
from .coordinator import WohnsinnigVernetztCoordinator
from .entity import WohnsinnigVernetztEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Erstellt 'Jemand zuhause' sowie je eine native Binary-Sensor-Entität pro angelegtem Sensor."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = [
        WohnsinnigVernetztAnyoneHomeBinarySensor(coordinator, entry.entry_id),
    ]
    for sdef in coordinator.presence_sensors_manager.sensor_defs:
        if sdef.get("enabled", True):
            entities.append(
                WohnsinnigVernetztCombinedPresenceBinarySensor(
                    coordinator, entry.entry_id, sdef["id"], sdef["name"]
                )
            )
    async_add_entities(entities)


class WohnsinnigVernetztAnyoneHomeBinarySensor(
    WohnsinnigVernetztEntity, BinarySensorEntity
):
    """Gesamt-Anwesenheitssensor: Zuhause sobald mind. 1 Person anwesend ist (ideal für Alarmanlage)."""

    _device_section = DEVICE_SECTION_PRESENCE_SENSORS
    _attr_name = "Jemand zuhause"
    _attr_device_class = BinarySensorDeviceClass.PRESENCE

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "presence_anyone_home")

    @property
    def is_on(self) -> bool:
        return bool(
            self.coordinator.presence_sensors_manager.get_overview_snapshot()[
                "anyone_home"
            ]
        )

    @property
    def icon(self) -> str:
        return "mdi:home-account" if self.is_on else "mdi:home-export-outline"

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.presence_sensors_manager.get_overview_snapshot()
        return {
            "status": snap["status"],
            "zuhause_anzahl": snap["home_count"],
            "abwesend_anzahl": snap["away_count"],
            "personen_zuhause": snap["home_names"],
            "personen_abwesend": snap["away_names"],
            "sensoren_gesamt": snap["sensors_count"],
        }


class WohnsinnigVernetztCombinedPresenceBinarySensor(
    WohnsinnigVernetztEntity, BinarySensorEntity
):
    """Individueller kombinierter Anwesenheitssensor (Standort + WLAN + Bewegungsmelder-Timeout)."""

    _device_section = DEVICE_SECTION_PRESENCE_SENSORS
    _attr_device_class = BinarySensorDeviceClass.PRESENCE

    def __init__(
        self,
        coordinator: WohnsinnigVernetztCoordinator,
        entry_id: str,
        sensor_id: str,
        sensor_name: str,
    ) -> None:
        super().__init__(coordinator, entry_id, f"presence_sensor_{sensor_id}")
        self._sensor_id = sensor_id
        self._attr_name = sensor_name

    @property
    def is_on(self) -> bool:
        st = self.coordinator.presence_sensors_manager.get_sensor_state(self._sensor_id)
        return bool(st.get("is_present", False))

    @property
    def icon(self) -> str:
        return "mdi:account-check" if self.is_on else "mdi:account-arrow-right-outline"

    @property
    def extra_state_attributes(self) -> dict:
        st = self.coordinator.presence_sensors_manager.get_sensor_state(self._sensor_id)
        return {
            "status_text": st.get("status_text", ""),
            "grund": st.get("reason", ""),
            "modus": st.get("combine_mode", ""),
            "standort_zuhause": st.get("location_present"),
            "standort_details": st.get("location_details", []),
            "wlan_verbunden": st.get("wifi_present"),
            "wlan_details": st.get("wifi_details", []),
            "bewegung_aktiv": st.get("motion_present"),
            "bewegung_timeout_min": st.get("motion_timeout_minutes"),
            "letzte_bewegung_vor_min": st.get("last_motion_ago_min"),
            "bewegung_details": st.get("motion_details", []),
            "extras_aktiv": st.get("extra_present"),
            "extras_details": st.get("extra_details", []),
            "abwesend_verzoegerung_min": st.get("away_delay_minutes"),
            "warte_auf_abwesend": st.get("waiting_for_away", False),
            "abwesend_in_min": st.get("away_in_min", 0),
            "in_gesamt_einbeziehen": st.get("include_in_anyone_home", True),
            "letzte_aenderung": st.get("last_changed", ""),
        }
