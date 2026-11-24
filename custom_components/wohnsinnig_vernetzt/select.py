"""Select-Entitäten für Episodenwahl, Wiedergabe-Gerät, Push-Handy und Blueprint-Auswahl."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BROWSER_TARGET, BROWSER_TARGET_LABEL, DOMAIN, NOTIFY_NONE
from .coordinator import WohnsinnigVernetztCoordinator
from .entity import WohnsinnigVernetztEntity
from .media_player import get_available_targets
from .notify_helpers import get_notify_choices


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Erstellt die Auswahlmenüs für Folgen, Wiedergabe-Gerät, Handy-Push und Blueprints."""
    coordinator: WohnsinnigVernetztCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            WohnsinnigVernetztEpisodeSelect(coordinator, entry.entry_id),
            WohnsinnigVernetztTargetSelect(coordinator, entry.entry_id),
            WohnsinnigVernetztNotifyDeviceSelect(coordinator, entry.entry_id),
            WohnsinnigVernetztBlueprintSelect(coordinator, entry.entry_id),
        ]
    )


class WohnsinnigVernetztEpisodeSelect(WohnsinnigVernetztEntity, SelectEntity):
    """Dropdown mit allen Folgen – Auswahl startet direkt den Media Player."""

    _attr_name = "Folge auswählen & abspielen"
    _attr_icon = "mdi:play-box-multiple"

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
        }

    async def async_select_option(self, option: str) -> None:
        mapping = self._option_map()
        ep = mapping.get(option)
        if ep:
            await self.coordinator.async_play_episode(ep["guid"])


class WohnsinnigVernetztTargetSelect(WohnsinnigVernetztEntity, SelectEntity):
    """Wählt aus, ob Folgen im Dashboard-Browser oder auf einem HA-Lautsprecher laufen."""

    _attr_name = "Wiedergabe-Gerät"
    _attr_icon = "mdi:speaker-wireless"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "target_player")

    @property
    def options(self) -> list[str]:
        return list(get_available_targets(self.hass).keys())

    @property
    def current_option(self) -> str | None:
        targets = get_available_targets(self.hass)
        for label, entity_id in targets.items():
            if entity_id == self.coordinator.target_entity:
                return label
        return BROWSER_TARGET_LABEL

    async def async_select_option(self, option: str) -> None:
        targets = get_available_targets(self.hass)
        target_id = targets.get(option, BROWSER_TARGET)
        await self.coordinator.async_set_target_entity(target_id)


class WohnsinnigVernetztNotifyDeviceSelect(WohnsinnigVernetztEntity, SelectEntity):
    """Wählt das Handy (Companion App) für Push-Benachrichtigungen bei neuen Folgen aus."""

    _attr_name = "Handy für Push-Benachrichtigung"
    _attr_icon = "mdi:cellphone-message"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "notify_device_select")

    def _option_map(self) -> dict[str, str]:
        """Liefert {Anzeigename: service_id}."""
        choices = get_notify_choices(self.hass, self.coordinator.notify_services)
        mapping: dict[str, str] = {}
        for svc_id, label in choices:
            mapping[label] = svc_id

        # Falls in den Optionen mehrere Ziele gleichzeitig gewählt wurden
        if len(self.coordinator.notify_services) > 1:
            multi_label = f"📱 Mehrere Ziele ({len(self.coordinator.notify_services)})"
            mapping[multi_label] = "__multi__"
        return mapping

    @property
    def options(self) -> list[str]:
        return list(self._option_map().keys())

    @property
    def current_option(self) -> str | None:
        mapping = self._option_map()
        active = self.coordinator.notify_services
        if not active:
            for label, svc_id in mapping.items():
                if svc_id == NOTIFY_NONE:
                    return label
            return next(iter(mapping.keys()), None)

        if len(active) > 1:
            for label, svc_id in mapping.items():
                if svc_id == "__multi__":
                    return label

        target = active[0]
        for label, svc_id in mapping.items():
            if svc_id == target:
                return label
        return next(iter(mapping.keys()), None)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "active_notify_services": self.coordinator.notify_services,
        }

    async def async_select_option(self, option: str) -> None:
        mapping = self._option_map()
        svc_id = mapping.get(option)
        if not svc_id or svc_id == "__multi__":
            return
        await self.coordinator.async_set_notify_target(svc_id)


class WohnsinnigVernetztBlueprintSelect(WohnsinnigVernetztEntity, SelectEntity):
    """Dropdown mit allen Blueprints von wohnsinnigvernetzt.de."""

    _attr_name = "Blueprint auswählen"
    _attr_icon = "mdi:file-download-outline"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "blueprint_select")

    def _option_map(self) -> dict[str, dict]:
        blueprints = self.coordinator.get_blueprints()
        mapping: dict[str, dict] = {}
        for bp in blueprints:
            prefix = "✓ " if bp.get("installed") else ""
            candidate = f"{prefix}{bp['title']}"[:255]
            if candidate in mapping:
                candidate = f"{candidate[:248]} #{len(mapping) + 1}"
            mapping[candidate] = bp
        return mapping

    @property
    def options(self) -> list[str]:
        opts = list(self._option_map().keys())
        return opts or ["Keine Blueprints gefunden"]

    @property
    def current_option(self) -> str | None:
        mapping = self._option_map()
        if not mapping:
            return "Keine Blueprints gefunden"
        selected = self.coordinator.get_selected_blueprint()
        if selected:
            for label, bp in mapping.items():
                if bp["id"] == selected["id"]:
                    return label
        return next(iter(mapping.keys()))

    @property
    def extra_state_attributes(self) -> dict:
        bp = self.coordinator.get_selected_blueprint() or {}
        return {
            "title": bp.get("title", ""),
            "description": bp.get("description", ""),
            "url": bp.get("url", ""),
            "installed": bp.get("installed", False),
            "installed_path": bp.get("installed_path", ""),
        }

    async def async_select_option(self, option: str) -> None:
        mapping = self._option_map()
        bp = mapping.get(option)
        if bp:
            await self.coordinator.async_set_selected_blueprint(bp["id"])
