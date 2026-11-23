# Wohnsinnig vernetzt – Home Assistant Integration

Hol dir alle Folgen und Home-Assistant-Blueprints von **Wohnsinnig vernetzt** direkt in dein Home Assistant – inklusive Media Player, Episodenliste, automatischer Benachrichtigung bei neuen Folgen und 1-Klick-Blueprint-Import.

## Features
- **Echter Home Assistant Media Player (`media_player.wohnsinnig_vernetzt_player`):** Spielt Episoden direkt über die originale RSS-Tracking-URL im Dashboard-Browser oder auf jedem Home-Assistant-Lautsprecher ab – inklusive Medienbrowser.
- **Direktstart über das Episoden-Dropdown:** Wählst du eine Folge unter *Folge auswählen & abspielen*, startet sofort die Wiedergabe auf dem gewählten Wiedergabe-Gerät.
- **Blueprints direkt importieren:** Lädt automatisch alle aktuellen Blueprints von `www.wohnsinnigvernetzt.de` und importiert sie per 1-Klick-Button (einzeln oder alle auf einmal) direkt in deinen Home-Assistant-Ordner `blueprints/<domain>/wohnsinnig_vernetzt/`.
- **Optionaler Spotify-Embed-Modus:** Hinterlege in den Optionen eure Spotify-Show-URL, um in der Dashboard-Karte auf den offiziellen Spotify-Player umzuschalten.
- **Benachrichtigungen bei neuen Folgen:** Direkt auf der Geräteseite ein-/ausschaltbar, mit Mehrfachauswahl deiner `notify`-Dienste, Test-Button und Geräte-Auslöser für Automationen.

## Installation über HACS
1. **HACS** öffnen → oben rechts auf die **drei Punkte** → **Benutzerdefinierte Repositories**.
2. URL dieses Repositories einfügen, Kategorie **Integration** wählen und hinzufügen.
3. Nach **Wohnsinnig vernetzt** suchen und **Herunterladen** klicken.
4. **Home Assistant neu starten**.
5. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **Wohnsinnig vernetzt** suchen.

## Dashboard-Karte hinzufügen
Dashboard bearbeiten → **Karte hinzufügen** → ganz unten **Wohnsinnig vernetzt Player & Blueprints** auswählen.

```yaml
type: custom:wohnsinnig-vernetzt-card
title: Wohnsinnig vernetzt
show_list_default: true
```
