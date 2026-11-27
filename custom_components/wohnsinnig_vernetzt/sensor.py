"""Sensor-Entitäten für Podcast, Blueprints, Eilmeldungen und Batterie-Check."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEVICE_SECTION_BLUEPRINTS,
    DEVICE_SECTION_CHECKS,
    DEVICE_SECTION_PRESENCE,
    DEVICE_SECTION_WAKEUP,
    DOMAIN,
)
from .coordinator import WohnsinnigVernetztCoordinator
from .entity import WohnsinnigVernetztEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Erstellt alle Sensoren der Integration."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            WohnsinnigVernetztLatestSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztNewEpisodeAvailableSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztEpisodesSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztBlueprintsSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztAlertSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztBatteryCheckSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztSilentSensorsSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztPresenceStatusSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztWakeUpStatusSensor(coordinator, entry.entry_id),
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


class WohnsinnigVernetztNewEpisodeAvailableSensor(
    WohnsinnigVernetztEntity, SensorEntity
):
    """Gibt JA oder NEIN aus, je nachdem ob eine neuere Folge erschienen ist."""

    _attr_name = "Neue Folge verfügbar"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "new_episode_available")

    @property
    def native_value(self) -> str:
        return "JA" if self.coordinator.has_newer_episode() else "NEIN"

    @property
    def icon(self) -> str:
        return (
            "mdi:bell-badge"
            if self.coordinator.has_newer_episode()
            else "mdi:check-circle-outline"
        )

    @property
    def extra_state_attributes(self) -> dict:
        episodes = self.coordinator.get_episodes()
        latest = episodes[0] if episodes else {}
        return {
            "neueste_folge": latest.get("title", ""),
            "letzte_bekannte_folge": self.coordinator.acknowledged_latest_title,
            "neue_folgen_anzahl": self.coordinator.newer_episodes_count(),
            "veroeffentlicht_am": latest.get("pub_date", ""),
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
    """Zeigt alle verfügbaren Blueprints inkl. Import- und Update-Status."""

    _device_section = DEVICE_SECTION_BLUEPRINTS
    _attr_name = "Verfügbare Blueprints"
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
            "updates_available_count": sum(
                1 for bp in bps if bp.get("update_available")
            ),
            "last_error": self.coordinator.blueprints_last_error,
            "blueprints": [
                {
                    "title": bp["title"],
                    "description": bp.get("description", ""),
                    "url": bp["url"],
                    "installed": bp.get("installed", False),
                    "update_available": bp.get("update_available", False),
                    "installed_path": bp.get("installed_path", ""),
                }
                for bp in bps
            ],
        }


class WohnsinnigVernetztAlertSensor(WohnsinnigVernetztEntity, SensorEntity):
    """Zeigt aktive Smart-Home-Eilmeldungen („Niels & Patrick warnen“)."""

    _attr_name = "Eilmeldung"
    _unrecorded_attributes = frozenset({"all_alerts"})

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "community_alert")

    @property
    def native_value(self) -> str:
        if not self.coordinator.alerts_enabled:
            return "Deaktiviert"
        alerts = self.coordinator.get_alerts()
        if not alerts:
            return "Keine Meldung"
        return alerts[0]["title"][:255]

    @property
    def icon(self) -> str:
        if not self.coordinator.alerts_enabled:
            return "mdi:shield-off-outline"
        alerts = self.coordinator.get_alerts()
        if not alerts:
            return "mdi:shield-check-outline"
        sev = alerts[0].get("severity", "info")
        if sev == "critical":
            return "mdi:alert-decagram"
        if sev == "warning":
            return "mdi:alert-circle"
        return "mdi:information-outline"

    @property
    def extra_state_attributes(self) -> dict:
        alerts = self.coordinator.get_alerts() if self.coordinator.alerts_enabled else []
        top = alerts[0] if alerts else {}
        return {
            "active": bool(alerts),
            "alerts_enabled": self.coordinator.alerts_enabled,
            "alerts_count": len(alerts),
            "severity": top.get("severity", "none"),
            "message": top.get("message", ""),
            "url": top.get("url", ""),
            "date": top.get("date", ""),
            "all_alerts": alerts,
        }


class WohnsinnigVernetztBatteryCheckSensor(WohnsinnigVernetztEntity, SensorEntity):
    """Zeigt alle Geräte mit weniger als 15 % Batteriestand an."""

    _device_section = DEVICE_SECTION_CHECKS
    _attr_name = "Batterie-Check"
    _unrecorded_attributes = frozenset({"geraete", "devices", "ausgeschlossene_geraete", "excluded_devices"})

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "battery_check")

    @property
    def native_value(self) -> str:
        res = self.coordinator.battery_check_result
        return res.get("summary_text") or res.get("status", "Ausstehend")

    @property
    def icon(self) -> str:
        count = self.coordinator.battery_check_result.get("low_battery_count", 0)
        return (
            "mdi:battery-alert-variant-outline"
            if count > 0
            else "mdi:battery-check-outline"
        )

    @property
    def extra_state_attributes(self) -> dict:
        res = self.coordinator.battery_check_result
        threshold = res.get("battery_threshold", 15)
        geraete = res.get("geraete", [])
        return {
            "status": res.get("status", "OK"),
            "anzahl": res.get("low_battery_count", 0),
            "schwellwert": f"< {threshold} %",
            "reset_schwellwert": f"≥ {self.coordinator.get_battery_reset_threshold()} %",
            "bereits_gemeldet": len(self.coordinator.notified_low_batteries),
            "geprueft_am": res.get("checked_at", ""),
            "geraete": geraete if geraete else [f"Keine Geräte unter {threshold} %"],
            "devices": res.get("devices", []),
            "ausgeschlossen_anzahl": res.get("excluded_count", 0),
            "ausgeschlossene_geraete": res.get("excluded_names", []),
            "excluded_devices": res.get("excluded_devices", []),
        }


class WohnsinnigVernetztSilentSensorsSensor(WohnsinnigVernetztEntity, SensorEntity):
    """Zeigt alle physischen Sensoren an, die stumm eingefroren sind (> X Stunden ohne Update)."""

    _device_section = DEVICE_SECTION_CHECKS
    _attr_name = "Stille Sensoren"
    _unrecorded_attributes = frozenset({"geraete", "devices"})

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "silent_sensors")

    @property
    def native_value(self) -> str:
        res = self.coordinator.silent_sensors_result
        return res.get("summary_text") or res.get("status", "Ausstehend")

    @property
    def icon(self) -> str:
        count = self.coordinator.silent_sensors_result.get("silent_count", 0)
        return "mdi:sleep" if count > 0 else "mdi:access-point-check"

    @property
    def extra_state_attributes(self) -> dict:
        res = self.coordinator.silent_sensors_result
        hours = res.get("silent_hours", self.coordinator.silent_hours)
        geraete = res.get("geraete", [])
        return {
            "status": res.get("status", "Alle aktiv"),
            "anzahl": res.get("silent_count", 0),
            "schwellwert": f"> {hours} h",
            "geprueft_am": res.get("checked_at", ""),
            "geraete": geraete if geraete else [f"Alle Sensoren aktiv (< {hours} h)"],
            "devices": res.get("devices", []),
        }


class WohnsinnigVernetztPresenceStatusSensor(WohnsinnigVernetztEntity, SensorEntity):
    """Zeigt Status, Datenquelle, geplante Schaltungen und abgewehrte Bewegungsmelder-Eingriffe."""

    _device_section = DEVICE_SECTION_PRESENCE
    _attr_name = "Status"
    _unrecorded_attributes = frozenset(
        {"geplante_schaltungen", "upcoming", "ausgewaehlte_geraete", "pausierte_automationen"}
    )

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "presence_simulation_status")

    @property
    def native_value(self) -> str:
        return self.coordinator.presence_manager.get_status_snapshot()["status"]

    @property
    def icon(self) -> str:
        return (
            "mdi:shield-home"
            if self.coordinator.presence_manager.enabled
            else "mdi:home-clock-outline"
        )

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.presence_manager.get_status_snapshot()
        return {
            "aktiv": snap["enabled"],
            "geraete_anzahl": snap["entities_count"],
            "ausgewaehlte_geraete": snap["entity_names"],
            "entity_ids": snap["entities"],
            "versatz_tage": snap["days_offset"],
            "zufall_minuten": snap["jitter_minutes"],
            "datenquelle": snap["data_source"],
            "verlauf_tage": snap["history_days"],
            "naechste_schaltung": snap["next_event"],
            "geplante_anzahl": snap["scheduled_count"],
            "geplante_schaltungen": snap["upcoming_formatted"],
            "upcoming": snap["upcoming"],
            "pausierte_automationen": snap["paused_automation_names"],
            "abgewehrte_eingriffe": snap["blocked_interferences"],
            "letzter_eingriff": snap["last_interference"],
            "letzte_schaltung": snap["last_action"],
        }


class WohnsinnigVernetztWakeUpStatusSensor(WohnsinnigVernetztEntity, SensorEntity):
    """Zeigt Status, Start-/Zielzeit, Fortschritt und pausierte Automationen des Wake-Up Lights."""

    _device_section = DEVICE_SECTION_WAKEUP
    _attr_name = "Status"
    _unrecorded_attributes = frozenset({"ausgewaehlte_lampen", "pausierte_automationen"})

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "wakeup_light_status")

    @property
    def native_value(self) -> str:
        return self.coordinator.wakeup_manager.get_status_snapshot()["status"]

    @property
    def icon(self) -> str:
        wm = self.coordinator.wakeup_manager
        if wm.is_running:
            return "mdi:weather-sunny"
        return "mdi:weather-sunset-up" if wm.enabled else "mdi:weather-night"

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.wakeup_manager.get_status_snapshot()
        return {
            "aktiv": snap["enabled"],
            "laeuft": snap["is_running"],
            "lampen_anzahl": snap["lamps_count"],
            "ausgewaehlte_lampen": snap["lamp_names"],
            "entity_ids": snap["entities"],
            "modus": snap["mode"],
            "uhrzeit": snap["wakeup_time"],
            "startzeit": snap["start_hhmm"],
            "zielzeit": snap["end_hhmm"],
            "naechster_start": snap["next_start"],
            "dauer_minuten": snap["duration_minutes"],
            "wochentage": snap["weekdays"],
            "fortschritt_prozent": snap["progress_percent"],
            "helligkeit_prozent": snap["brightness_percent"],
            "verbleibende_minuten": snap["remaining_minutes"],
            "automationen_pausieren": snap["auto_pause"],
            "pausierte_automationen": snap["paused_automation_names"],
            "sonnenaufgang_farbe": snap["sunrise_color"],
            "letzter_durchlauf": snap["last_run"],
        }
