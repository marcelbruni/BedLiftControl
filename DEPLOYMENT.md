# Deployment auf dem Raspberry Pi

Schritt-für-Schritt-Anleitung, um BedLiftControl auf einem Raspberry Pi zu
installieren und beim Start automatisch hochfahren zu lassen.

Das Repository ist auf GitHub öffentlich, das Klonen auf dem Pi braucht also
weder Login noch Token.

- [Erstinstallation](#erstinstallation) — der Pi hat das Projekt noch nicht
- [Update](#update) — das Projekt ist schon per git auf dem Pi

---

## Vorbereitung

> ⚠️ **Bett ganz hochfahren, bevor du anfängst.**
> Die Installation startet mit dem gespeicherten Zustand „Bett oben":
> in der eingecheckten `data/config.json` steht `position_steps` auf `28000`,
> also gleich `total_steps` — Bett ganz oben.

Die App merkt sich die Bettposition **in Schritten**, nicht nur als oben/unten:

| Schlüssel | Bedeutung |
|-----------|-----------|
| `total_steps` | Schritte für den vollen Weg |
| `speed_pps` | Motorgeschwindigkeit in Pulsen pro Sekunde |
| `position_steps` | Aktuelle Position: `0` = ganz unten, `total_steps` = ganz oben |
| `bed_up` | Wird aus `position_steps` abgeleitet, nicht von Hand gepflegt |
| `kiosk` | Vollbildmodus (siehe Schritt 13) |
| `weather_location` | Ausgewählter Wetter-Ort, Standard `phone` (Handystandort) |

Ausserdem: **Internet am Pi** (z. B. Handy-Tethering). Nötig für das Klonen und
das Installieren der Pakete — danach läuft die App offline.

Alles Folgende passiert **im Terminal auf dem Pi**, per SSH oder direkt mit
Tastatur am Gerät.

---

## Erstinstallation

### 1. Alte Installation finden

Falls schon einmal eine Version ohne git auf den Pi kopiert wurde, muss sie
gefunden werden, damit später nicht zwei Apps gleichzeitig laufen:

```bash
find ~ -name "main.py" -path "*bedlift*" 2>/dev/null
ls ~/.config/autostart/
```

Die Ausgaben notieren — besonders die Dateinamen der Autostart-Einträge.
**Noch nichts löschen**, die alte Version bleibt vorerst als Sicherheitsnetz.

### 2. git und venv prüfen

```bash
git --version
python3 -m venv --help > /dev/null && echo "venv ok"
```

Erwartet: eine Versionsnummer und `venv ok`. Falls nicht:

```bash
sudo apt update
sudo apt install git python3-venv python3-tk
```

### 3. Projekt klonen

```bash
cd ~
git clone https://github.com/marcelbruni/BedLiftControl.git
cd ~/BedLiftControl
ls
```

`ls` muss `src`, `data`, `deploy` und `README.md` zeigen. Ab hier bleibst du in
diesem Ordner.

### 4. Virtuelle Umgebung anlegen

Ein abgeschottetes Python nur für dieses Projekt, damit die Pakete das
System-Python nicht beeinflussen:

```bash
python3 -m venv .venv
```

### 5. Umgebung aktivieren

```bash
source .venv/bin/activate
```

Kontrolle: Vor dem Prompt steht jetzt `(.venv)`.

> 🔑 **Wichtigster Punkt der Anleitung.** Das `(.venv)` muss in den Schritten 6
> bis 9 sichtbar bleiben. Nach einem Neustart oder einem neuen Terminal ist es
> weg — dann erst wieder `cd ~/BedLiftControl` und `source .venv/bin/activate`.

### 6. Pakete installieren

```bash
pip install -r requirements.txt
pip install -e .
```

Der erste Befehl holt `customtkinter` (GUI) und `RPi.GPIO` (Motorsteuerung),
der zweite macht die Befehle `bedliftcontrol` und `bedliftcontrol-autostart`
verfügbar.

Falls **RPi.GPIO** einen Fehler wirft (kommt auf neueren Pi-Systemen vor):

```bash
deactivate
sudo apt install python3-rpi-lgpio
rm -rf .venv
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install customtkinter
pip install -e .
```

Falls ein Fehler zu Tk kommt (`ModuleNotFoundError: No module named '_tkinter'`):

```bash
sudo apt install python3-tk
```

### 7. Testlauf

```bash
python -m bedliftcontrol.main
```

Die GUI muss aufgehen. Was hier funktionieren muss:

- Pfeiltasten rechts, Wetter mit Wochenvorschau, Uhr rechts unten in der Leiste
- eine Fahrt starten: der Bestätigungsdialog kommt, danach überdeckt ein roter
  **STOP**-Button beide Pfeile
- STOP drücken: die Fahrt endet, beide Pfeile sind danach aktiv, der `↑↓`-Button
  in der Leiste ist ausgegraut (Korrekturen gehen nur an den Endlagen)
- weiterfahren bis zum Anschlag: der `↑↓`-Button wird wieder aktiv

Danach Fenster schliessen bzw. `Strg+C` im Terminal.

> 🛑 **Erst weitermachen, wenn das läuft.** Einen Autostart für etwas
> einzurichten, das nicht startet, bringt nichts.

### 8. Autostart einrichten

```bash
bedliftcontrol-autostart
```

Erwartete Ausgabe:

```
Autostart entry installed at /home/pi/.config/autostart/bedliftcontrol.desktop
BedLiftControl will start on the next desktop login.
```

Der Befehl **erstellt und platziert die `.desktop`-Datei selbst**. Es muss
nichts von Hand kopiert werden — `deploy/bedliftcontrol.desktop` ist nur eine
Vorlage zum Nachschlagen.

### 9. Autostart kontrollieren

```bash
cat ~/.config/autostart/bedliftcontrol.desktop
```

Die `Exec=`-Zeile muss auf das venv zeigen:

```
Exec=/home/pi/BedLiftControl/.venv/bin/python -m bedliftcontrol.main
```

❌ Steht dort nur `python3` ohne den langen Pfad, war `(.venv)` nicht aktiv.
Dann `source .venv/bin/activate` und `bedliftcontrol-autostart` wiederholen.

### 10. Alten Autostart abschalten

Die Einträge aus Schritt 1 nochmal ansehen:

```bash
ls ~/.config/autostart/
```

Alles, was zur alten Bett-App gehört und **nicht** `bedliftcontrol.desktop`
heisst, entfernen — sonst starten zwei Apps gleichzeitig und streiten sich um
die GPIO-Pins:

```bash
rm ~/.config/autostart/DER_ALTE_NAME.desktop
```

### 11. Neustart

```bash
sudo reboot
```

Nach dem Hochfahren startet die App von selbst. Wenn sie ein paar Tage stabil
läuft, kann der alte Projektordner gelöscht werden.

---

### 12. Uhrzeit: Systemuhr setzen lassen (optional)

Der Raspberry Pi hat keine batteriegepufferte Echtzeituhr. Ohne Netz startet er
mit der Zeit, die er zuletzt gesehen hat.

**Die App zeigt trotzdem immer die richtige Zeit.** Sie holt sich stündlich einen
Zeitstempel aus dem Internet, merkt sich die Abweichung zur Maschinenuhr und
rechnet sie auf die Anzeige. Ohne Netz läuft sie mit der zuletzt gemessenen
Abweichung weiter. Dafür ist nichts einzurichten.

Damit auch der **Rest des Systems** (Logs, Dateidaten, cron) die richtige Zeit
bekommt, darf die App die Systemuhr stellen. Das braucht einmalig ein sudo-Recht:

```bash
sudo visudo -f /etc/sudoers.d/bedliftcontrol
```

Diese Zeile eintragen (`pi` durch den eigenen Benutzernamen ersetzen):

```
pi ALL=(root) NOPASSWD: /usr/bin/date
```

Prüfen, dass es greift — der Befehl darf nicht nach einem Passwort fragen:

```bash
sudo -n date -u -s "$(date -u +'%Y-%m-%d %H:%M:%S')"
```

Ohne diesen Eintrag passiert nichts Schlimmes: der Versuch scheitert leise, es
landet eine Warnung im Log, und die Anzeige in der App bleibt korrekt.

> **Der übliche Weg ist NTP.** Wenn der Pi Netz hat, stellt `systemd-timesyncd`
> die Uhr von selbst und genauer als diese Korrektur. Prüfen mit
> `timedatectl status` (`NTP service: active`, `System clock synchronized: yes`).
> Ist NTP aktiv und synchron, weist es das Setzen per `date` unter Umständen ab —
> das ist in Ordnung, dann macht es NTP ohnehin schon richtig. Die Korrektur in
> der App ist das Netz darunter für alles, was vor dem ersten NTP-Sync passiert
> oder wenn der Pi tagelang offline im Auto steht.

---

### 13. Kiosk-Modus einschalten (optional)

Im Kiosk-Modus nimmt die App den ganzen Bildschirm ein (800 × 480 auf dem
7"-Touchdisplay) statt eines Fensters mit Titelleiste. Auf dem Pi ist das der
sinnvolle Betriebsmodus.

Einschalten in der App: **⚙ → „Kiosk-Modus einschalten"**.

Die Einstellung landet als `kiosk: true` in `data/config.json`, der Pi startet
danach also direkt im Vollbild.

> **Der Rückweg:** im Vollbild gibt es keine Titelleiste und kein X. Zurück
> geht es über **⚙ → „Kiosk-Modus ausschalten"** — das Einstellungsfenster
> wird im Kiosk-Modus bewusst vor die Vollbild-App gelegt, damit es auf dem
> Touchdisplay erreichbar bleibt. Mit angeschlossener Tastatur geht auch `Esc`.

---

## Update

Wenn das Projekt bereits per git auf dem Pi liegt und am Entwicklungsrechner
Änderungen gepusht wurden:

> ⚠️ Auch hier gilt: **Bett vorher ganz hochfahren.** Die Zeile
> `git checkout -- data/config.json` setzt `position_steps` auf den
> eingecheckten Wert `28000` zurück, also „Bett oben". Steht das Bett dann
> woanders, fährt die App in die falsche Richtung gegen den Anschlag.
>
> Mit zurückgesetzt werden auch `kiosk`, `total_steps` und `speed_pps`. Wenn du
> den Kiosk-Modus oder eigene Schrittzahlen behalten willst, nimm die Variante
> mit `cp` weiter unten.

```bash
cd ~/BedLiftControl
pkill -f bedliftcontrol.main
git checkout -- data/config.json
git pull
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python -m bedliftcontrol.main
```

Läuft der Testlauf sauber, das Fenster schliessen und den Pi neu starten
(`sudo reboot`) — der Autostart-Eintrag bleibt bestehen und muss nur dann neu
gesetzt werden, wenn sich der Pfad zum venv geändert hat.

### Warum die Zeile mit `git checkout`?

`data/config.json` ist im Repository eingecheckt, wird auf dem Pi aber von der
laufenden App fortlaufend überschrieben — `position_steps` nach jeder Fahrt und
nach jedem Stopp, dazu Schrittzahl, Geschwindigkeit und der Kiosk-Modus.
`git pull` bricht deshalb mit *"Your local changes would be overwritten"* ab. `git checkout -- data/config.json` verwirft die lokalen
Änderungen und macht den Weg frei.

Sollen die Werte vom Pi erhalten bleiben:

```bash
cp data/config.json /tmp/config.bak
git checkout -- data/config.json
git pull
cp /tmp/config.bak data/config.json
```

---

## Fehlersuche

| Symptom | Ursache und Behebung |
|---------|----------------------|
| `ModuleNotFoundError: No module named 'customtkinter'` | `(.venv)` war nicht aktiv. `source .venv/bin/activate`, dann `pip install -r requirements.txt`. |
| `ModuleNotFoundError: No module named '_tkinter'` | `sudo apt install python3-tk` |
| App startet nach dem Reboot nicht | `Exec=`-Zeile prüfen (Schritt 9). Zeigt sie nicht auf das venv, Schritt 8 mit aktivem `(.venv)` wiederholen. |
| App startet doppelt / GPIO-Fehler | Alter Autostart-Eintrag noch vorhanden, siehe Schritt 10. |
| `git pull` bricht mit „local changes would be overwritten" ab | `git checkout -- data/config.json`, dann erneut `git pull`. |
| Bett fährt in die falsche Richtung gegen den Anschlag | `position_steps` in `data/config.json` passt nicht zur echten Position. Auf `0` setzen wenn das Bett unten ist, auf den Wert von `total_steps` wenn es oben ist, App neu starten. `bed_up` von Hand zu ändern bewirkt **nichts** — der Wert wird aus `position_steps` abgeleitet. |
| `↑↓`-Button ist ausgegraut | Kein Fehler. Korrekturen gehen nur, wenn das Bett ganz oben oder ganz unten steht und nichts fährt. Nach einem Stopp auf halber Höhe erst bis zum Anschlag weiterfahren. |
| Beide Pfeile aktiv, Prozentanzeige zeigt einen Zwischenwert | Kein Fehler. Das Bett steht dort, wo zuletzt STOP gedrückt wurde. Ein Pfeil fährt den Restweg, der andere zurück zum Ausgangspunkt. |
| Ein Korrekturmotor läuft beim Gedrückthalten nicht | Er stoppt nach `CORRECTION_HOLD_MAX_STEPS` (8000 Schritte, rund 10 s) als Sicherung. Taste loslassen und neu drücken. |
| Uhr zeigt eine falsche Zeit | Log prüfen: `Time synced, machine clock is off by …` zeigt die gemessene Abweichung. Fehlt die Zeile, war kein Internet da — dann läuft die Uhr mit der Maschinenzeit weiter, siehe Schritt 12. |
