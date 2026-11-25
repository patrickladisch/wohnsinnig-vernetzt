"""Parser und Repair-Issue-Verwaltung für Smart-Home-Eilmeldungen."""

from __future__ import annotations

import json
import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

VALID_SEVERITIES = ("info", "warning", "critical")


def _safe_issue_id(alert_id: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (alert_id or "alert").strip()).strip("_").lower()
    return f"community_alert_{slug[:60] or 'info'}"


def parse_alerts_payload(raw_text: str) -> list[dict]:
    """Parst eine alerts.json (Liste, {alerts: [...]} oder Einzelobjekt) in aktive Meldungen."""
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        if isinstance(payload.get("alerts"), list):
            raw_items = payload["alerts"]
        elif payload.get("title") or payload.get("message"):
            raw_items = [payload]
        else:
            raw_items = []
    elif isinstance(payload, list):
        raw_items = payload
    else:
        return []

    active_alerts: list[dict] = []
    seen_ids: set[str] = set()

    for idx, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        if item.get("active", True) is False:
            continue
        title = str(item.get("title") or "").strip()
        message = str(item.get("message") or "").strip()
        if not title and not message:
            continue

        alert_id = str(item.get("id") or f"alert_{idx}_{title[:24]}").strip()
        if alert_id in seen_ids:
            continue
        seen_ids.add(alert_id)

        severity = str(item.get("severity") or "info").strip().lower()
        if severity not in VALID_SEVERITIES:
            severity = "info"

        active_alerts.append(
            {
                "id": alert_id,
                "title": (title or "Smart-Home-Hinweis")[:160],
                "message": message[:1000],
                "severity": severity,
                "url": str(item.get("url") or "https://www.wohnsinnigvernetzt.de/").strip(),
                "date": str(item.get("date") or "").strip(),
            }
        )

    return active_alerts


def sync_alert_repair_issues(
    hass: HomeAssistant,
    active_alerts: list[dict],
    alerts_enabled: bool,
    tracked_issue_ids: set[str],
) -> set[str]:
    """Erstellt/aktualisiert HA-Reparaturhinweise für aktive Warnungen und räumt alte auf."""
    desired_ids: set[str] = set()

    if alerts_enabled:
        for alert in active_alerts:
            if alert["severity"] not in ("warning", "critical"):
                continue
            issue_id = _safe_issue_id(alert["id"])
            desired_ids.add(issue_id)
            ha_severity = (
                ir.IssueSeverity.CRITICAL
                if alert["severity"] == "critical"
                else ir.IssueSeverity.WARNING
            )
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=False,
                severity=ha_severity,
                translation_key="community_alert",
                translation_placeholders={
                    "title": alert["title"],
                    "message": alert["message"] or alert["title"],
                },
                learn_more_url=alert.get("url") or "https://www.wohnsinnigvernetzt.de/",
            )

    for stale_id in list(tracked_issue_ids - desired_ids):
        ir.async_delete_issue(hass, DOMAIN, stale_id)

    return desired_ids
