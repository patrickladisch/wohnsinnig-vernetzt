"""Konstanten für Wohnsinnig vernetzt."""

DOMAIN = "wohnsinnig_vernetzt"
VERSION = "1.1.1"

DEFAULT_RSS_URL = "https://anchor.fm/s/111a8abd0/podcast/rss"
DEFAULT_LOGO_URL = ""  # Optional: direkte URL zum Website-Logo (sonst RSS-Cover)
DEFAULT_FEEDBACK_WEBHOOK_URL = ""  # z. B. Formspree, n8n, Discord oder eigener Endpoint
DEFAULT_FEEDBACK_FALLBACK_URL = "https://www.wohnsinnigvernetzt.de"

CONF_RSS_URL = "rss_url"
CONF_LOGO_URL = "logo_url"
CONF_NOTIFY_SERVICES = "notify_services"
CONF_NOTIFY_SERVICE = "notify_service"  # Legacy v1.0.0 Kompatibilität
CONF_SCAN_INTERVAL = "scan_interval"
CONF_FEEDBACK_WEBHOOK_URL = "feedback_webhook_url"

DEFAULT_NOTIFY_SERVICES = ["persistent_notification.create"]
DEFAULT_SCAN_INTERVAL = 30  # Minuten

STORAGE_KEY = f"{DOMAIN}_state"
STORAGE_VERSION = 1

EVENT_NEW_EPISODE = f"{DOMAIN}_new_episode"
EVENT_FEEDBACK_SENT = f"{DOMAIN}_feedback_sent"
SIGNAL_NEW_EPISODE = f"{DOMAIN}_signal_new_episode"

SERVICE_SEND_FEEDBACK = "send_feedback"

CARD_URL_BASE = f"/{DOMAIN}"
CARD_FILENAME = "wohnsinnig-vernetzt-card.js"
