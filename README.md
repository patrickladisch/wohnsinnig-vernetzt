# Wohnsinnig vernetzt – Home Assistant Integration

Die offizielle Smart-Home-Integration zum Podcast **Wohnsinnig vernetzt** (von Niels und Patrick – [wohnsinnigvernetzt.de](https://www.wohnsinnigvernetzt.de)).

## Features (v2.4.1)
- **Anwesenheitssimulation (1:1 Verlauf von vor 2 Wochen ± 7 Min):** Wähle beliebige Lampen und Schalter aus und schalte die Simulation über den Hauptschalter (`switch.wohnsinnig_vernetzt_anwesenheitssimulation`) ein oder aus. Ein eigener rollierender 21-Tage-Verlauf sorgt dafür, dass die 14-Tage-Wiedergabe auch bei Standard-Recorder-Einstellungen (`purge_keep_days: 10`) zuverlässig funktioniert. Doppelter Bewegungsmelder-Schutz (Automations-Pause + Echtzeit-Zustandswächter) verhindert zuverlässig, dass Bewegungsmelder dazwischenfunken.
- **Podcast-Player & Episodenliste:** Kompakte Dashboard-Karte (`custom:wohnsinnig-vernetzt-card`) zum direkten Anhören sowie eine native `media_player`-Entität für Lautsprecher im Haus.
- **Native Blueprint-Updates:** Importiert alle Blueprints von `wohnsinnigvernetzt.de` per Klick direkt nach Home Assistant und überwacht installierte Blueprints über eine native `update`-Entität – inklusive 1-Klick-Update unter *Einstellungen → Updates*.
- **Interaktive Push-Nachrichten mit Episoden-Infografik:** Stellt die Episoden-Infografik als `image`-Entität bereit und schickt bei neuen Folgen eine Push-Nachricht mit Vorschaubild sowie zwei direkten Action-Buttons (**▶️ Folge abspielen** und **✅ Als gesehen markieren**).
- **Smart-Home-Eilmeldungen („Niels & Patrick warnen“):** Optional abschaltbarer Hinweis-Sensor + Home Assistant Repair-Hinweis für akute Smart-Home-Warnungen über `alerts.json`.
- **Batterie-Check mit Ausschlussliste & Proaktivem Push ohne Spam:** Überwacht lokal alle Batterien unter einer einstellbaren Grenze (Standard: 15 %), erlaubt das gezielte Ausschließen und Wiederaufnehmen einzelner Geräte direkt auf der Geräteseite (unter Konfiguration), in den Optionen oder per 1-Klick in der Dashboard-Karte und meldet jedes schwache Gerät genau einmal ans gewählte Handy.
- **„Stille Sensoren“-Wächter (Zigbee-Freeze-Erkennung):** Erkennt stumm eingefrorene Sensoren (z. B. Aqara, Hue, Tradfri), die seit mehr als 24 oder 48 Stunden kein Update mehr geliefert haben.

## Installation über HACS
1. **HACS** öffnen → oben rechts auf die **drei Punkte** → **Benutzerdefinierte Repositories**.
2. URL dieses Repositories einfügen, Kategorie **Integration** wählen und hinzufügen.
3. Nach **Wohnsinnig vernetzt** suchen und **Herunterladen** klicken.
4. **Home Assistant neu starten**.
5. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **Wohnsinnig vernetzt** suchen.

## Dashboard-Karten
- Podcast-Player: `type: custom:wohnsinnig-vernetzt-card`
- Anwesenheitssimulation: `type: custom:wohnsinnig-vernetzt-presence-card`
- Blueprint-Manager: `type: custom:wohnsinnig-vernetzt-blueprints-card`
- Batterie-Check: `type: custom:wohnsinnig-vernetzt-battery-card`
- Stille Sensoren: `type: custom:wohnsinnig-vernetzt-silent-sensors-card`
