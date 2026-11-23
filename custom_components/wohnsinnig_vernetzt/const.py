"""Konstanten für Wohnsinnig vernetzt."""

DOMAIN = "wohnsinnig_vernetzt"
VERSION = "1.2.0"

DEFAULT_RSS_URL = "https://anchor.fm/s/111a8abd0/podcast/rss"
DEFAULT_LOGO_URL = "/wohnsinnig_vernetzt/logo.png"
DEFAULT_SPOTIFY_SHOW_URL = ""

CONF_RSS_URL = "rss_url"
CONF_LOGO_URL = "logo_url"
CONF_SPOTIFY_SHOW_URL = "spotify_show_url"
CONF_NOTIFY_SERVICES = "notify_services"
CONF_NOTIFY_SERVICE = "notify_service"  # Legacy v1.0.0 Kompatibilität
CONF_SCAN_INTERVAL = "scan_interval"
CONF_DEFAULT_TARGET = "default_target"

DEFAULT_NOTIFY_SERVICES = ["persistent_notification.create"]
DEFAULT_SCAN_INTERVAL = 30  # Minuten

BROWSER_TARGET = "__browser__"
BROWSER_TARGET_LABEL = "Dashboard-Browser (Karte)"

STORAGE_KEY = f"{DOMAIN}_state"
STORAGE_VERSION = 1

EVENT_NEW_EPISODE = f"{DOMAIN}_new_episode"
SIGNAL_NEW_EPISODE = f"{DOMAIN}_signal_new_episode"

CARD_URL_BASE = f"/{DOMAIN}"
CARD_FILENAME = "wohnsinnig-vernetzt-card.js"
