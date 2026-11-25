# Wohnsinnig vernetzt – Home Assistant Integration

Die offizielle Smart-Home-Integration zum Podcast **Wohnsinnig vernetzt** (von Niels und Patrick – [wohnsinnigvernetzt.de](https://www.wohnsinnigvernetzt.de)).

## Features (v2.0.0)
- **Podcast-Player & Episodenliste:** Kompakte Dashboard-Karte (`custom:wohnsinnig-vernetzt-card`) zum direkten Anhören sowie eine native `media_player`-Entität für Lautsprecher im Haus.
- **Native Blueprint-Updates:** Importiert alle Blueprints von `wohnsinnigvernetzt.de` per Klick direkt nach Home Assistant und überwacht installierte Blueprints über eine native `update`-Entität – inklusive 1-Klick-Update unter *Einstellungen → Updates*.
- **Interaktive Push-Nachrichten mit Episoden-Infografik:** Stellt die Episoden-Infografik als `image`-Entität bereit und schickt bei neuen Folgen eine Push-Nachricht mit Vorschaubild sowie zwei direkten Action-Buttons (**▶️ Folge abspielen** und **✅ Als gesehen markieren**) – ganz ohne eigene Automation.
- **Smart-Home-Eilmeldungen („Niels & Patrick warnen“):** Optional abschaltbarer Hinweis-Sensor + Home Assistant Repair-Hinweis für akute Smart-Home-Warnungen über `alerts.json`.
- **Lokaler Systemcheck:** Prüft 100 % lokal auf nicht verfügbare Entitäten, schwache Batterien (Schwellwert konfigurierbar) und verwaiste Entitäten.

## Installation über HACS
1. **HACS** öffnen → oben rechts auf die **drei Punkte** → **Benutzerdefinierte Repositories**.
2. URL dieses Repositories einfügen, Kategorie **Integration** wählen und hinzufügen.
3. Nach **Wohnsinnig vernetzt** suchen und **Herunterladen** klicken.
4. **Home Assistant neu starten**.
5. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **Wohnsinnig vernetzt** suchen.

## Dashboard-Karten
- Podcast-Player: `type: custom:wohnsinnig-vernetzt-card`
- Blueprint-Manager: `type: custom:wohnsinnig-vernetzt-blueprints-card`

## Format für Smart-Home-Eilmeldungen (`alerts.json`)
Eine Beispiel-Datei liegt im Repository unter `docs/alerts.example.json`. Lege die Datei unter `https://www.wohnsinnigvernetzt.de/alerts.json` ab – ist sie nicht vorhanden oder sind alle Einträge auf `"active": false`, bleibt alles ruhig.
