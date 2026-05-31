# Arbeitszeit-Einträge an Wochenenden und Feiertagen

**Datum:** 2026-05-31
**App:** `timetracking`

## Problem

Aktuell können Arbeitszeit-Einträge nur an Werktagen (Mo–Fr, keine Feiertage des hinterlegten Bundeslands) angelegt werden. Im Dashboard und in der Monatsdetailansicht erscheint an Wochenenden und Feiertagen kein "+"-Button. Wer am Samstag oder an einem Feiertag arbeitet, kann diese Zeit nicht erfassen — sie geht im Saldo verloren.

## Ziel

Nutzer können auch an Wochenenden und Feiertagen Arbeitsstunden eintragen. Diese Stunden zählen 1:1 als Plus ins Wochen-, Monats- und Gesamt-Saldo (Soll bleibt 0h an dem Tag — die Stunden sind reine Überstunden).

## Scope

### Erlaubt
- Eintragstyp `work` an Wochenenden und Feiertagen.

### Nicht erlaubt
- Eintragstypen `urlaub`, `krankheit`, `homeoffice` an Wochenenden/Feiertagen — diese ergeben dort fachlich keinen Sinn (Soll = 0h).

### Nicht im Scope
- Zuschläge (z. B. 1,5× für Wochenend-/Feiertagsarbeit).
- Datenmodell-Änderungen / Migrationen.
- Änderungen am Eintragsformular-UI (Typ-Select bleibt unverändert; Validierung greift serverseitig).

## Verhalten im Detail

### Saldo-Logik
- **Soll** an Wochenenden und Feiertagen bleibt 0h (unverändert).
- **Ist** wird aus `WorkEntry.worked_hours` aufaddiert (auch an Wochenenden/Feiertagen).
- **Diff** = Ist − Soll = volle Ist-Stunden als Plus.

Beispiel: 4h gearbeitet am Samstag → Tages-Diff +4h, Wochen-Saldo +4h, Monats-Saldo +4h, Gesamt-Saldo +4h.

### Anzeige
- Wochenenden bleiben in der Tabelle grau (`text-muted`), Feiertage bleiben blau hinterlegt (`table-info`) — visuell weiterhin als Nicht-Werktage erkennbar.
- Mit Eintrag: Ist-Spalte zeigt die Stunden (statt `–`), Diff-Spalte zeigt `+Xh` grün, Bearbeiten/Löschen-Buttons sind verfügbar.
- Ohne Eintrag: "+"-Button ist verfügbar (zusätzlich zu Werktagen).

## Änderungen

### 1. `timetracking/forms.py` — `WorkEntryForm.clean()`
Erweiterung: Wenn `date` auf ein Wochenende oder einen Feiertag (für `request.user.userprofile.bundesland`) fällt und `entry_type != "work"`, wird ein Validierungsfehler auf `entry_type` gesetzt: „An Wochenenden und Feiertagen sind nur Arbeitseinträge möglich."

Das Bundesland muss dazu ins Form übergeben werden — `__init__` bekommt zusätzlich zu `user` Zugriff auf das Profil (über `user.userprofile.bundesland` aus dem `get_or_create_profile`-Aufruf in den Views; einfacher: `bundesland` direkt als Parameter beim Instanziieren übergeben).

### 2. `timetracking/views.py` — `dashboard()`
Aufbereitung pro Tag in `week_data`:
- `no_value` wird `True` nur noch, wenn weder Werktag noch Eintrag vorhanden (`(is_weekend or holiday_name) and not entry`).
- `ist` wird aus dem Eintrag berechnet, auch wenn Wochenende/Feiertag.
- `diff` = `ist - soll` (also = `ist`, da `soll = 0`), wenn Eintrag vorhanden.

Monatsübersicht (`month_ist`): `entries_this_month`-Query filtert bereits nicht auf Werktage, also läuft die Summierung automatisch auch über Wochenend-/Feiertags-Einträge — keine Änderung nötig. ✓

### 3. `timetracking/views.py` — `month_detail()`, `report_view()`, `report_pdf()`, `report_email()`
Schleife über alle Monatstage: `ist` und `diff` müssen auch für Wochenenden/Feiertage gesetzt werden, sobald ein Eintrag existiert. Aktuell ist die Berechnung in diesen Views bereits korrekt (`ist = Decimal(str(entry.worked_hours or 0))` unabhängig von `is_weekend`), also reicht es zu prüfen, ob die Templates die Werte richtig ausgeben.

### 4. `timetracking/utils.py` — `calculate_weekly_saldo()`
Keine Änderung — die Funktion summiert bereits alle `WorkEntry`-Objekte im Zeitraum ohne Wochentag-Filter. Wochenend-/Feiertags-Einträge gehen automatisch ins `week_ist` ein, während `week_soll` (über `get_soll_days_in_range`) Wochenenden/Feiertage ausschließt → korrektes Saldo-Plus. ✓

### 5. Templates

**`templates/timetracking/dashboard.html`**:
- "+"-Button-Bedingung anpassen: aktuell `{% if not d.is_weekend and not d.holiday_name %}` → entfernen, sodass Button immer erscheint wenn kein Eintrag (oder Bearbeiten/Löschen wenn Eintrag).
- Ist-Anzeige: bei Eintrag immer Stunden anzeigen, auch an Wochenende/Feiertag.
- Diff-Anzeige: bei Eintrag immer Diff anzeigen, an Wochenenden/Feiertagen als grünes Plus (Soll = 0).

**`templates/timetracking/month_detail.html`** (analog):
- Bearbeiten/Löschen/+-Buttons auch an Wochenenden/Feiertagen.
- Ist und Diff bei vorhandenem Eintrag anzeigen.

**`templates/timetracking/report.html`**: Prüfen, ob die Werte bereits korrekt erscheinen — falls ja, keine Änderung.

### 6. `timetracking/tests.py`
Neue Tests:
- Anlegen eines `work`-Eintrags am Samstag → erfolgreich.
- Anlegen eines `work`-Eintrags an einem bayerischen Feiertag → erfolgreich.
- Anlegen eines `urlaub`-Eintrags am Samstag → Validierungsfehler.
- Anlegen eines `krankheit`-Eintrags an einem Feiertag → Validierungsfehler.
- Saldo-Berechnung: 4h am Samstag → Wochen-Saldo enthält +4h, Monats-Saldo enthält +4h.

## Risiken & offene Punkte

- **Bundesland-Wechsel:** Wenn ein Nutzer sein Bundesland ändert, kann sich rückwirkend ändern, ob ein bestimmter Tag ein Feiertag ist. Bestehende Einträge bleiben gültig (Validierung greift nur beim Anlegen/Bearbeiten). Das ist akzeptiertes Verhalten, da auch jetzt schon das Soll von Vergangenheits-Wochen sich bei Bundeslandwechsel ändert.
- Keine sichtbaren Nebenwirkungen für bestehende Werktag-Einträge.
