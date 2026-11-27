# Wohnsinnig vernetzt – Home Assistant Integration

Die offizielle Smart-Home-Integration zum Podcast **Wohnsinnig vernetzt** (von Niels und Patrick – [wohnsinnigvernetzt.de](https://www.wohnsinnigvernetzt.de)).

## Features (v2.10.0)
- **Kombinierte Anwesenheitssensoren (Personen & Alarmanlage):** Erstelle beliebig viele eigene `binary_sensor`-Entitäten (z. B. für dich, Frau, Kind) plus den automatischen Sammel-Sensor `Jemand zuhause`. Kombiniert GPS/Person, WLAN (Router-Tracker oder Handy-SSID), Bewegungsmelder-Timeout (keine Bewegung seit X Min) und optionale Extras – perfekt als fehlalarmfreier Auslöser für Alarmanlagen.
- **PV-Überschuss & Solar-Manager:** Führt bei PV-Überschuss (Watt) und/oder PV-Akku-Füllstand (%) beliebig viele konfigurierbare Aktionen aus (Steckdosen für Werkzeug-Akkus, Geschirrspüler, Wallbox, Skripte, Szenen) – inkl. Wolkenfilter, Hysterese, Auto-Aus und 1×-pro-Tag-Modus.
- **Wake-Up Light (Sonnenaufgang 0 % → 100 %):** Wähle eine oder mehrere Lampen, verknüpfe direkt deinen **Handy-Wecker (Next Alarm Sensor)** oder definiere eine feste Zielzeit (100 % um) bzw. Startzeit sowie die Dimm-Dauer (z. B. 30 Min) und optional eine **Auto-Aus-Zeit** nach Erreichen von 100 %. Betroffene Lampen-Automationen werden während des Dimmens automatisch deaktiviert und danach wieder aktiviert.
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
- Anwesenheitssensoren: `type: custom:wohnsinnig-vernetzt-presence-sensors-card`
- PV-Überschuss: `type: custom:wohnsinnig-vernetzt-pv-card`
- Wake-Up Light: `type: custom:wohnsinnig-vernetzt-wakeup-card`
- Anwesenheitssimulation: `type: custom:wohnsinnig-vernetzt-presence-card`
- Blueprint-Manager: `type: custom:wohnsinnig-vernetzt-blueprints-card`
- Batterie-Check: `type: custom:wohnsinnig-vernetzt-battery-card`
- Stille Sensoren: `type: custom:wohnsinnig-vernetzt-silent-sensors-card`

## Aufgeräumte 7-Bereiche-Struktur in Home Assistant
Die Integration legt automatisch 7 übersichtliche Geräte an, damit Steuerung und Sensoren sauber getrennt bleiben:
1. **Wohnsinnig vernetzt – Audio & Podcast** (Player, Episoden, Infografik, Push & Eilmeldungen)
2. **Wohnsinnig vernetzt – Anwesenheitssimulation** (Hauptschalter, Status & direkter Button **Konfiguration öffnen**)
3. **Wohnsinnig vernetzt – Blueprints** (Auswahl, 1-Klick-Import & native Updates)
4. **Wohnsinnig vernetzt – Batterie- & Sensor-Check** (Batterie-Check mit Ausschlussliste + Stille Sensoren gemeinsam)
5. **Wohnsinnig vernetzt – Wake-Up Light** (Hauptschalter, Handy-Wecker, Zeitmodus, Uhrzeit, Dimm-Dauer, Auto-Aus & Direkt-Konfiguration)
6. **Wohnsinnig vernetzt – PV-Überschuss** (Hauptschalter, Live-Überschuss & PV-Akku, unbegrenzte Aktionen mit Wolkenfilter & Direkt-Konfiguration)
7. **Wohnsinnig vernetzt – Anwesenheitssensoren** (Sammel-Sensor „Jemand zuhause“ + beliebig viele Personen-/Alarmanlagen-Sensoren mit Standort, WLAN & Bewegungsmelder-Timeout)
