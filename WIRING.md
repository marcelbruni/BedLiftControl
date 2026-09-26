# Wechselrichter anschliessen

Wie das purecrea 1-Kanal-Relaismodul zwischen Raspberry Pi und die
Fernbedienklemme des Victron-Wechselrichters kommt, damit die App die 230V
schalten kann.

Einmalige Arbeit. Danach schaltet der „230V"-Knopf den Wechselrichter, und jede
Bettfahrt schaltet ihn selbst ein und wartet seinen Anlauf ab.

- [Vorbereitung](#vorbereitung)
- [Schritt 1–4: Pi-Seite](#schritt-1-pi-herunterfahren)
- [Schritt 5–6: Test ohne Wechselrichter](#schritt-5-jumper-prüfen-und-modul-testen)
- [Schritt 7–9: Wechselrichter-Seite](#schritt-7-wechselrichter-stromlos-machen)
- [Fehlersuche](#fehlersuche)

---

## Vorbereitung

> ⚠️ **Der Wechselrichter erzeugt 230V.** Alles an seinem Wechselstrom-Ausgang
> ist lebensgefährlich. Die Fernbedienklemme selbst führt praktisch keine
> Spannung, aber gearbeitet wird trotzdem nur, wenn das Gerät **ausgeschaltet**
> ist und nichts am 230V-Ausgang hängt.

Was du brauchst:

| Teil | Wofür |
|------|-------|
| purecrea 1-Kanal Relaismodul | das Ganze |
| 3 Adern, ca. 0,25 mm², mit Dupont-Buchse an einem Ende | Pi → Modul |
| 2 Adern, ca. 0,5 mm² | Modul → Wechselrichter |
| kleiner Schlitz-Schraubendreher | Schraubklemmen |
| Multimeter (optional) | Durchgangsprüfung |
| 10 kΩ Widerstand (optional) | siehe Schritt 4 |

Ausserdem: die Software muss auf dem Pi aktuell sein. Der Wechselrichter-Teil
kam mit einem Update dazu — falls noch nicht geschehen, zuerst das Update aus
[DEPLOYMENT.md](DEPLOYMENT.md#update) fahren.

---

## Schritt 1: Pi herunterfahren

Nie Kabel an die Stiftleiste stecken, während der Pi läuft.

```bash
sudo shutdown -h now
```

Warten, bis die grüne LED aus bleibt, dann das Netzteil ziehen.

## Schritt 2: Die drei Pins finden

Die Stiftleiste hat **40 Pins** in zwei Reihen. Gebraucht werden drei davon,
alle im oberen Drittel. Pin 1 liegt an der Ecke, die der SD-Karte am nächsten
ist, und ist auf der Platine markiert:

```
                             +---------+
       DC+   Relais →     5V | 2     1 | 3V3
    (oder hier DC+) →     5V | 4     3 | GPIO2
       DC−   Relais →    GND | 6     5 | GPIO3
                      GPIO14 | 8     7 | GPIO4
                      GPIO15 |10     9 | GND    ← Motor −DIR
                      GPIO18 |12    11 | GPIO17 ← Relais IN
         Motor −DIR →    GND |14    13 | GPIO27 ← front PUL
           back DIR → GPIO23 |16    15 | GPIO22 ← front DIR
           back PUL → GPIO24 |18    17 | 3V3
         Motor −PUL →    GND |20    19 | GPIO10
                      GPIO25 |22    21 | GPIO9
                       GPIO8 |24    23 | GPIO11
                       GPIO7 |26    25 | GND    ← Motor −PUL
                       ID_SC |28    27 | ID_SD
                         GND |30    29 | GPIO5
                      GPIO12 |32    31 | GPIO6
                         GND |34    33 | GPIO13
                      GPIO16 |36    35 | GPIO19
                      GPIO20 |38    37 | GPIO26
                      GPIO21 |40    39 | GND
                             +---------+
```

So gezeichnet, wie du im Fahrzeug auf die Leiste schaust: die geraden Pins
links, die ungeraden rechts.

Die Motoren belegen **acht** Pins: vier Signale (front PUL/DIR rechts, back
PUL/DIR links) und vier Rückleiter auf GND-Pins (9, 14, 20 und 25). Alles
andere ist frei.

**Zum Abzählen auf einem Breakout-Board**, wo die Beschriftung oft winzig ist:
die Motoradern sind der Anker. In der rechten Reihe sind die Pins 9, 13 und 15
belegt — **GPIO 17 ist der einzige freie Pin mittendrin**, zwischen dem GND mit
dem Rückleiter und der ersten Front-Ader. Ein Pin daneben und du sitzt auf einer
Motorleitung, das merkst du sofort.

DC+ und DC− liegen in der anderen Reihe ganz oben: die **ersten beiden** Pins
sind 5V, der **dritte** ist GND und der einzige GND dieser Reihe, der noch frei
ist. Findest du diese Muster nicht, hast du vom falschen Ende gezählt.

## Schritt 3: Modul mit dem Pi verbinden

Die drei Adern in die Schraubklemmen des Moduls, die Dupont-Buchsen auf die
Stiftleiste:

| Modul | Pi-Pin | Bedeutung |
|-------|--------|-----------|
| DC+ | 2 | 5V |
| DC− | 6 | GND |
| IN | **11** | GPIO 17, das Steuersignal |

## Schritt 4: Optional — Eingang definiert halten

Zwischen dem Einschalten des Pi und dem Start der App vergehen ein paar
Sekunden, in denen GPIO 17 noch gar kein Ausgang ist und der Eingang des Moduls
frei in der Luft hängt. Ein Widerstand von 10 kΩ zwischen **IN und DC−** zieht
ihn in dieser Zeit sicher auf „aus".

Ohne den Widerstand passiert mit grosser Wahrscheinlichkeit auch nichts — bau
ihn ein, wenn du ihn ohnehin da hast.

## Schritt 5: Jumper prüfen und Modul testen

Der Jumper auf dem Modul muss auf **High-Level-Trigger** stehen. Welche Stellung
das ist, steht auf der Platine; sicher weisst du es nach diesem Test.

Pi einschalten, einloggen, und:

```bash
python3 -c "import RPi.GPIO as G; G.setmode(G.BCM); G.setup(17, G.OUT); G.output(17, G.HIGH); input('LED an? Enter zum Beenden')"
```

- **Status-LED leuchtet, Relais klickt** → Jumper stimmt, weiter mit Schritt 6.
- **Nichts passiert** → Enter drücken, Pi herunterfahren, Jumper umstecken, Test
  wiederholen.

Der Test lässt den Pin nach dem Enter wieder los; das Relais fällt ab.

## Schritt 6: Kontakt durchmessen (optional)

Multimeter auf Durchgang, an **COM** und **NO** des Moduls. Mit dem Kommando aus
Schritt 5 muss der Kontakt schliessen, nach dem Beenden wieder öffnen. Damit ist
sicher, dass du die richtigen zwei der drei Schraubklemmen erwischt hast — die
dritte (**NC**) macht genau das Gegenteil und ist hier falsch.

## Schritt 7: Wechselrichter stromlos machen

Wechselrichter mit seinem eigenen Schalter auf **off**, alle 230V-Verbraucher
abstecken. Wer es gründlich mag, trennt zusätzlich die Batterie-Zuleitung.

## Schritt 8: Drahtbrücke aus Klemme H entfernen

Klemme **H** ist die Fernbedienung (Handbuch Abschnitt 4.4.1, Anhang A). Ab Werk
steckt dort eine kleine Drahtbrücke, die den Kontakt dauerhaft schliesst.

**Diese Brücke herausnehmen und aufheben.** Sie ist dein Notfall-Rückweg: steckt
sie wieder in H, läuft der Wechselrichter unabhängig vom Pi. Leg sie irgendwo
ins Fahrzeug, wo du sie im Dunkeln findest.

## Schritt 9: Relais an Klemme H

| Modul | Wechselrichter |
|-------|----------------|
| COM | Klemme H, eine Ader |
| **NO** | Klemme H, andere Ader |

Die Polarität ist egal, es ist ein Schaltkontakt. **NO**, nicht NC: ohne Strom,
ohne Pi und ohne laufendes Programm bleibt der Kontakt offen und der
Wechselrichter aus.

Zum Schluss den Schalter am Wechselrichter wieder auf **on** stellen. Er läuft
damit nicht an — ab jetzt entscheidet das Relais. Der Geräteschalter muss
dauerhaft auf „on" bleiben, sonst ignoriert der Wechselrichter die
Fernbedienung.

---

## Funktionstest

1. App starten, den grauen Knopf **„230V"** in der unteren Leiste antippen.
   Er wird rot, das Relais klickt, der Wechselrichter läuft an.
2. Nochmal antippen: der Knopf wird wieder grau, der Wechselrichter geht aus.
3. Einen Pfeil antippen. Über beiden Pfeilen erscheint ein Countdown
   („230V startet … 10s"), danach fährt das Bett. War der Wechselrichter schon
   an und eingelaufen, geht es ohne Wartezeit los.
   Miss dabei, wie lange dein Gerät wirklich braucht — die Wartezeit stellst du
   unter ⚙ → **230V Anlauf** zwischen 0 und 15 Sekunden ein.
   Beim Herunterfahren von ganz oben kommt noch die Zeit zum Lösen der
   Sicherungsseile dazu (⚙ → **Seile lösen**, 0 bis 20 Sekunden); der Knopf sagt
   dann „Seile lösen!" statt „230V startet".
4. Während der Fahrt ist der 230V-Knopf ausgegraut — mitten in der Fahrt die
   Motoren stromlos zu machen würde die gespeicherte Bettposition verfälschen.
   Dasselbe gilt für das Korrekturfenster (↑↓): es schaltet 230V beim Öffnen
   ein und beim Schliessen wieder aus, die Korrekturtasten fahren ja Motoren.
5. Bis zum Anschlag fahren lassen. Unten geht das 230V von selbst wieder aus,
   oben erst, wenn du das Popup „Sicherungsseile anbringen!" mit OK bestätigt
   hast. Der Knopf wird in beiden Fällen wieder grau.

---

## Fehlersuche

| Symptom | Ursache und Behebung |
|---------|----------------------|
| LED des Moduls bleibt bei HIGH dunkel | Jumper steht auf Low-Level-Trigger, siehe Schritt 5. |
| Relais klickt, Wechselrichter bleibt aus | Schalter am Gerät steht auf „off", oder die Adern sitzen an NC statt NO, oder die Drahtbrücke steckt noch in H (dann ist der Kontakt dauerhaft geschlossen und das Relais wirkungslos). |
| Wechselrichter läuft dauerhaft, der Knopf bewirkt nichts | Drahtbrücke noch in Klemme H, siehe Schritt 8. |
| Wechselrichter geht beim Schliessen der App aus | Kein Fehler. Die App gibt die GPIO-Pins frei, das Relais fällt ab. |
| Nach einem Neustart ist der Wechselrichter aus | Kein Fehler, so gewollt. Der Zustand wird bewusst nicht gespeichert; unbeaufsichtigt 230V einzuschalten wäre die schlechtere Voreinstellung. |
| Bett fährt trotz Countdown nicht los | Countdown abgelaufen? Im Log steht `Inverter switched on, ready in 10s`. Fehlt die Zeile, kam der Aufruf nicht an — dann ist das Modul nicht an GPIO 17. |
| Der Anlauf dauert länger oder kürzer als 10 Sekunden | ⚙ → **230V Anlauf**, Schieberegler zwischen 0 und 15 Sekunden. |
| Wechselrichter startet sporadisch nicht mehr, Relais klickt aber | Nach Jahren möglich: der Kontakt schaltet fast stromlos und kann eine dünne Oxidschicht ansetzen. Modul tauschen, oder eines mit vergoldeten Kontakten nehmen. |
