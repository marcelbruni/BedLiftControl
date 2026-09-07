# Deployment auf dem Raspberry Pi

Schritt-für-Schritt-Anleitung, um BedLiftControl auf einem Raspberry Pi zu
installieren und beim Start automatisch hochfahren zu lassen.

Das Repository ist auf GitHub öffentlich, das Klonen auf dem Pi braucht also
weder Login noch Token.

- [Erstinstallation](#erstinstallation) — der Pi hat das Projekt noch nicht
- [Update](#update) — das Projekt ist schon per git auf dem Pi

---

## Vorbereitung

> ⚠️ **Bett ganz runterfahren, bevor du anfängst.**
> Die Installation startet mit dem gespeicherten Zustand „Bett unten"
> (`bed_up: false` in `data/config.json`). Ist das Bett real oben, die App aber
> auf „unten" gesetzt, fahren die Motoren beim nächsten „Runter" gegen den
> Anschlag.

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

Die GUI muss aufgehen: Buttons vorhanden, Wetter sichtbar, Bett fährt hoch und
runter. Danach Fenster schliessen bzw. `Strg+C` im Terminal.

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

## Update

Wenn das Projekt bereits per git auf dem Pi liegt und am Entwicklungsrechner
Änderungen gepusht wurden:

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
laufenden App fortlaufend überschrieben (Schrittzahl, Geschwindigkeit,
Bettposition). `git pull` bricht deshalb mit *"Your local changes would be
overwritten"* ab. `git checkout -- data/config.json` verwirft die lokalen
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
| Bett fährt in die falsche Richtung gegen den Anschlag | `bed_up` in `data/config.json` passt nicht zur echten Position. Wert von Hand korrigieren, App neu starten. |
