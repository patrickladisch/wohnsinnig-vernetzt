# Wohnsinnig vernetzt – Home Assistant Integration

Die offizielle Smart-Home-Integration zum Podcast **Wohnsinnig vernetzt** (von Niels und Patrick – [wohnsinnigvernetzt.de](https://www.wohnsinnigvernetzt.de)).

## Features (v2.2.0)
- **Podcast-Player & Episodenliste:** Kompakte Dashboard-Karte (`custom:wohnsinnig-vernetzt-card`) zum direkten Anhören sowie eine native `media_player`-Entität für Lautsprecher im Haus.
- **Native Blueprint-Updates:** Importiert alle Blueprints von `wohnsinnigvernetzt.de` per Klick direkt nach Home Assistant und überwacht installierte Blueprints über eine native `update`-Entität – inklusive 1-Klick-Update unter *Einstellungen → Updates*.
- **Interaktive Push-Nachrichten mit Episoden-Infografik:** Stellt die Episoden-Infografik als `image`-Entität bereit und schickt bei neuen Folgen eine Push-Nachricht mit Vorschaubild sowie zwei direkten Action-Buttons (**▶️ Folge abspielen** und **✅ Als gesehen markieren**) – ganz ohne eigene Automation.
- **Smart-Home-Eilmeldungen („Niels & Patrick warnen“):** Optional abschaltbarer Hinweis-Sensor + Home Assistant Repair-Hinweis für akute Smart-Home-Warnungen über `alerts.json`.
- **Batterie-Check & Proaktiver Batterie-Push ohne Spam:** Überwacht lokal alle Batterien unter einer einstellbaren Grenze (Standard: 15 %). Meldet jedes schwache Gerät genau einmal ans gewählte Handy (sofort oder gebündelt zur Wunsch-Uhrzeit) und erst wieder nach einem Batteriewechsel (≥ 50 %).
- **„Stille Sensoren“-Wächter (Zigbee-Freeze-Erkennung):** Erkennt stumm eingefrorene Sensoren (z. B. Aqara, Hue, Tradfri), die trotz fehlendem `unavailable` seit mehr als 24 oder 48 Stunden (frei einstellbar) kein Update mehr geliefert haben – übersichtlich auf einen Klick.

## Installation über HACS
1. **HACS** öffnen → oben rechts auf die **drei Punkte** → **Benutzerdefinierte Repositories**.
2. URL dieses Repositories einfügen, Kategorie **Integration** wählen und hinzufügen.
3. Nach **Wohnsinnig vernetzt** suchen und **Herunterladen** klicken.
4. **Home Assistant neu starten**.
5. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **Wohnsinnig vernetzt** suchen.

## Dashboard-Karten
- Podcast-Player: `type: custom:wohnsinnig-vernetzt-card`
- Blueprint-Manager: `type: custom:wohnsinnig-vernetzt-blueprints-card`
- Batterie-Check: `type: custom:wohnsinnig-vernetzt-battery-card`
- Stille Sensoren: `type: custom:wohnsinnig-vernetzt-silent-sensors-card`
