"""Select-Entitäten für Episodenwahl, Wiedergabe-Gerät, Push-Handy und Blueprint-Auswahl."""

from __future__ import annotations

import re

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BROWSER_TARGET, BROWSER_TARGET_LABEL, DOMAIN, NOTIFY_NONE
from .coordinator import WohnsinnigVernetztCoordinator
from .entity import WohnsinnigVernetztEntity
from .media_player import get_available_targets
from .notify_helpers import get_notify_choices

MAX_SELECT_LABEL_LEN = 28


def compact_select_label(text: str, max_len: int = MAX_SELECT_LABEL_LEN) -> str:
    """Kürzt lange Dropdown-Texte sauber, damit das Menü nie über den Kartenrand läuft."""
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if len(clean) <= max_len:
        return clean

    # Typische Endungen wie " - Teil 1" oder " #12" nach Möglichkeit erhalten
    suffix_match = re.search(r"(\s[-–]\sTeil\s\d+|\s#\d+)$", clean, re.IGNORECASE)
    if suffix_match:
        suffix = suffix_match.group(1)
        head_budget = max_len - len(suffix) - 1
        if head_budget >= 10:
            head = clean[:head_budget].rstrip(" -–:,;")
            return f"{head}…{suffix}"

    cut = clean[: max_len - 1]
    if " " in cut and cut.rfind(" ") >= max_len // 2:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" -–:,;") + "…"


def _dedupe_label(label: str, existing: dict, max_len: int = MAX_SELECT_LABEL_LEN) -> str:
    """Stellt eindeutige Optionen sicher, ohne die Maximalbreite zu sprengen."""
    if label not in existing:
        return label
    counter = 2
    while True:
        suffix = f" ({counter})"
        trimmed = label[: max(6, max_len - len(suffix))].rstrip(" -–:,;…")
        candidate = f"{trimmed}{suffix}"
        if candidate not in existing:
            return candidate
        counter += 1


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
            WohnsinnigVernetztBatteryListSelect(coordinator, entry.entry_id),
        ]
    )


class WohnsinnigVernetztEpisodeSelect(WohnsinnigVernetztEntity, SelectEntity):
    """Dropdown mit allen Folgen – kompakt gekürzt, startet direkt den Media Player."""

    _attr_name = "Podcast: Folge wählen"
    _attr_icon = "mdi:play-box-multiple"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "episode_select")

    def _option_map(self) -> dict[str, dict]:
        episodes = (self.coordinator.data or {}).get("episodes", [])
        mapping: dict[str, dict] = {}
        for ep in episodes:
            label = compact_select_label(ep["title"], MAX_SELECT_LABEL_LEN)
            label = _dedupe_label(label, mapping, MAX_SELECT_LABEL_LEN)
            mapping[label] = ep
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
            "full_title": ep.get("title", ""),
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
    _attr_entity_category = EntityCategory.CONFIG

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

    @property
    def extra_state_attributes(self) -> dict:
        return {"target_entity": self.coordinator.target_entity}

    async def async_select_option(self, option: str) -> None:
        targets = get_available_targets(self.hass)
        target_id = targets.get(option, BROWSER_TARGET)
        await self.coordinator.async_set_target_entity(target_id)


class WohnsinnigVernetztNotifyDeviceSelect(WohnsinnigVernetztEntity, SelectEntity):
    """Wählt das Handy (Companion App) für Push-Benachrichtigungen bei neuen Folgen aus."""

    _attr_name = "Push-Gerät (Handy)"
    _attr_icon = "mdi:cellphone-message"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "notify_device_select")

    def _option_map(self) -> dict[str, str]:
        """Liefert {kompakter Anzeigename: service_id}."""
        choices = get_notify_choices(
            self.hass, self.coordinator.notify_services, compact=True
        )
        mapping: dict[str, str] = {}
        for svc_id, label in choices:
            mapping[label] = svc_id

        if len(self.coordinator.notify_services) > 1:
            multi_label = f"📱 Mehrere ({len(self.coordinator.notify_services)} Ziele)"
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
    """Dropdown mit allen Blueprints von wohnsinnigvernetzt.de (kompakt formatiert)."""

    _attr_name = "Blueprint: Auswählen"
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
            budget = MAX_SELECT_LABEL_LEN - len(prefix)
            short_title = compact_select_label(bp["title"], budget)
            candidate = _dedupe_label(f"{prefix}{short_title}", mapping, MAX_SELECT_LABEL_LEN)
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
            "full_title": bp.get("title", ""),
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


class WohnsinnigVernetztBatteryListSelect(WohnsinnigVernetztEntity, SelectEntity):
    """1-Klick-Dropdown direkt auf der Geräteseite mit allen Batterien unter 15 %."""

    _attr_name = "Batterie: Schwache Geräte"

    def __init__(
        self, coordinator: WohnsinnigVernetztCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, "battery_low_list")

    @property
    def icon(self) -> str:
        count = self.coordinator.battery_check_result.get("low_battery_count", 0)
        return (
            "mdi:battery-alert-variant-outline"
            if count > 0
            else "mdi:battery-check-outline"
        )

    def _header_label(self) -> str:
        res = self.coordinator.battery_check_result
        count = res.get("low_battery_count", 0)
        threshold = res.get("battery_threshold", 15)
        if count == 0:
            return f"✅ Alle OK (≥ {threshold} %)"
        if count == 1:
            return f"🔋 1 Gerät unter {threshold} %"
        return f"🔋 {count} Geräte unter {threshold} %"

    def _build_options(self) -> list[str]:
        res = self.coordinator.battery_check_result
        devices = res.get("devices", [])
        header = self._header_label()
        mapping: dict[str, bool] = {header: True}

        for dev in devices:
            pct = f"{dev['level']}%"
            prefix = f"{pct} · "
            budget = max(8, MAX_SELECT_LABEL_LEN - len(prefix))
            short_name = compact_select_label(dev["name"], budget)
            label = _dedupe_label(f"{prefix}{short_name}", mapping, MAX_SELECT_LABEL_LEN)
            mapping[label] = True

        mapping["🔄 Jetzt neu prüfen"] = True
        return list(mapping.keys())

    @property
    def options(self) -> list[str]:
        return self._build_options()

    @property
    def current_option(self) -> str | None:
        return self._header_label()

    @property
    def extra_state_attributes(self) -> dict:
        res = self.coordinator.battery_check_result
        return {
            "anzahl": res.get("low_battery_count", 0),
            "schwellwert": f"< {res.get('battery_threshold', 15)} %",
            "geprueft_am": res.get("checked_at", ""),
            "geraete": res.get("geraete", []),
        }

    async def async_select_option(self, option: str) -> None:
        if option == "🔄 Jetzt neu prüfen":
            await self.coordinator.async_run_battery_check(notify=False)
        else:
            # Dropdown schließt sauber und zeigt weiterhin die Übersicht im Kopf
            self.async_write_ha_state()
