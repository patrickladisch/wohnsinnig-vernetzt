# Wohnsinnig vernetzt – Home Assistant Integration

Hol dir alle Folgen von **Wohnsinnig vernetzt** direkt in Home Assistant – inklusive Benachrichtigung bei neuen Episoden und kompaktem Podcast-Player fürs Dashboard.

## Features
- Lädt alle Episoden automatisch über den offiziellen RSS-Feed.
- Schickt bei jeder neuen Folge eine Benachrichtigung (z. B. per Companion App oder persistenter Meldung) und feuert das Event `wohnsinnig_vernetzt_new_episode`.
- Bringt eine eigene Dashboard-Karte mit integriertem Audioplayer (Play/Pause, -15s/+30s, Geschwindigkeit 1x–2x, Fortschrittsbalken und ausklappbarer Episodenliste) mit – die Ressource wird automatisch registriert.

## Installation über HACS (empfohlen)
1. **HACS** öffnen → oben rechts auf die **drei Punkte** → **Benutzerdefinierte Repositories**.
2. Die URL dieses GitHub-Repositories einfügen, Kategorie **Integration** wählen und hinzufügen.
3. Nach **Wohnsinnig vernetzt** suchen und **Herunterladen** klicken.
4. **Home Assistant neu starten**.
5. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **Wohnsinnig vernetzt** suchen und einrichten.

## Dashboard-Karte hinzufügen
Dashboard bearbeiten → **Karte hinzufügen** → ganz unten **Wohnsinnig vernetzt Player** auswählen.

Oder direkt als YAML:
```yaml
type: custom:wohnsinnig-vernetzt-card
title: Wohnsinnig vernetzt
show_list_default: false
```
