# Arbeitszeit-Einträge an Wochenenden und Feiertagen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nutzer können Arbeitsstunden auch an Wochenenden und Feiertagen eintragen; diese zählen 1:1 als Plus ins Saldo.

**Architecture:** Serverseitige Formularvalidierung lehnt nicht-Arbeits-Einträge an Wochenenden/Feiertagen ab. Bestehende Saldo-Berechnung in `utils.calculate_weekly_saldo` rechnet bereits korrekt (Wochenend-Ist wird summiert, Soll bleibt 0). Dashboard, Monatsdetail und Bericht-Templates erlauben die "+"-/Bearbeiten-Aktion an allen Tagen und zeigen Ist/Diff bei vorhandenem Eintrag.

**Tech Stack:** Django 6, Bootstrap 5.3, `holidays`-Package (bereits in `utils.py` integriert).

**Spec:** `docs/superpowers/specs/2026-05-31-arbeitszeit-wochenende-feiertag-design.md`

---

## File Structure

- **Modify:** `timetracking/forms.py` — `WorkEntryForm.__init__` und `clean()` erweitern
- **Modify:** `timetracking/views.py` — `entry_create` und `entry_edit` übergeben `bundesland` ans Formular; `dashboard()` setzt `show_values`-Flag pro Tag
- **Modify:** `templates/timetracking/dashboard.html` — Button-/Spalten-Bedingungen anpassen
- **Modify:** `templates/timetracking/month_detail.html` — Button-/Spalten-Bedingungen anpassen
- **Modify:** `templates/timetracking/report.html` — Wochenend-Einträge mit aufnehmen
- **Modify:** `timetracking/tests.py` — neue Tests (Klasse `WeekendHolidayEntryTest`)

---

## Task 1: Form-Validierung — nicht-Arbeits-Einträge an Wochenenden/Feiertagen ablehnen

**Files:**
- Modify: `timetracking/forms.py`
- Test: `timetracking/tests.py`

- [ ] **Step 1: Schreibe die fehlschlagenden Tests**

Hänge ans Ende von `timetracking/tests.py` an:

```python
class WeekendHolidayFormValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="formtest", password="pw123456")
        profile = self.user.userprofile
        profile.bundesland = "BY"
        profile.save()
        from timetracking.models import Job
        self.job = Job.objects.create(
            user=self.user, name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 1, 1),
        )

    def _form(self, data):
        from timetracking.forms import WorkEntryForm
        return WorkEntryForm(data=data, user=self.user, bundesland="BY")

    def test_work_entry_on_saturday_is_valid(self):
        # 2026-05-30 ist ein Samstag
        form = self._form({
            "job": self.job.pk,
            "date": "2026-05-30",
            "entry_type": "work",
            "start_time": "10:00",
            "end_time": "14:00",
            "break_minutes": "0",
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_work_entry_on_bavarian_holiday_is_valid(self):
        # 2026-05-01 (Tag der Arbeit) ist Feiertag in BY
        form = self._form({
            "job": self.job.pk,
            "date": "2026-05-01",
            "entry_type": "work",
            "start_time": "09:00",
            "end_time": "13:00",
            "break_minutes": "0",
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_urlaub_on_saturday_is_rejected(self):
        form = self._form({
            "job": self.job.pk,
            "date": "2026-05-30",
            "entry_type": "urlaub",
            "break_minutes": "0",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("entry_type", form.errors)

    def test_krankheit_on_holiday_is_rejected(self):
        form = self._form({
            "job": self.job.pk,
            "date": "2026-05-01",
            "entry_type": "krankheit",
            "break_minutes": "0",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("entry_type", form.errors)

    def test_homeoffice_on_sunday_is_rejected(self):
        form = self._form({
            "job": self.job.pk,
            "date": "2026-05-31",
            "entry_type": "homeoffice",
            "break_minutes": "0",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("entry_type", form.errors)

    def test_urlaub_on_normal_weekday_still_valid(self):
        # 2026-05-04 ist ein Montag, kein Feiertag in BY
        form = self._form({
            "job": self.job.pk,
            "date": "2026-05-04",
            "entry_type": "urlaub",
            "break_minutes": "0",
        })
        self.assertTrue(form.is_valid(), form.errors)
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `python manage.py test timetracking.tests.WeekendHolidayFormValidationTest -v 2`
Expected: Mehrere Tests scheitern (TypeError: unexpected keyword argument 'bundesland', oder Validierung greift nicht).

- [ ] **Step 3: `WorkEntryForm` anpassen**

In `timetracking/forms.py` Imports ergänzen und `WorkEntryForm` erweitern:

```python
from django import forms
from .models import Job, UserProfile, WorkEntry
from .utils import is_holiday
```

Die Methode `__init__` so ersetzen:

```python
    def __init__(self, *args, user=None, bundesland=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.bundesland = bundesland
        if user is not None:
            self.fields["job"].queryset = Job.objects.filter(user=user)
```

Am Ende von `clean()` (vor `return cleaned_data`) ergänzen:

```python
        if entry_date and self.bundesland:
            is_weekend = entry_date.weekday() >= 5
            holiday = is_holiday(entry_date, self.bundesland)
            if (is_weekend or holiday) and entry_type and entry_type != "work":
                self.add_error(
                    "entry_type",
                    "An Wochenenden und Feiertagen sind nur Arbeitseinträge möglich.",
                )
```

- [ ] **Step 4: `entry_create` und `entry_edit` Views anpassen**

In `timetracking/views.py` die zwei Stellen, an denen `WorkEntryForm(...)` instanziiert wird, um `bundesland=profile.bundesland` ergänzen.

In `entry_create` (Zeilen ~162 und ~170):

```python
    if request.method == "POST":
        form = WorkEntryForm(request.POST, user=request.user, bundesland=profile.bundesland)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user = request.user
            entry.save()
            messages.success(request, "Eintrag gespeichert.")
            return redirect("timetracking:dashboard")
    else:
        form = WorkEntryForm(initial=initial, user=request.user, bundesland=profile.bundesland)
```

In `entry_edit` (Zeilen ~184 und ~190):

```python
    if request.method == "POST":
        form = WorkEntryForm(request.POST, instance=entry, user=request.user, bundesland=profile.bundesland)
        if form.is_valid():
            form.save()
            messages.success(request, "Eintrag aktualisiert.")
            return redirect("timetracking:dashboard")
    else:
        form = WorkEntryForm(instance=entry, user=request.user, bundesland=profile.bundesland)
```

- [ ] **Step 5: Tests laufen lassen — müssen jetzt grün sein**

Run: `python manage.py test timetracking.tests.WeekendHolidayFormValidationTest -v 2`
Expected: Alle 6 Tests PASS.

- [ ] **Step 6: Restliche Testsuite gegenchecken (keine Regression)**

Run: `python manage.py test timetracking -v 1`
Expected: Alle Tests PASS.

- [ ] **Step 7: Commit**

```bash
git add timetracking/forms.py timetracking/views.py timetracking/tests.py
git commit -m "feat(timetracking): reject non-work entries on weekends and holidays"
```

---

## Task 2: Saldo-Korrektheit verifizieren — Wochenend-Arbeit fließt ins Saldo

**Files:**
- Test: `timetracking/tests.py`
- (Keine Code-Änderungen erwartet — `calculate_weekly_saldo` summiert bereits ohne Wochentag-Filter.)

- [ ] **Step 1: Test schreiben, der Wochenend-Arbeitsstunden im Saldo prüft**

Hänge ans Ende von `timetracking/tests.py` an:

```python
class WeekendHolidaySaldoTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="saldotest", password="pw123456")
        profile = self.user.userprofile
        profile.bundesland = "BY"
        profile.save()
        from timetracking.models import Job
        self.job = Job.objects.create(
            user=self.user, name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 5, 4),  # Montag der KW 19
        )

    def test_saturday_work_increases_saldo(self):
        from timetracking.models import WorkEntry
        from timetracking.utils import calculate_total_saldo
        from datetime import time
        # Mo-Fr (4.-8.5.) jeweils 8h = 40h Soll/Ist = 0 Saldo
        for day_offset in range(5):
            WorkEntry.objects.create(
                user=self.user, job=self.job,
                date=date(2026, 5, 4 + day_offset),
                entry_type="work",
                start_time=time(8, 0), end_time=time(16, 0), break_minutes=0,
            )
        # Sa (9.5.) zusätzlich 4h Arbeit
        WorkEntry.objects.create(
            user=self.user, job=self.job,
            date=date(2026, 5, 9),
            entry_type="work",
            start_time=time(10, 0), end_time=time(14, 0), break_minutes=0,
        )
        saldo = calculate_total_saldo(self.job, "BY", as_of=date(2026, 5, 11))
        self.assertEqual(saldo, Decimal("4.00"))

    def test_holiday_work_increases_saldo(self):
        from timetracking.models import WorkEntry
        from timetracking.utils import calculate_total_saldo
        from datetime import time
        # 2026-05-01 ist Feiertag in BY (Tag der Arbeit). job-Start ist 2026-05-04,
        # also setze Startdatum für diesen Test früher:
        self.job.work_start_date = date(2026, 4, 27)
        self.job.save()
        # KW 18 (27.4.-3.5.): Mo-Do (27.-30.4.) je 8h, Fr (1.5.) ist Feiertag
        # → Soll = 4 Tage × 8h = 32h
        from datetime import time as t
        for day_offset in range(4):
            WorkEntry.objects.create(
                user=self.user, job=self.job,
                date=date(2026, 4, 27 + day_offset),
                entry_type="work",
                start_time=t(8, 0), end_time=t(16, 0), break_minutes=0,
            )
        # Feiertag 1.5.: 5h Arbeit → +5h Saldo
        WorkEntry.objects.create(
            user=self.user, job=self.job,
            date=date(2026, 5, 1),
            entry_type="work",
            start_time=t(9, 0), end_time=t(14, 0), break_minutes=0,
        )
        saldo = calculate_total_saldo(self.job, "BY", as_of=date(2026, 5, 4))
        self.assertEqual(saldo, Decimal("5.00"))
```

- [ ] **Step 2: Tests laufen lassen**

Run: `python manage.py test timetracking.tests.WeekendHolidaySaldoTest -v 2`
Expected: Beide Tests PASS (Saldo-Logik in `utils.py` arbeitet bereits korrekt).

Falls einer scheitert: in `timetracking/utils.py` prüfen, ob `calculate_weekly_saldo` einen unerwarteten Filter hat — laut Spec ist nichts zu ändern. Falls doch nötig, hier korrigieren und festhalten.

- [ ] **Step 3: Commit**

```bash
git add timetracking/tests.py
git commit -m "test(timetracking): verify weekend and holiday work counts toward saldo"
```

---

## Task 3: Dashboard — View-Logik und Template für Wochenend-/Feiertag-Einträge

**Files:**
- Modify: `timetracking/views.py` — Funktion `dashboard()`
- Modify: `templates/timetracking/dashboard.html`
- Test: `timetracking/tests.py`

- [ ] **Step 1: Test schreiben, der Dashboard-Kontext für Wochenend-Eintrag prüft**

Hänge ans Ende von `timetracking/tests.py` an:

```python
class DashboardWeekendEntryTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="dashweekend", password="pw123456")
        self.client.login(username="dashweekend", password="pw123456")
        from timetracking.models import Job
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = Job.objects.create(
            user=self.user, name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 1, 1),
        )
        profile.active_job = self.job
        profile.save()

    def test_weekend_entry_appears_with_ist_and_diff(self):
        from timetracking.models import WorkEntry
        from datetime import time, timedelta
        today = date.today()
        # Nimm einen vergangenen Samstag der aktuellen Woche, falls heute ≥ Sa,
        # sonst kommenden Sa der aktuellen Woche (innerhalb week_data sichtbar).
        monday = today - timedelta(days=today.weekday())
        saturday = monday + timedelta(days=5)
        WorkEntry.objects.create(
            user=self.user, job=self.job, date=saturday,
            entry_type="work",
            start_time=time(10, 0), end_time=time(13, 0), break_minutes=0,
        )
        response = self.client.get("/timetracking/")
        week_data = response.context["week_data"]
        sat_row = next(d for d in week_data if d["day"] == saturday)
        self.assertEqual(sat_row["entry"].pk, WorkEntry.objects.first().pk)
        self.assertEqual(sat_row["ist"], Decimal("3.00"))
        self.assertEqual(sat_row["soll"], Decimal("0"))
        self.assertEqual(sat_row["diff"], Decimal("3.00"))
        self.assertFalse(sat_row["no_value"])
```

- [ ] **Step 2: Test laufen lassen — muss scheitern**

Run: `python manage.py test timetracking.tests.DashboardWeekendEntryTest -v 2`
Expected: FAIL — `no_value` ist `True` für Samstag, also wird `ist` aktuell als "–" gerendert; Assertion auf `ist == 3.00` scheitert oder `no_value`-Assertion scheitert.

- [ ] **Step 3: Logik in `dashboard()` anpassen**

In `timetracking/views.py`, im Schleifenblock innerhalb `dashboard()` (etwa Zeilen 61-90), den Block durch folgendes ersetzen:

```python
    daily_equiv = active_job.weekly_target_hours / Decimal("5")
    week_data = []
    for day in week_days:
        entry = entries_this_week.get(day)
        holiday_name = get_holiday_name(day, bundesland)
        is_weekend = day.weekday() >= 5
        is_soll = not is_weekend and not holiday_name
        soll = daily_equiv if is_soll else Decimal("0")

        if entry:
            if entry.entry_type == "work":
                ist = Decimal(str(entry.worked_hours or 0))
            else:
                ist = daily_equiv
        else:
            ist = Decimal("0")

        # Werte (Ist/Diff) anzeigen, wenn Werktag ODER Eintrag vorhanden.
        # An Wochenenden/Feiertagen ohne Eintrag bleibt die Zeile leer ("–").
        show_values = is_soll or entry is not None
        pending = is_soll and not entry and day >= today
        no_value = not show_values
        week_data.append({
            "day": day,
            "entry": entry,
            "holiday_name": holiday_name,
            "is_weekend": is_weekend,
            "is_soll": is_soll,
            "show_values": show_values,
            "soll": soll,
            "ist": ist,
            "diff": Decimal("0") if pending else ist - soll,
            "pending": pending,
            "no_value": no_value,
        })
```

- [ ] **Step 4: Test laufen lassen — muss jetzt grün sein**

Run: `python manage.py test timetracking.tests.DashboardWeekendEntryTest -v 2`
Expected: PASS.

- [ ] **Step 5: Template `dashboard.html` anpassen**

Ersetze in `templates/timetracking/dashboard.html` den Wochen-Tabellen-Block (Zeilen 72-104) durch:

```html
                        {% for d in week_data %}
                        <tr class="{% if d.is_weekend %}text-muted{% elif d.holiday_name %}table-info{% elif d.day == today %}table-warning{% endif %}">
                            <td class="ps-3">
                                {{ d.day|date:"D, d.m." }}
                                {% if d.holiday_name %}<br><small class="text-muted">{{ d.holiday_name }}</small>{% endif %}
                                {% if d.entry %}
                                <br><small class="text-muted">
                                    {{ d.entry.get_entry_type_display }}
                                    {% if d.entry.start_time %} {{ d.entry.start_time|time:"H:i" }}–{{ d.entry.end_time|time:"H:i" }}{% endif %}
                                </small>
                                {% endif %}
                            </td>
                            <td class="text-end">
                                {% if d.no_value %}–{% else %}{{ d.ist|floatformat:2 }}h{% endif %}
                            </td>
                            <td class="text-end">
                                {% if d.is_soll %}{{ d.soll|floatformat:2 }}h{% else %}–{% endif %}
                            </td>
                            <td class="text-end pe-3 {% if d.show_values and not d.pending %}{% if d.diff >= 0 %}text-success{% else %}text-danger{% endif %}{% endif %}">
                                {% if d.pending or not d.show_values %}–{% else %}{% if d.diff >= 0 %}+{% endif %}{{ d.diff|floatformat:2 }}h{% endif %}
                            </td>
                            <td class="text-end pe-3">
                                {% if d.entry %}
                                <a href="{% url 'timetracking:entry_edit' d.entry.pk %}" class="btn btn-sm btn-outline-secondary py-0 px-2" title="Bearbeiten">✎</a>
                                <a href="{% url 'timetracking:entry_delete' d.entry.pk %}" class="btn btn-sm btn-outline-danger py-0 px-2" title="Löschen">×</a>
                                {% else %}
                                <a href="{% url 'timetracking:entry_create' %}?date={{ d.day|date:'Y-m-d' }}" class="btn btn-sm btn-outline-primary py-0 px-2" title="Eintrag hinzufügen">+</a>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
```

Wesentliche Änderungen gegenüber dem Original:
- Eintrags-Info (Typ + Zeiten) wird jetzt bei jedem Eintrag angezeigt, nicht nur an Werktagen.
- Ist-Spalte zeigt Stunden, sobald `not no_value` (also auch Wochenende/Feiertag mit Eintrag).
- Diff-Spalte verwendet `show_values` statt `is_soll` — zeigt Diff auch bei Wochenend-/Feiertag-Eintrag.
- Aktions-Spalte ist nicht mehr auf Werktage beschränkt: "+"-Button auf jedem Tag ohne Eintrag, Bearbeiten/Löschen bei Eintrag.

- [ ] **Step 6: Manueller Smoke-Test (Browser)**

Run: `python manage.py runserver` und im Browser:
- Login, Dashboard öffnen → an einem Samstag/Sonntag ist ein "+"-Button.
- Über "+" einen Wochenend-Arbeitseintrag anlegen → erscheint in der Tabelle mit Ist und grünem Plus-Diff.
- Wochen-/Gesamt-Saldo zeigen die zusätzlichen Stunden.

Falls etwas nicht stimmt → reparieren, dann Tests erneut laufen lassen.

- [ ] **Step 7: Vollständige Testsuite laufen lassen**

Run: `python manage.py test timetracking -v 1`
Expected: Alle Tests PASS.

- [ ] **Step 8: Commit**

```bash
git add timetracking/views.py templates/timetracking/dashboard.html timetracking/tests.py
git commit -m "feat(timetracking): show weekend and holiday entries on dashboard"
```

---

## Task 4: Monatsdetail — Template für Wochenend-/Feiertag-Einträge

**Files:**
- Modify: `templates/timetracking/month_detail.html`
- Test: `timetracking/tests.py`

- [ ] **Step 1: Test schreiben, der prüft, dass Wochenend-Eintrag im Monatsdetail mit Werten erscheint**

Hänge ans Ende von `timetracking/tests.py` an:

```python
class MonthDetailWeekendEntryTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="monthweekend", password="pw123456")
        self.client.login(username="monthweekend", password="pw123456")
        from timetracking.models import Job
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = Job.objects.create(
            user=self.user, name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 1, 1),
        )
        profile.active_job = self.job
        profile.save()

    def test_weekend_entry_visible_in_month_detail(self):
        from timetracking.models import WorkEntry
        from datetime import time
        # 2026-05-09 ist ein Samstag
        WorkEntry.objects.create(
            user=self.user, job=self.job, date=date(2026, 5, 9),
            entry_type="work",
            start_time=time(10, 0), end_time=time(14, 0), break_minutes=0,
        )
        response = self.client.get("/timetracking/monat/2026/5/")
        content = response.content.decode("utf-8")
        # Die Stunden müssen in der gerenderten Tabelle erscheinen
        self.assertIn("4.00h", content)
        # Es muss Bearbeiten-Link zum Eintrag geben
        from timetracking.models import WorkEntry as WE
        pk = WE.objects.first().pk
        self.assertIn(f"/timetracking/eintrag/{pk}/bearbeiten/", content)
```

- [ ] **Step 2: Test laufen lassen — muss scheitern**

Run: `python manage.py test timetracking.tests.MonthDetailWeekendEntryTest -v 2`
Expected: FAIL — Wochenendzeilen rendern aktuell keine Werte und keine Bearbeiten-Links.

- [ ] **Step 3: Template `month_detail.html` anpassen**

Ersetze in `templates/timetracking/month_detail.html` den `<tbody>`-Block (Zeilen 67-97) durch:

```html
                <tbody>
                {% for d in days_data %}
                <tr class="{% if d.is_weekend %}text-muted{% elif d.holiday_name %}table-info{% endif %}">
                    <td class="ps-3">
                        {{ d.day|date:"D, d.m.Y" }}
                        {% if d.holiday_name %}<small class="ms-1 text-muted">({{ d.holiday_name }})</small>{% endif %}
                    </td>
                    <td>
                        {% if d.entry %}{{ d.entry.get_entry_type_display }}
                        {% elif d.is_weekend %}Wochenende
                        {% elif d.holiday_name %}Feiertag
                        {% else %}–{% endif %}
                    </td>
                    <td class="text-end">
                        {% if d.entry or not d.is_weekend and not d.holiday_name %}{{ d.ist|floatformat:2 }}h{% endif %}
                    </td>
                    <td class="text-end">
                        {% if not d.is_weekend and not d.holiday_name %}{{ d.soll|floatformat:2 }}h{% endif %}
                    </td>
                    <td class="text-end {% if d.entry or not d.is_weekend and not d.holiday_name %}{% if d.diff >= 0 %}text-success{% else %}text-danger{% endif %}{% endif %}">
                        {% if d.entry or not d.is_weekend and not d.holiday_name %}{% if d.diff >= 0 %}+{% endif %}{{ d.diff|floatformat:2 }}h{% endif %}
                    </td>
                    <td>
                        {% if d.entry %}
                        <a href="{% url 'timetracking:entry_edit' d.entry.pk %}" class="btn btn-sm btn-outline-secondary py-0 px-2" title="Bearbeiten">✎</a>
                        <a href="{% url 'timetracking:entry_delete' d.entry.pk %}" class="btn btn-sm btn-outline-danger py-0 px-2" title="Löschen">×</a>
                        {% else %}
                        <a href="{% url 'timetracking:entry_create' %}?date={{ d.day|date:'Y-m-d' }}" class="btn btn-sm btn-outline-primary py-0 px-2" title="Eintrag hinzufügen">+</a>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
                </tbody>
```

Wesentliche Änderungen:
- Ist und Diff erscheinen jetzt, sobald ein Eintrag vorhanden ist (auch an Wochenende/Feiertag).
- Aktions-Spalte ist immer aktiv: "+"-Button bei freiem Tag, Bearbeiten/Löschen bei Eintrag.
- Soll-Spalte bleibt nur an Werktagen befüllt (Soll ist 0h an Wochenenden/Feiertagen).

- [ ] **Step 4: Test laufen lassen — muss jetzt grün sein**

Run: `python manage.py test timetracking.tests.MonthDetailWeekendEntryTest -v 2`
Expected: PASS.

- [ ] **Step 5: Vollständige Testsuite laufen lassen**

Run: `python manage.py test timetracking -v 1`
Expected: Alle Tests PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/timetracking/month_detail.html timetracking/tests.py
git commit -m "feat(timetracking): show weekend and holiday entries in month detail"
```

---

## Task 5: Bericht — Wochenend-Einträge in den PDF/HTML-Bericht aufnehmen

**Files:**
- Modify: `templates/timetracking/report.html`
- Test: `timetracking/tests.py`

- [ ] **Step 1: Test schreiben, der Wochenend-Eintrag im Bericht prüft**

Hänge ans Ende von `timetracking/tests.py` an:

```python
class ReportWeekendEntryTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="reportweekend", password="pw123456")
        self.client.login(username="reportweekend", password="pw123456")
        from timetracking.models import Job
        profile = self.user.userprofile
        profile.timetracking_enabled = True
        profile.bundesland = "BY"
        profile.save()
        self.job = Job.objects.create(
            user=self.user, name="Hauptjob",
            weekly_target_hours=Decimal("40.00"),
            work_start_date=date(2026, 5, 1),
        )
        profile.active_job = self.job
        profile.save()

    def test_saturday_entry_appears_in_report(self):
        from timetracking.models import WorkEntry
        from datetime import time
        # 2026-05-09 = Samstag
        WorkEntry.objects.create(
            user=self.user, job=self.job, date=date(2026, 5, 9),
            entry_type="work",
            start_time=time(10, 0), end_time=time(13, 30), break_minutes=0,
        )
        response = self.client.get("/timetracking/bericht/2026/5/")
        content = response.content.decode("utf-8")
        # 3.50h sollte in der Bericht-Tabelle erscheinen
        self.assertIn("3.50h", content)
        # Datum 09.05.2026 sollte als Zeile vorhanden sein
        self.assertIn("09.05.2026", content)
```

- [ ] **Step 2: Test laufen lassen — muss scheitern**

Run: `python manage.py test timetracking.tests.ReportWeekendEntryTest -v 2`
Expected: FAIL — Bericht-Template überspringt Wochenenden komplett (`{% if not d.is_weekend %}`).

- [ ] **Step 3: Template `report.html` anpassen**

In `templates/timetracking/report.html` den `<tbody>`-Block (Zeilen 121-138) ersetzen durch:

```html
        <tbody>
        {% for d in days_data %}
        {% if not d.is_weekend or d.entry %}
        <tr class="{% if d.holiday_name %}table-secondary{% endif %}">
            <td>{{ d.day|date:"D, d.m.Y" }}</td>
            <td>
                {% if d.entry %}{{ d.entry.get_entry_type_display }}{% if d.holiday_name %} (Feiertag){% elif d.is_weekend %} (Wochenende){% endif %}
                {% elif d.holiday_name %}Feiertag ({{ d.holiday_name }})
                {% else %}–{% endif %}
            </td>
            <td class="text-end">{% if d.entry and d.entry.start_time %}{{ d.entry.start_time|time:"H:i" }}{% else %}–{% endif %}</td>
            <td class="text-end">{% if d.entry and d.entry.end_time %}{{ d.entry.end_time|time:"H:i" }}{% else %}–{% endif %}</td>
            <td class="text-end">{% if d.entry and d.entry.break_minutes %}{{ d.entry.break_minutes }}min{% else %}–{% endif %}</td>
            <td class="text-end">{% if d.ist %}{{ d.ist|floatformat:2 }}h{% else %}–{% endif %}</td>
        </tr>
        {% endif %}
        {% endfor %}
        </tbody>
```

Wesentliche Änderung: Wochenend-Tag wird gezeigt, sobald ein Eintrag vorliegt; Typ-Spalte markiert ihn als „(Wochenende)" bzw. „(Feiertag)".

- [ ] **Step 4: Test laufen lassen — muss jetzt grün sein**

Run: `python manage.py test timetracking.tests.ReportWeekendEntryTest -v 2`
Expected: PASS.

- [ ] **Step 5: Vollständige Testsuite laufen lassen**

Run: `python manage.py test timetracking -v 1`
Expected: Alle Tests PASS.

- [ ] **Step 6: Manueller Smoke-Test (Bericht im Browser)**

Run: `python manage.py runserver`, im Browser einen Monat mit Wochenend-Eintrag öffnen unter `/timetracking/bericht/<jahr>/<monat>/` — der Wochenendtag soll in der Tabelle erscheinen. PDF-Download über den Bericht-Button prüfen.

- [ ] **Step 7: Commit**

```bash
git add templates/timetracking/report.html timetracking/tests.py
git commit -m "feat(timetracking): include weekend and holiday entries in report"
```

---

## Selbst-Check nach Abschluss

- [ ] Alle 5 Tasks committed.
- [ ] `python manage.py test timetracking` läuft komplett grün.
- [ ] Manueller Browser-Test: Anlegen / Bearbeiten / Löschen eines Wochenend-Arbeitseintrags funktioniert; Saldo erhöht sich entsprechend; Bericht zeigt den Tag.
- [ ] Versuch, an einem Samstag „Urlaub" einzutragen, wird mit Fehlermeldung abgelehnt.
