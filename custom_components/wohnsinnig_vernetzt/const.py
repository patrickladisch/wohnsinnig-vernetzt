"""Konstanten für Wohnsinnig vernetzt."""

DOMAIN = "wohnsinnig_vernetzt"
VERSION = "1.5.1"

DEFAULT_RSS_URL = "https://anchor.fm/s/111a8abd0/podcast/rss"
DEFAULT_BLUEPRINTS_URL = "https://www.wohnsinnigvernetzt.de/"
DEFAULT_LOGO_URL = "/wohnsinnig_vernetzt/logo.png"
DEFAULT_SPOTIFY_SHOW_URL = ""

CONF_RSS_URL = "rss_url"
CONF_BLUEPRINTS_URL = "blueprints_url"
CONF_LOGO_URL = "logo_url"
CONF_SPOTIFY_SHOW_URL = "spotify_show_url"
CONF_NOTIFY_SERVICES = "notify_services"
CONF_NOTIFY_SERVICE = "notify_service"  # Legacy v1.0.0 Kompatibilität
CONF_SCAN_INTERVAL = "scan_interval"
CONF_DEFAULT_TARGET = "default_target"

DEFAULT_NOTIFY_SERVICES = ["persistent_notification.create"]
DEFAULT_SCAN_INTERVAL = 30  # Minuten

NOTIFY_ALL_MOBILE_APPS = "__all_mobile_apps__"
NOTIFY_NONE = "__none__"

BROWSER_TARGET = "__browser__"
BROWSER_TARGET_LABEL = "Dashboard-Browser"

STORAGE_KEY = f"{DOMAIN}_state"
STORAGE_VERSION = 1

EVENT_NEW_EPISODE = f"{DOMAIN}_new_episode"
EVENT_BLUEPRINT_IMPORTED = f"{DOMAIN}_blueprint_imported"
SIGNAL_NEW_EPISODE = f"{DOMAIN}_signal_new_episode"

SERVICE_IMPORT_BLUEPRINT = "import_blueprint"
SERVICE_MARK_EPISODE_SEEN = "mark_episode_seen"

BLUEPRINT_SUBDIR = "wohnsinnig_vernetzt"
ALLOWED_BLUEPRINT_DOMAINS = ("automation", "script")

DEVICE_NAME = "Wohnsinnig vernetzt"
DEVICE_MODEL = "Podcast: Wohnsinnig vernetzt"
DEVICE_MANUFACTURER = "Niels und Patrick – www.wohnsinnigvernetzt.de"
DEVICE_CONFIG_URL = "https://www.wohnsinnigvernetzt.de"

CARD_URL_BASE = f"/{DOMAIN}"
CARD_FILENAME = "wohnsinnig-vernetzt-card.js"
