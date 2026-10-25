# Zigbee2MQTT (WebSocket) für Home Assistant

**Deutsch** · [English](README.md)

Diese Integration holt deine Zigbee2MQTT-Geräte über die **WebSocket-Schnittstelle**
von Zigbee2MQTT nach Home Assistant — als Alternative zum üblichen Weg über MQTT.

Kurz gesagt: Zigbee2MQTT verwaltet die Zigbee-Geräte (Lampen, Steckdosen, Sensoren …),
diese Integration ist die Leitung dazwischen und macht daraus Home-Assistant-Entitäten.

---

## Installation

1. **HACS → Integrationen → ⋮ → Benutzerdefinierte Repositories**
2. URL eintragen: `https://github.com/jonnycastaway/ha-zigbee2mqtt-ws`
   Kategorie: **Integration**
3. Integration suchen, installieren, Home Assistant neu starten.
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → „Zigbee2MQTT (WebSocket)"**

### Felder bei der Einrichtung

| Feld | Bedeutung |
|---|---|
| **Host** | IP oder Name des Rechners, auf dem Zigbee2MQTT läuft |
| **Port** | Standard `8080` (die Web-Oberfläche von Zigbee2MQTT) |
| **SSL** | nur anschalten, wenn Zigbee2MQTT hinter HTTPS läuft |
| **Auth-Token** | nur nötig, wenn in der Zigbee2MQTT-Konfiguration ein `frontend: auth_token` gesetzt ist |
| **Base Topic** | Standard `zigbee2mqtt`, nur bei abweichender Konfiguration ändern |

Nach dem Einrichten erscheinen deine Zigbee-Geräte als ganz normale Geräte in
Home Assistant — mit Lampen, Schaltern, Sensoren, Abdeckungen, Schlössern und
Klimageräten, je nachdem was das Gerät kann.

---

## Verbindungsanzeige (ab Version 1.3.6)

Es gibt ein zusätzliches Gerät **„Zigbee2MQTT (WebSocket)"** mit einer Diagnose-Entität:

```
binary_sensor.zigbee2mqtt_websocket_connection
```

* **an** = Die Verbindung steht, es kommen Daten an.
* **aus** = Seit etwa 2,5 Minuten keine Daten mehr.

Zusätzlich erscheint bei einem echten Ausfall eine **Benachrichtigung** in Home Assistant,
die beim Wiederverbinden automatisch verschwindet.

Die Entität eignet sich zum Beispiel für eine eigene Automation („schick mir eine
Nachricht, wenn die Verbindung länger weg ist") — so entscheidest du selbst, was passiert.

> **Wichtig:** Bei einem Verbindungsabbruch werden **keine** anderen Entitäten auf
> „nicht verfügbar" gesetzt. Das ist Absicht: Zigbee2MQTT meldet selbst, wenn einzelne
> Geräte nicht erreichbar sind. Würde die Integration bei jedem kurzen Aussetzer *alle*
> Entitäten sperren, hätte das echte Nebenwirkungen — eine Alarmanlage zum Beispiel
> behandelt „nicht verfügbare" Sensoren als ausgelöst, wenn man das pro Sensor so
> eingestellt hat. Ein kurzer Netzwerk-Hänger würde dann die Sirene starten.

---

## Was passiert bei einem Verbindungsabbruch?

* **Befehle gehen nicht verloren.** Schaltest du in Home Assistant eine Lampe, während die
  Verbindung gerade weg ist, wird der Befehl gespeichert und nach dem Wiederverbinden
  nachgeholt — bis zu **30 Sekunden** lang. Alles, was älter ist, wird verworfen, denn eine
  Lampe eine Minute später einzuschalten wäre mehr Ärger als Nutzen.
* **Die Anzeige bleibt auf dem letzten Stand**, bis wieder Daten ankommen. Der letzte
  bekannte Zustand ist ehrlicher als ein erfundener.
* **Automatisch neu verbinden:** Die Integration versucht es alle 5 Sekunden erneut.

---

## Changelog

### 1.3.6 — Befehle gehen nicht mehr verloren, Verbindungsanzeige

**Behoben / neu:**

* **Befehle wurden stillschweigend verworfen.** Bisher hat die Integration Befehle, die
  während eines Verbindungsabbruchs abgeschickt wurden, nur ins Log geschrieben und dann
  vergessen. In der App sah es so aus, als hätte geklappt — die Lampe blieb aber aus.
  Jetzt werden solche Befehle gespeichert und nach dem Wiederverbinden nachgeholt
  (maximal 30 Sekunden alte Befehle).
* **Neue Verbindungsanzeige + Benachrichtigung.** Man sieht jetzt in Home Assistant, ob die
  Verbindung zu Zigbee2MQTT steht (siehe oben). Vorher merkte man einen Ausfall nur daran,
  dass nichts mehr reagierte.

**Technischer Hintergrund:** Damit ein ruhiger Funkverkehr (nachts passiert oft minutenlang
nichts) nicht mit einem Ausfall verwechselt wird, fragt die Integration bei Stille alle 30
Sekunden kurz bei Zigbee2MQTT nach („bist du noch da?"). Erst wenn auch darauf nichts kommt
und insgesamt 2,5 Minuten keine Daten eintrafen, gilt die Verbindung als getrennt.

### 1.3.5 — Veraltete Zustände behoben

**Behoben:**

* **Lampen zeigten manchmal einen falschen Zustand.** Beispiel: Du stellst eine Lampe auf
  100 % Helligkeit, Zigbee2MQTT meldet auch brav 100 % — Home Assistant zeigte aber
  weiterhin die alten 25 %. Der richtige Wert war intern schon bekannt, wurde aber nicht
  ans Dashboard weitergegeben. Erst ein Neustart oder ein Verbindungsabbruch hat den
  Anzeigefehler repariert.
  Ursache: Die Integration hat die Bestätigung von Zigbee2MQTT als „veraltete Meldung"
  eingestuft und weggeworfen, sobald Home Assistant selbst gerade etwas geschaltet hatte.
  Das passiert jetzt nicht mehr.
* **Schnelle Änderungen wurden verschluckt.** Wenn mehrere Meldungen kurz hintereinander
  kamen (z. B. Helligkeit + Farbe in einem Rutsch), konnte die letzte verloren gehen.
  Jetzt wird sie nachgeholt.
* **Abdeckungen und Schlösser** konnten kurzzeitig einen falschen Zustand anzeigen
  (z. B. „offen" statt „geschlossen"), weil alle Zustände außer „an" als „aus" übersetzt
  wurden. Behoben.
* **Erreichbarkeit** von Geräten („offline"/„online") wird jetzt korrekt ins Dashboard
  übernommen.

### Ältere Versionen

Bis einschließlich **1.3.4** gab es keine Changelogs. Kurzfassung: Aufbau der Integration,
Unterstützung für Lampen, Schalter, Sensoren, Binärsensoren, Abdeckungen, Schlösser und
Klimageräte, Verbesserungen für Home-Assistant-Versionen ab 2025.

---

## Bekannte Eigenheiten

* Die Integration nutzt die WebSocket-Schnittstelle der Zigbee2MQTT-Weboberfläche. Ist die
  Weboberfläche in Zigbee2MQTT deaktiviert, funktioniert sie nicht.
* Wird MQTT-Discovery parallel benutzt, entstehen doppelte Geräte. Dann bitte nur einen der
  beiden Wege verwenden.
* Nach einem Update über HACS die Integration einmal **neu laden**
  (Einstellungen → Geräte & Dienste → Zigbee2MQTT (WebSocket) → ⋮ → Neu laden), damit neue
  Entitäten erscheinen.
