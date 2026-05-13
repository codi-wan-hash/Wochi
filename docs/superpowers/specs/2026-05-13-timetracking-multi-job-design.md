# Timetracking Multi-Job + Monatsbericht — Design Spec

**Datum:** 2026-05-13
**Status:** Genehmigt
**Vorgänger:** `2026-05-13-arbeitszeiterfassung-design.md`

## Überblick

Erweiterung der bestehenden Arbeitszeiterfassung um:
1. **Mehrere benannte Jobs** — User kann beliebig viele Jobs anlegen, zwischen ihnen wechseln
2. **Wöchentliches Sollstunden-Modell** — ersetzt das bisherige Tagessoll; gilt für alle Jobs
3. **Monatlicher Arbeitszeitnachweis** — als druckbare HTML-Seite, PDF-Download und E-Mail an eigene Adresse

Bundesland bleibt global in `UserProfile`. Alle Job-spezifischen Settings (Name, Wochensoll, Startdatum) liegen im neuen `Job`-Model.

---

## Datenmodell

### Neues Model: `Job`

```python
class Job(models.Model):
    user = models.ForeignKey(AUTH_USER_MODEL, on_delete=CASCADE, related_name="jobs")
    name = models.CharField(max_length=100)           # z.B. "Hauptjob", "Nebenjob"
    weekly_target_hours = models.DecimalField(max_digits=5, decimal_places=2)
    work_start_date = models.DateField()

    class Meta:
        unique_together = ("user", "name")
        ordering = ["name"]
```

### `UserProfile` — Änderungen

**Entfernt:**
- `daily_target_hours`
- `work_start_date`

**Neu:**
- `active_job = ForeignKey(Job, null=True, blank=True, on_delete=SET_NULL)`

### `WorkEntry` — Änderung

**Neu:**
- `job = ForeignKey(Job, on_delete=CASCADE, related_name="entries")`

Das `user`-Feld bleibt zur Query-Effizienz erhalten.

### Migration bestehender Daten

Datenmigration (RunPython) in einer neuen Migration:

1. Für jeden User mit `timetracking_enabled=True`:
   - Job "Hauptjob" anlegen mit `weekly_target_hours = daily_target_hours × 5`, `work_start_date` aus `UserProfile`
   - Alle `WorkEntry`-Einträge dieses Users diesem Job zuweisen
   - `UserProfile.active_job` auf diesen Job setzen
2. Felder `daily_target_hours` und `work_start_date` aus `UserProfile` entfernen

---

## Wochensaldo-Berechnung

### Logik

Statt Tages-Soll wird das Saldo pro **Kalenderwoche** (Mo–So) berechnet:

- **Wochensoll** = `weekly_target_hours`, reduziert um Feiertage in dieser Woche
  - Reduktion pro Feiertag: `weekly_target_hours ÷ 5`
- **Wochen-Ist** = Summe aller Arbeitsstunden der Woche für diesen Job
  - Abwesenheitstypen (Urlaub, Krankheit, Homeoffice) zählen als `weekly_target_hours ÷ 5`
- **Saldo einer Woche** = Wochen-Ist − (bereinigtes) Wochensoll
- **Gesamtsaldo** = Summe aller abgeschlossenen Wochen + aktuelle Woche (nur wenn Einträge vorhanden)

### Abgeschlossene vs. laufende Woche

- Vergangene Wochen (vor der aktuellen ISO-Woche): immer Soll einrechnen (Deficit wenn keine Einträge)
- Aktuelle Woche: Soll nur einrechnen wenn mindestens ein Eintrag existiert (kein automatisches Minus)

### Funktion `calculate_weekly_saldo(job, as_of=None)`

Gibt eine Liste von Wochen-Dicts zurück:
```python
{
    "week_start": date,
    "week_end": date,
    "iso_week": int,
    "year": int,
    "soll": Decimal,
    "ist": Decimal,
    "saldo": Decimal,
    "is_current": bool,
}
```

Und `calculate_total_saldo(job, as_of=None)` → Summe aller Wochen-Saldi.

---

## URL-Struktur

Namespace: `timetracking` (unverändert)

| URL | View | Zweck |
|---|---|---|
| `/timetracking/` | `dashboard` | Hauptseite (aktiver Job) |
| `/timetracking/jobs/` | `job_list` | Job-Verwaltung |
| `/timetracking/jobs/neu/` | `job_create` | Neuen Job anlegen |
| `/timetracking/jobs/<id>/bearbeiten/` | `job_edit` | Job bearbeiten |
| `/timetracking/jobs/<id>/loeschen/` | `job_delete` | Job löschen (nur wenn keine Einträge) |
| `/timetracking/jobs/<id>/aktivieren/` | `job_activate` | Aktiven Job setzen (POST) |
| `/timetracking/eintrag/neu/` | `entry_create` | Eintrag anlegen (Job vorausgefüllt) |
| `/timetracking/eintrag/<id>/bearbeiten/` | `entry_edit` | Eintrag bearbeiten |
| `/timetracking/eintrag/<id>/loeschen/` | `entry_delete` | Eintrag löschen |
| `/timetracking/einstellungen/` | `settings_view` | Bundesland + Feature-Toggle |
| `/timetracking/monat/<year>/<month>/` | `month_detail` | Monatsdetail (aktiver Job) |
| `/timetracking/bericht/<year>/<month>/` | `report_view` | Arbeitszeitnachweis HTML |
| `/timetracking/bericht/<year>/<month>/pdf/` | `report_pdf` | PDF-Download |
| `/timetracking/bericht/<year>/<month>/email/` | `report_email` | E-Mail an eigene Adresse |

---

## Views & Logik

### Dashboard

- Job-Switcher oben: Aktiver Job als Badge, Dropdown-Links zu `job_activate`
- Wochenübersicht: Tage Mo–So mit Einträgen; Saldo-Zeile am Ende der Woche (Ist vs. Wochensoll)
- Monatsblock: wie bisher, aber Soll = Wochensoll × Wochen im Monat (anteilig)
- Gesamtsaldo: `calculate_total_saldo(active_job)`
- Button "Monatsbericht [Monat Jahr]" → `report_view`

### Job-Aktivierung

`job_activate` ist ein POST-only View:
```python
profile.active_job = job
profile.save()
return redirect("timetracking:dashboard")
```

### `entry_create` / `entry_edit`

- `job`-Feld im Formular: Dropdown aller Jobs des Users, vorausgewählt mit `active_job`
- User kann Job pro Eintrag abweichend setzen

### Monatsbericht (`report_view`)

Für den aktiven Job, den gewählten Monat:

**Kopfzeile:**
```
Arbeitszeitnachweis
[Job-Name] | [Bundesland] | [Monat Jahr]
Wochensoll: XX.Xh | Mitarbeiter: [username]
```

**Wochenübersicht (Tabelle):**
```
KW | Zeitraum     | Soll   | Ist    | Saldo
18 | 27.04–01.05  | 32.0h  | 38.5h  | +6.5h
19 | 04.05–08.05  | 40.0h  | 41.0h  | +1.0h
...
   | Gesamt       | 160.0h | 162.0h | +2.0h
```

**Tagesdetails (Tabelle):**
```
Datum         | Typ       | Beginn | Ende  | Pause  | Stunden
Mo 04.05.2026 | Arbeit    | 08:00  | 17:00 | 30min  | 8.50h
Di 05.05.2026 | Urlaub    |        |       |        | 8.00h
Mi 06.05.2026 | Feiertag  |        |       |        | –
```

### PDF-Generierung (`report_pdf`)

```python
from weasyprint import HTML

html = render_to_string("timetracking/report.html", context)
pdf = HTML(string=html, base_url=request.build_absolute_uri()).write_pdf()
return HttpResponse(pdf, content_type="application/pdf",
    headers={"Content-Disposition": f'attachment; filename="bericht-{year}-{month:02d}.pdf"'})
```

### E-Mail-Versand (`report_email`)

```python
from django.core.mail import EmailMessage

pdf = ...  # wie oben
email = EmailMessage(
    subject=f"Arbeitszeitnachweis {job.name} {monat_name}",
    body=f"Anbei Ihr Arbeitszeitnachweis für {monat_name}.",
    to=[request.user.email],
)
email.attach(f"bericht-{year}-{month:02d}.pdf", pdf, "application/pdf")
email.send()
messages.success(request, f"Bericht wurde an {request.user.email} gesendet.")
return redirect("timetracking:report_view", year=year, month=month)
```

Wenn `request.user.email` leer ist → Fehlermeldung mit Hinweis, E-Mail in Profil zu hinterlegen.

---

## Frontend

### Templates

- `timetracking/job_list.html` — Job-Verwaltung
- `timetracking/job_form.html` — Job anlegen/bearbeiten
- `timetracking/job_confirm_delete.html` — Löschen bestätigen
- `timetracking/report.html` — Bericht (HTML + druckoptimiert)
- `timetracking/dashboard.html` — Job-Switcher ergänzen
- `timetracking/entry_form.html` — Job-Dropdown ergänzen

### Dashboard Job-Switcher

```html
<div class="d-flex align-items-center gap-2 mb-3">
    <span class="fw-bold">{{ active_job.name }}</span>
    <div class="dropdown">
        <button class="btn btn-sm btn-outline-secondary dropdown-toggle">Wechseln</button>
        <ul class="dropdown-menu">
            {% for job in all_jobs %}
            <li>
                <form method="post" action="{% url 'timetracking:job_activate' job.pk %}">
                    {% csrf_token %}
                    <button class="dropdown-item {% if job == active_job %}active{% endif %}">
                        {{ job.name }}
                    </button>
                </form>
            </li>
            {% endfor %}
            <li><hr class="dropdown-divider"></li>
            <li><a class="dropdown-item" href="{% url 'timetracking:job_list' %}">Jobs verwalten</a></li>
        </ul>
    </div>
</div>
```

### Druckoptimierung (`report.html`)

```css
@media print {
    .no-print { display: none !important; }
    body { font-size: 11pt; }
}
```

---

## Abhängigkeiten

```
weasyprint
```

WeasyPrint benötigt auf dem Server system-level dependencies (`libpango`, `libcairo`). Für Render/Hetzner: im `build.sh` via `apt-get install` oder alternative Dockerfile-Anpassung.

---

## Tests

- `Job`-Model: unique_together, str-Repräsentation
- Migration: bestehende Einträge korrekt migriert
- `calculate_weekly_saldo`: Feiertag-Reduktion, aktuelle Woche kein Deficit
- `calculate_total_saldo` mit mehreren Wochen
- `job_activate`: setzt `active_job` korrekt
- `job_delete`: blockiert wenn Einträge vorhanden
- `report_view`: lädt, enthält Wochentabelle und Tagdetails
- `report_pdf`: gibt PDF zurück (Content-Type prüfen)
- `report_email`: sendet E-Mail, Redirect danach
- Feature-Guard: alle Views ohne `active_job` → Settings

---

## Nicht im Scope

- Mehrere Empfänger-Adressen pro Bericht
- Automatischer monatlicher E-Mail-Versand (Cronjob)
- Urlaubskonto-Management
- Überstunden-Regelungen (Zuschläge)
- Export als Excel/CSV
