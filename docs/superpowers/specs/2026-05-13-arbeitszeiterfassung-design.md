# Arbeitszeiterfassung — Design Spec

**Datum:** 2026-05-13
**Status:** Genehmigt

## Überblick

Optionales, user-spezifisches Bonus-Feature für Wochi. Ermöglicht die manuelle Erfassung von Arbeitszeiten (Start/Endzeit pro Tag), berechnet automatisch Plus-/Minusstunden unter Berücksichtigung von Feiertagen (nach Bundesland), Wochenenden und Abwesenheitstypen. Ein Dashboard zeigt Wochen- und Monatsübersicht sowie einen laufenden Gesamtsaldo.

Das Feature ist per User-Setting aktivierbar — inaktive User sehen keinen Sidebar-Eintrag und keinen Zugang.

## Architektur

### Neue Django-App: `timetracking`

Folgt dem bestehenden Muster der anderen Apps (`tasks`, `meals`, `shopping`). Kein Household-Bezug — rein user-spezifisch.

### Neue Abhängigkeit

```
holidays==0.62
```

Unterstützt alle 16 deutschen Bundesländer. Wird für die Feiertags-Erkennung im Dashboard und bei der Soll-Stunden-Berechnung verwendet.

## Datenmodell

### `UserProfile` (OneToOneField → User)

| Feld | Typ | Beschreibung |
|---|---|---|
| `timetracking_enabled` | BooleanField | Feature-Toggle, default=False |
| `bundesland` | CharField (choices) | 16 Bundesländer, z.B. `"BY"`, `"BW"` |
| `daily_target_hours` | DecimalField | Tagessoll in Stunden, z.B. `8.0` |
| `work_start_date` | DateField | Ab diesem Datum läuft der Gesamtsaldo |

Wird per `post_save`-Signal beim User-Erstellen automatisch angelegt.

**Bundesland-Choices:** Alle 16 Bundesländer als `(code, name)`-Tupel, z.B. `("BY", "Bayern")`, `("BW", "Baden-Württemberg")` etc.

### `WorkEntry` (ForeignKey → User)

| Feld | Typ | Beschreibung |
|---|---|---|
| `date` | DateField | Arbeitstag |
| `entry_type` | CharField (choices) | `work`, `urlaub`, `krankheit`, `homeoffice` |
| `start_time` | TimeField (nullable) | Pflicht bei `entry_type=work` |
| `end_time` | TimeField (nullable) | Pflicht bei `entry_type=work` |
| `break_minutes` | IntegerField | Pausenzeit in Minuten, default=0 |

**Property `worked_hours`:** `(end_time - start_time) - break_minutes` in Stunden. Bei Abwesenheitstypen (urlaub, krankheit, homeoffice) gilt das Tagessoll als erfüllt.

**Constraint:** `unique_together = ("user", "date")` — ein Eintrag pro Tag.

## URL-Struktur

Namespace: `timetracking`

| URL | View | Zweck |
|---|---|---|
| `/timetracking/` | `dashboard` | Haupt-Dashboard |
| `/timetracking/eintrag/neu/` | `entry_create` | Neuen Eintrag anlegen |
| `/timetracking/eintrag/<id>/bearbeiten/` | `entry_edit` | Eintrag bearbeiten |
| `/timetracking/eintrag/<id>/loeschen/` | `entry_delete` | Eintrag löschen |
| `/timetracking/einstellungen/` | `settings_view` | UserProfile-Einstellungen |
| `/timetracking/monat/<year>/<month>/` | `month_detail` | Detailansicht eines Monats |

## Views & Logik

### Feature-Guard

Jede View (außer `settings_view`) prüft:
```python
if not request.user.userprofile.timetracking_enabled:
    return redirect("timetracking:settings_view")
```

### Dashboard-View

Berechnet zwei Blöcke:

**Wochenblock (aktuelle Woche Mo–So):**
- Pro Tag: Datum, Wochentag, Eintrag (falls vorhanden), Ist-Stunden, Soll-Stunden, Differenz
- Wochenenden: Soll=0, kein Eintrag erwartet
- Feiertage: automatisch via `holidays`-Paket erkannt, Name als Badge, Soll=0

**Monatsblock (aktueller Monat):**
- Anzahl Soll-Arbeitstage (Werktage ohne Feiertage)
- Summe Soll-Stunden (Soll-Arbeitstage × `daily_target_hours`)
- Summe Ist-Stunden (aus WorkEntry-Einträgen des Monats)
- Monatssaldo (Ist − Soll)
- Navigation zu Vormonat / Nächstmonat

**Gesamtsaldo:**
- Akkumuliert seit `work_start_date`
- Alle vergangenen Soll-Arbeitstage × Tagessoll − Summe aller Ist-Stunden
- Wird groß oben im Dashboard angezeigt, grün bei Plus, rot bei Minus

### Abwesenheitstypen

- `urlaub`, `krankheit`, `homeoffice`: Zählen als Soll erfüllt (Ist = Tagessoll)
- `work`: Ist = `worked_hours` aus Start/End/Pause

### Settings-View

Erstellt oder aktualisiert `UserProfile` per `get_or_create`. Enthält:
- Bundesland-Dropdown
- Tagessoll-Eingabe
- Startdatum
- Feature-Toggle-Checkbox

## Frontend

### Templates

Alle erben von `base.html`, Bootstrap 5.3, Django-Formulare mit Bootstrap-Klassen.

- `timetracking/dashboard.html`
- `timetracking/entry_form.html`
- `timetracking/settings.html`
- `timetracking/month_detail.html`

### Dashboard-Layout

```
┌─────────────────────────────────────┐
│  Gesamtsaldo: +12h 30min            │  ← grün/rot je nach Vorzeichen
├──────────────┬──────────────────────┤
│  Diese Woche │  Dieser Monat        │
│  Mo 7,5h ✓  │  Arbeitstage: 21     │
│  Di 8,0h ✓  │  Soll:    168h       │
│  Mi – Feiert.│  Ist:     154h 30m   │
│  Do 6,0h ↓  │  Saldo:   -13h 30m   │
│  Fr –       │                      │
│  Sa –       │  [← April] [Juni →]  │
│  So –       │                      │
├──────────────┴──────────────────────┤
│  [+ Eintrag hinzufügen]             │
└─────────────────────────────────────┘
```

### Eintrag-Formular

Felder: Datum, Typ (Dropdown), Start- und Endzeit (nur sichtbar wenn Typ=`work`), Pausenminuten.

### Sidebar

Link "Arbeitszeit" erscheint im `base.html` nur wenn `user.userprofile.timetracking_enabled = True`. Für User ohne aktiviertes Feature ändert sich die Sidebar nicht.

Die Template-Prüfung muss mit `get_or_create` oder `hasattr` abgesichert sein, da `UserProfile` für ältere User möglicherweise noch nicht existiert.

## Tests

Datei: `timetracking/tests.py`

- `UserProfile` wird per Signal beim User-Erstellen automatisch angelegt
- Feature-Guard: deaktiviertes Timetracking leitet auf Settings weiter
- `worked_hours`-Berechnung: Start/End/Pause → korrekte Stundenzahl
- Feiertag wird korrekt erkannt (z.B. 01.05. in Bayern)
- Wochenenden haben Soll=0
- Abwesenheitstypen zählen als Soll erfüllt
- Gesamtsaldo akkumuliert korrekt über Monatsgrenzen
- Monatssaldo: Summe Ist vs. Summe Soll
- `unique_together`-Constraint: kein doppelter Eintrag pro Tag

## Nicht im Scope

- Automatisches Zeit-Tracking (kein Timer/Stempeluhr)
- Export (PDF/CSV)
- Mehrere Benutzer vergleichen
- Overtime-Regelungen (Zuschläge etc.)
- Urlaubskontigent-Verwaltung
