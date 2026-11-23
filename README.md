# Wohnsinnig vernetzt – Home Assistant Integration

Hol dir alle Folgen von **Wohnsinnig vernetzt** direkt in Home Assistant – mit Episodenliste, automatischer Benachrichtigung bei neuen Folgen, kompaktem Dashboard-Player und direkter Feedback-Funktion.

## Features
- **Alle Folgen im Blick:** Zeigt die neueste Folge, die Gesamtanzahl inkl. Episodenliste und ein Dropdown-Steuerelement (`select`) mit allen Folgen.
- **Benachrichtigungen bei neuen Folgen:** Ein-/Ausschaltbar direkt auf der Geräteseite, Mehrfachauswahl deiner `notify`-Dienste (z. B. Handy + HA-Seitenleiste), Test-Button und eigener Geräte-Auslöser für Automationen.
- **Dashboard-Player:** Integrierter HTML5-Audioplayer (Play/Pause, -15s/+30s, Geschwindigkeit 1x–2x, Fortschrittsbalken, Episodensuche & komplette Liste).
- **Feedback senden:** Direkt über die Dashboard-Karte, über die Geräteseite oder per Aktion `wohnsinnig_vernetzt.send_feedback`.

## Installation über HACS
1. **HACS** öffnen → oben rechts auf die **drei Punkte** → **Benutzerdefinierte Repositories**.
2. URL dieses Repositories einfügen, Kategorie **Integration** wählen und hinzufügen.
3. Nach **Wohnsinnig vernetzt** suchen und **Herunterladen** klicken.
4. **Home Assistant neu starten**.
5. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **Wohnsinnig vernetzt** suchen.

## Dashboard-Karte hinzufügen
Dashboard bearbeiten → **Karte hinzufügen** → ganz unten **Wohnsinnig vernetzt Player** auswählen.

```yaml
type: custom:wohnsinnig-vernetzt-card
title: Wohnsinnig vernetzt
show_list_default: true
```

## Integrations-Logo
Das offizielle **Wohnsinnig vernetzt**-Logo ist bereits fertig skaliert im Ordner `custom_components/wohnsinnig_vernetzt/brand/` (`icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`) sowie unter `www/logo.png` für Sensor & Dashboard-Karte enthalten.
