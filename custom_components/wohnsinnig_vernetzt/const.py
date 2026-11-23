"""Konstanten für Wohnsinnig vernetzt."""

DOMAIN = "wohnsinnig_vernetzt"
VERSION = "1.0.0"
DEFAULT_RSS_URL = "https://anchor.fm/s/111a8abd0/podcast/rss"

CONF_RSS_URL = "rss_url"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_NOTIFY_SERVICE = "persistent_notification.create"
DEFAULT_SCAN_INTERVAL = 30  # Minuten

STORAGE_KEY = f"{DOMAIN}_seen_episodes"
STORAGE_VERSION = 1

EVENT_NEW_EPISODE = f"{DOMAIN}_new_episode"

CARD_URL_BASE = f"/{DOMAIN}"
CARD_FILENAME = "wohnsinnig-vernetzt-card.js"
