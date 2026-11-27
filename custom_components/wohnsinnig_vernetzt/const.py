"""Konstanten für Wohnsinnig vernetzt."""

DOMAIN = "wohnsinnig_vernetzt"
VERSION = "2.4.0"

DEFAULT_RSS_URL = "https://anchor.fm/s/111a8abd0/podcast/rss"
DEFAULT_BLUEPRINTS_URL = "https://www.wohnsinnigvernetzt.de/"
DEFAULT_ALERTS_URL = "https://www.wohnsinnigvernetzt.de/alerts.json"
DEFAULT_LOGO_URL = "/wohnsinnig_vernetzt/logo.png"
DEFAULT_SPOTIFY_SHOW_URL = ""

DEFAULT_BATTERY_THRESHOLD = 15
DEFAULT_BATTERY_RESET_MIN = 50
DEFAULT_BATTERY_PUSH_ENABLED = True
DEFAULT_BATTERY_PUSH_MODE = "scheduled"
DEFAULT_BATTERY_PUSH_TIME = "18:00"
DEFAULT_SILENT_HOURS = 24

# Anwesenheitssimulation
DEFAULT_PRESENCE_DAYS_OFFSET = 14
DEFAULT_PRESENCE_JITTER_MINUTES = 7
DEFAULT_PRESENCE_AUTO_PAUSE_MOTION = True
PRESENCE_HISTORY_KEEP_DAYS = 22
PRESENCE_HISTORY_STORAGE_KEY = f"{DOMAIN}_presence_history"
PRESENCE_HISTORY_STORAGE_VERSION = 1

BATTERY_PUSH_MODE_SCHEDULED = "scheduled"
BATTERY_PUSH_MODE_IMMEDIATE = "immediate"
BATTERY_PUSH_MODE_LABELS = {
    BATTERY_PUSH_MODE_SCHEDULED: "Gebündelt (Uhrzeit)",
    BATTERY_PUSH_MODE_IMMEDIATE: "Sofort",
}

CONF_RSS_URL = "rss_url"
CONF_BLUEPRINTS_URL = "blueprints_url"
CONF_ALERTS_URL = "alerts_url"
CONF_LOGO_URL = "logo_url"
CONF_SPOTIFY_SHOW_URL = "spotify_show_url"
CONF_NOTIFY_SERVICES = "notify_services"
CONF_NOTIFY_SERVICE = "notify_service"  # Legacy v1.0.0 Kompatibilität
CONF_SCAN_INTERVAL = "scan_interval"
CONF_DEFAULT_TARGET = "default_target"
CONF_BATTERY_THRESHOLD = "battery_threshold"
CONF_BATTERY_EXCLUDED_DEVICES = "battery_excluded_devices"
CONF_BATTERY_PUSH_ENABLED = "battery_push_enabled"
CONF_BATTERY_PUSH_MODE = "battery_push_mode"
CONF_BATTERY_PUSH_TIME = "battery_push_time"
CONF_SILENT_HOURS = "silent_hours"

CONF_PRESENCE_ENTITIES = "presence_entities"
CONF_PRESENCE_PAUSE_AUTOMATIONS = "presence_pause_automations"
CONF_PRESENCE_AUTO_PAUSE_MOTION = "presence_auto_pause_motion"
CONF_PRESENCE_JITTER_MINUTES = "presence_jitter_minutes"

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
EVENT_ALERT_RECEIVED = f"{DOMAIN}_alert"
EVENT_BATTERY_CHECK_COMPLETED = f"{DOMAIN}_battery_check_completed"
EVENT_BATTERY_PUSH_SENT = f"{DOMAIN}_battery_push_sent"
EVENT_SILENT_SENSORS_COMPLETED = f"{DOMAIN}_silent_sensors_completed"
EVENT_PRESENCE_INTERFERENCE_BLOCKED = f"{DOMAIN}_presence_interference_blocked"
SIGNAL_NEW_EPISODE = f"{DOMAIN}_signal_new_episode"

# Interaktive Companion-App-Push-Aktionen
ACTION_PLAY_LATEST = "WV_PLAY_LATEST"
ACTION_MARK_SEEN = "WV_MARK_SEEN"

SERVICE_IMPORT_BLUEPRINT = "import_blueprint"
SERVICE_MARK_EPISODE_SEEN = "mark_episode_seen"
SERVICE_RUN_BATTERY_CHECK = "run_battery_check"
SERVICE_RUN_SILENT_SENSORS_CHECK = "run_silent_sensors_check"
SERVICE_RESET_BATTERY_PUSH_MEMORY = "reset_battery_push_memory"
SERVICE_EXCLUDE_BATTERY_DEVICE = "exclude_battery_device"
SERVICE_INCLUDE_BATTERY_DEVICE = "include_battery_device"

BLUEPRINT_SUBDIR = "wohnsinnig_vernetzt"
ALLOWED_BLUEPRINT_DOMAINS = ("automation", "script")

DEVICE_NAME = "Wohnsinnig vernetzt"
DEVICE_MODEL = "Podcast: Wohnsinnig vernetzt"
DEVICE_MANUFACTURER = "Niels und Patrick – www.wohnsinnigvernetzt.de"
DEVICE_CONFIG_URL = "https://www.wohnsinnigvernetzt.de"

CARD_URL_BASE = f"/{DOMAIN}"
CARD_FILENAME = "wohnsinnig-vernetzt-card.js"
