"""Sensor-Entitäten für Podcast, Blueprints, Eilmeldungen und Systemcheck."""

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
    """Erstellt alle Sensoren der Integration."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            WohnsinnigVernetztLatestSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztNewEpisodeAvailableSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztEpisodesSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztBlueprintsSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztAlertSensor(coordinator, entry.entry_id),
            WohnsinnigVernetztSystemcheckSensor(coordinator, entry.entry_id),
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


class WohnsinnigVernetztSystemcheckSensor(WohnsinnigVernetztEntity, SensorEntity):
    """Zeigt das Ergebnis des lokalen Wohnsinnig-vernetzt-Systemchecks."""

    _attr_name = "Systemcheck"
    _unrecorded_attributes = frozenset(
        {"unavailable_entities", "low_battery_entities", "orphaned_entities"}
    )

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "systemcheck")

    @property
    def native_value(self) -> str:
        return self.coordinator.systemcheck_result.get("status", "Ausstehend")

    @property
    def icon(self) -> str:
        issues = self.coordinator.systemcheck_result.get("total_issues", 0)
        return "mdi:stethoscope" if issues > 0 else "mdi:heart-pulse"

    @property
    def extra_state_attributes(self) -> dict:
        res = self.coordinator.systemcheck_result
        return {
            "total_issues": res.get("total_issues", 0),
            "unavailable_count": res.get("unavailable_count", 0),
            "low_battery_count": res.get("low_battery_count", 0),
            "orphaned_count": res.get("orphaned_count", 0),
            "battery_threshold": res.get("battery_threshold", 15),
            "checked_at": res.get("checked_at", ""),
            "unavailable_entities": res.get("unavailable_entities", []),
            "low_battery_entities": res.get("low_battery_entities", []),
            "orphaned_entities": res.get("orphaned_entities", []),
        }
