"""Hilfsfunktionen zum Erkennen von Smartphones (Companion App) und Notify-Diensten."""

from __future__ import annotations

import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import NOTIFY_ALL_MOBILE_APPS, NOTIFY_NONE


def _slugify_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _mobile_app_device_names(hass: HomeAssistant) -> dict[str, str]:
    """Ordnet mobile_app-Service-Slugs ihren echten Gerätenamen aus der Device Registry zu."""
    mapping: dict[str, str] = {}
    try:
        dev_reg = dr.async_get(hass)
        for device in dev_reg.devices.values():
            if not any(isinstance(i, (tuple, list)) and len(i) >= 1 and i[0] == "mobile_app" for i in (device.identifiers or ())):
                continue
            friendly = (device.name_by_user or device.name or "").strip()
            if not friendly:
                continue
            slug = _slugify_name(friendly)
            if slug:
                mapping[f"mobile_app_{slug}"] = friendly
            if device.name and device.name != friendly:
                orig_slug = _slugify_name(device.name)
                if orig_slug:
                    mapping[f"mobile_app_{orig_slug}"] = friendly
    except Exception:
        pass
    return mapping


def _prettify_mobile_slug(service_name: str) -> str:
    raw = service_name.removeprefix("mobile_app_")
    return raw.replace("_", " ").strip().title() or service_name


def _truncate_label(text: str, max_len: int = 26) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "…"


def get_mobile_app_services(hass: HomeAssistant) -> list[str]:
    """Gibt alle registrierten notify.mobile_app_* Dienste zurück."""
    notify_domain = hass.services.async_services().get("notify", {})
    return [
        f"notify.{name}"
        for name in sorted(notify_domain.keys())
        if name.startswith("mobile_app_")
    ]


def get_notify_choices(
    hass: HomeAssistant,
    current: list[str] | None = None,
    compact: bool = False,
) -> list[tuple[str, str]]:
    """Liefert eine geordnete Liste von (service_id, anzeigename) für Handys & Notify-Dienste."""
    current = current or []
    notify_domain = hass.services.async_services().get("notify", {})
    device_names = _mobile_app_device_names(hass)

    choices: list[tuple[str, str]] = []
    seen: set[str] = set()
    used_labels: set[str] = set()

    def _add(svc_id: str, label: str) -> None:
        final_label = _truncate_label(label, 26) if compact else label
        if final_label in used_labels:
            suffix = f" ({len(used_labels) + 1})"
            base_len = max(6, (26 if compact else 80) - len(suffix))
            final_label = f"{final_label[:base_len].rstrip()}{suffix}"
        used_labels.add(final_label)
        choices.append((svc_id, final_label))
        seen.add(svc_id)

    mobile_services = [
        name for name in sorted(notify_domain.keys()) if name.startswith("mobile_app_")
    ]

    # 1. Alle erkannten Smartphones (Home Assistant Companion App) ganz oben
    for svc_name in mobile_services:
        full_id = f"notify.{svc_name}"
        friendly = device_names.get(svc_name) or _prettify_mobile_slug(svc_name)
        label = f"📱 {friendly}" if compact else f"📱 {friendly} ({full_id})"
        _add(full_id, label)

    # 2. Option für alle Handys gemeinsam (sobald mindestens 2 Handys vorhanden sind)
    if len(mobile_services) >= 2:
        _add(
            NOTIFY_ALL_MOBILE_APPS,
            "📱 Alle Handys" if compact else "📱 Alle Handys (Companion App)",
        )

    # 3. Home Assistant Seitenleiste (persistente Benachrichtigung)
    _add(
        "persistent_notification.create",
        "🔔 HA Seitenleiste"
        if compact
        else "🔔 Home Assistant Seitenleiste (persistent_notification.create)",
    )

    # 4. Weitere notify-Dienste (z. B. Telegram, Pushover, Mail)
    for svc_name in sorted(notify_domain.keys()):
        if svc_name in ("send_message", "persistent_notification") or svc_name.startswith(
            "mobile_app_"
        ):
            continue
        full_id = f"notify.{svc_name}"
        if full_id not in seen:
            label = f"📨 {svc_name}" if compact else f"📨 {svc_name} ({full_id})"
            _add(full_id, label)

    # 5. Eventuell bereits konfigurierte benutzerdefinierte Dienste beibehalten
    for svc_id in current:
        if svc_id and svc_id not in seen and svc_id != NOTIFY_NONE:
            _add(svc_id, svc_id)

    # 6. Deaktiviert-Option für das Geräte-Dropdown
    _add(NOTIFY_NONE, "🔕 Kein Push" if compact else "🔕 Kein Push-Gerät ausgewählt")

    return choices
