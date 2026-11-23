# Wohnsinnig vernetzt – Home Assistant Integration

Hol dir alle Folgen von **Wohnsinnig vernetzt** direkt in Home Assistant – mit echtem Media Player, Episodenliste, automatischer Benachrichtigung bei neuen Folgen und Dashboard-Karte.

## Features
- **Echter Home Assistant Media Player (`media_player.wohnsinnig_vernetzt_player`):** Spielt Episoden direkt über die originale RSS-Tracking-URL im Dashboard-Browser oder auf jedem Home-Assistant-Lautsprecher (z. B. Sonos, Google Cast, Echo/Music Assistant) ab – inklusive Medien-Browser mit allen Folgen.
- **Direktstart über das Episoden-Dropdown:** Sobald du eine Folge unter *Folge auswählen* wählst, startet die Wiedergabe automatisch auf dem eingestellten Wiedergabe-Gerät.
- **Optionaler Spotify-Embed-Modus:** Hinterlege in den Optionen eure Spotify-Show-URL, um direkt in der Dashboard-Karte auf den offiziellen Spotify-Player umzuschalten (für native Spotify-App-Streams).
- **Benachrichtigungen bei neuen Folgen:** Direkt auf der Geräteseite ein-/ausschaltbar, mit Mehrfachauswahl deiner `notify`-Dienste, Test-Button und Geräte-Auslöser für Automationen.

## Installation über HACS
1. **HACS** öffnen → oben rechts auf die **drei Punkte** → **Benutzerdefinierte Repositories**.
2. URL dieses Repositories einfügen, Kategorie **Integration** wählen und hinzufügen.
3. Nach **Wohnsinnig vernetzt** suchen und **Herunterladen** klicken.
4. **Home Assistant neu starten**.
5. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **Wohnsinnig vernetzt** suchen.

## Dashboard-Karte hinzufügen
Dashboard bearbeiten → **Karte hinzufügen** → ganz unten **Wohnsinnig vernetzt Player** auswählen (oder die Standard-Home-Assistant-Mediensteuerung für `media_player.wohnsinnig_vernetzt_player` verwenden).

```yaml
type: custom:wohnsinnig-vernetzt-card
title: Wohnsinnig vernetzt
show_list_default: true
```
