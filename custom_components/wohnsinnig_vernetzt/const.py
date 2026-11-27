"""Konstanten für Wohnsinnig vernetzt."""

DOMAIN = "wohnsinnig_vernetzt"
VERSION = "2.9.0"

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
EVENT_OPEN_CONFIG = f"{DOMAIN}_open_config"
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

DEVICE_SECTION_AUDIO = "audio"
DEVICE_SECTION_PRESENCE = "presence"
DEVICE_SECTION_BLUEPRINTS = "blueprints"
DEVICE_SECTION_CHECKS = "checks"
DEVICE_SECTION_WAKEUP = "wakeup"
DEVICE_SECTION_PV = "pv"

DEVICE_NAME = "Wohnsinnig vernetzt – Audio & Podcast"
DEVICE_MODEL = "Podcast: Wohnsinnig vernetzt"
DEVICE_MANUFACTURER = "Niels und Patrick – www.wohnsinnigvernetzt.de"
DEVICE_CONFIG_URL = "https://www.wohnsinnigvernetzt.de"
DEVICE_INTEGRATION_CONFIG_URL = (
    f"homeassistant://config/integrations/integration/{DOMAIN}"
)

CARD_URL_BASE = f"/{DOMAIN}"
CARD_FILENAME = "wohnsinnig-vernetzt-card.js"

# Wake-Up Light
WAKEUP_MODE_REACH_100 = "reach_100"
WAKEUP_MODE_START_AT = "start_at"
WAKEUP_MODE_LABELS = {
    WAKEUP_MODE_REACH_100: "100% um (Weckzeit)",
    WAKEUP_MODE_START_AT: "Startet um (Startzeit)",
}

WAKEUP_DAYS_DAILY = "daily"
WAKEUP_DAYS_WORKDAYS = "workdays"
WAKEUP_DAYS_WEEKEND = "weekend"
WAKEUP_DAYS_LABELS = {
    WAKEUP_DAYS_DAILY: "Jeden Tag",
    WAKEUP_DAYS_WORKDAYS: "Werktags (Mo–Fr)",
    WAKEUP_DAYS_WEEKEND: "Wochenende (Sa–So)",
}

DEFAULT_WAKEUP_MODE = WAKEUP_MODE_REACH_100
DEFAULT_WAKEUP_TIME = "07:00"
DEFAULT_WAKEUP_DURATION = 30
DEFAULT_WAKEUP_AUTO_OFF_MINUTES = 0
DEFAULT_WAKEUP_DAYS = WAKEUP_DAYS_DAILY
DEFAULT_WAKEUP_AUTO_PAUSE = True
DEFAULT_WAKEUP_SUNRISE_COLOR = True
DEFAULT_WAKEUP_ALARM_ENTITY = ""
WAKEUP_ALARM_MANUAL = ""

CONF_WAKEUP_ENTITIES = "wakeup_entities"
CONF_WAKEUP_MODE = "wakeup_mode"
CONF_WAKEUP_TIME = "wakeup_time"
CONF_WAKEUP_DURATION = "wakeup_duration"
CONF_WAKEUP_AUTO_OFF_MINUTES = "wakeup_auto_off_minutes"
CONF_WAKEUP_DAYS = "wakeup_days"
CONF_WAKEUP_AUTO_PAUSE = "wakeup_auto_pause"
CONF_WAKEUP_PAUSE_AUTOMATIONS = "wakeup_pause_automations"
CONF_WAKEUP_SUNRISE_COLOR = "wakeup_sunrise_color"
CONF_WAKEUP_ALARM_ENTITY = "wakeup_alarm_entity"

EVENT_WAKEUP_STARTED = f"{DOMAIN}_wakeup_started"
EVENT_WAKEUP_COMPLETED = f"{DOMAIN}_wakeup_completed"
EVENT_WAKEUP_CANCELLED = f"{DOMAIN}_wakeup_cancelled"
EVENT_WAKEUP_AUTO_OFF = f"{DOMAIN}_wakeup_auto_off"

SERVICE_START_WAKEUP = "start_wakeup_light"
SERVICE_STOP_WAKEUP = "stop_wakeup_light"

# PV-Überschuss & Solar-Manager
PV_TRIGGER_SURPLUS = "surplus"
PV_TRIGGER_BATTERY = "battery"
PV_TRIGGER_EITHER = "either"
PV_TRIGGER_BOTH = "both"
PV_TRIGGER_MODE_LABELS = {
    PV_TRIGGER_EITHER: "Überschuss ODER PV-Akku",
    PV_TRIGGER_SURPLUS: "Nur PV-Überschuss (Watt)",
    PV_TRIGGER_BATTERY: "Nur PV-Akku (%)",
    PV_TRIGGER_BOTH: "Überschuss UND PV-Akku",
}

PV_ACTION_TURN_ON = "turn_on"
PV_ACTION_PRESS_BUTTON = "press_button"
PV_ACTION_RUN_SCRIPT = "run_script"
PV_ACTION_ACTIVATE_SCENE = "activate_scene"
PV_ACTION_TRIGGER_AUTOMATION = "trigger_automation"
PV_ACTION_TYPE_LABELS = {
    PV_ACTION_TURN_ON: "Einschalten (Steckdose / Wallbox / Schalter)",
    PV_ACTION_PRESS_BUTTON: "Taste drücken (z. B. Geschirrspüler)",
    PV_ACTION_RUN_SCRIPT: "Skript ausführen",
    PV_ACTION_ACTIVATE_SCENE: "Szene aktivieren",
    PV_ACTION_TRIGGER_AUTOMATION: "Automation auslösen",
}

DEFAULT_PV_SURPLUS_ENTITY = ""
DEFAULT_PV_BATTERY_ENTITY = ""
DEFAULT_PV_INVERT_SURPLUS = False

CONF_PV_SURPLUS_ENTITY = "pv_surplus_entity"
CONF_PV_BATTERY_ENTITY = "pv_battery_entity"
CONF_PV_INVERT_SURPLUS = "pv_invert_surplus"
CONF_PV_RULES = "pv_rules"

EVENT_PV_ACTION_TRIGGERED = f"{DOMAIN}_pv_action_triggered"
EVENT_PV_ACTION_STOPPED = f"{DOMAIN}_pv_action_stopped"

SERVICE_EVALUATE_PV = "evaluate_pv_surplus"
SERVICE_RESET_PV_DAILY = "reset_pv_daily_triggers"
