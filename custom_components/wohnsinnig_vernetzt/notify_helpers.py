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
            if not any(domain == "mobile_app" for domain, _ in device.identifiers):
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


def get_mobile_app_services(hass: HomeAssistant) -> list[str]:
    """Gibt alle registrierten notify.mobile_app_* Dienste zurück."""
    notify_domain = hass.services.async_services().get("notify", {})
    return [
        f"notify.{name}"
        for name in sorted(notify_domain.keys())
        if name.startswith("mobile_app_")
    ]


def get_notify_choices(
    hass: HomeAssistant, current: list[str] | None = None
) -> list[tuple[str, str]]:
    """Liefert eine geordnete Liste von (service_id, anzeigename) für Handys & Notify-Dienste."""
    current = current or []
    notify_domain = hass.services.async_services().get("notify", {})
    device_names = _mobile_app_device_names(hass)

    choices: list[tuple[str, str]] = []
    seen: set[str] = set()

    mobile_services = [
        name for name in sorted(notify_domain.keys()) if name.startswith("mobile_app_")
    ]

    # 1. Alle erkannten Smartphones (Home Assistant Companion App) ganz oben
    for svc_name in mobile_services:
        full_id = f"notify.{svc_name}"
        friendly = device_names.get(svc_name) or _prettify_mobile_slug(svc_name)
        choices.append((full_id, f"📱 {friendly} ({full_id})"))
        seen.add(full_id)

    # 2. Option für alle Handys gemeinsam (sobald mindestens 2 Handys vorhanden sind)
    if len(mobile_services) >= 2:
        choices.append((NOTIFY_ALL_MOBILE_APPS, "📱 Alle Handys (Companion App)"))
        seen.add(NOTIFY_ALL_MOBILE_APPS)

    # 3. Home Assistant Seitenleiste (persistente Benachrichtigung)
    choices.append(
        (
            "persistent_notification.create",
            "🔔 Home Assistant Seitenleiste (persistent_notification.create)",
        )
    )
    seen.add("persistent_notification.create")

    # 4. Weitere notify-Dienste (z. B. Telegram, Pushover, Mail)
    for svc_name in sorted(notify_domain.keys()):
        if svc_name in ("send_message", "persistent_notification") or svc_name.startswith("mobile_app_"):
            continue
        full_id = f"notify.{svc_name}"
        if full_id not in seen:
            choices.append((full_id, f"📨 {svc_name} ({full_id})"))
            seen.add(full_id)

    # 5. Eventuell bereits konfigurierte benutzerdefinierte Dienste beibehalten
    for svc_id in current:
        if svc_id and svc_id not in seen and svc_id != NOTIFY_NONE:
            choices.append((svc_id, svc_id))
            seen.add(svc_id)

    # 6. Deaktiviert-Option für das Geräte-Dropdown
    choices.append((NOTIFY_NONE, "🔕 Kein Push-Gerät ausgewählt"))

    return choices
