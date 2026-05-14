# User Profile + E-Mail-Änderung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Profil-Seite für eingeloggte User mit View/Edit für Username, Vor-/Nachname, Passwort-Änderung und sicherer E-Mail-Änderung via Verifizierungs-Link.

**Architecture:** Erweitert die `accounts`-App um Profil-Views. `UserProfile` (timetracking) bekommt drei neue Felder für den E-Mail-Verifizierungsflow (`pending_email`, `email_verification_token`, `email_token_expires_at`). Passwort-Änderung nutzt Djangos Built-in `PasswordChangeView`. Username in Sidebar wird klickbarer Link zum Profil.

**Tech Stack:** Django 6, Bootstrap 5.3, django.core.mail

---

## File Map

**Modify:**
- `timetracking/models.py` — UserProfile mit 3 neuen Feldern
- `accounts/forms.py` — ProfileForm, EmailChangeForm
- `accounts/views.py` — profile_view, email_change_view, email_verify_view, email_cancel_view
- `accounts/urls.py` — neue URL-Patterns
- `accounts/tests.py` — Tests
- `templates/base.html` — Sidebar-Username klickbar

**Create:**
- `timetracking/migrations/0006_userprofile_email_verification.py` (auto)
- `templates/accounts/profile.html`
- `templates/accounts/email_change.html`
- `templates/accounts/email_verification_sent.html`
- `templates/accounts/email_verify_done.html`
- `templates/accounts/password_change_form.html`
- `templates/accounts/password_change_done.html`
- `templates/accounts/email/verify_email.txt`

---

## Task 1: UserProfile-Felder für E-Mail-Verifizierung

**Files:**
- Modify: `timetracking/models.py`
- Modify: `accounts/tests.py` (existing file — currently empty per Django default)
- Create: migration via makemigrations

- [ ] **Schritt 1: Failing test schreiben**

Read `/home/stefan/Projekte/Wochi/accounts/tests.py` first. Replace its contents with:

```python
import uuid
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.core import mail

User = get_user_model()


class UserProfileEmailFieldsTest(TestCase):
    def test_pending_email_fields_default_none(self):
        user = User.objects.create_user(username="profilefields", password="pw123456")
        p = user.userprofile
        self.assertIsNone(p.pending_email)
        self.assertIsNone(p.email_verification_token)
        self.assertIsNone(p.email_token_expires_at)

    def test_pending_email_fields_can_be_set(self):
        user = User.objects.create_user(username="setfields", password="pw123456")
        p = user.userprofile
        token = uuid.uuid4()
        p.pending_email = "new@example.com"
        p.email_verification_token = token
        p.email_token_expires_at = timezone.now() + timedelta(hours=24)
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.pending_email, "new@example.com")
        self.assertEqual(p.email_verification_token, token)
```

- [ ] **Schritt 2: Test muss FAIL sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test accounts.tests.UserProfileEmailFieldsTest -v 2 2>&1 | tail -10
```
Expected: AttributeError / field doesn't exist.

- [ ] **Schritt 3: Felder zu `timetracking/models.py` hinzufügen**

Read `/home/stefan/Projekte/Wochi/timetracking/models.py` first. Find the `UserProfile` class. Add these three fields right after `work_start_date`:

```python
    pending_email = models.EmailField(null=True, blank=True)
    email_verification_token = models.UUIDField(null=True, blank=True, unique=True)
    email_token_expires_at = models.DateTimeField(null=True, blank=True)
```

- [ ] **Schritt 4: Migration erstellen und anwenden**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py makemigrations timetracking && python manage.py migrate
```
Expected: `Applying timetracking.0006_...`

- [ ] **Schritt 5: Tests müssen PASS sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test accounts.tests.UserProfileEmailFieldsTest -v 2 2>&1 | tail -10
```
Expected: `OK`

- [ ] **Schritt 6: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add timetracking/ accounts/tests.py && git commit -m "feat: add pending email fields to UserProfile for verification flow"
```

---

## Task 2: ProfileForm + EmailChangeForm

**Files:**
- Modify: `accounts/forms.py`
- Modify: `accounts/tests.py`

- [ ] **Schritt 1: Failing tests anhängen**

Append to `/home/stefan/Projekte/Wochi/accounts/tests.py`:

```python
class ProfileFormTest(TestCase):
    def test_saves_username_and_names(self):
        from accounts.forms import ProfileForm
        user = User.objects.create_user(username="orig", password="pw123456", first_name="Old", last_name="Name")
        form = ProfileForm(data={"username": "newname", "first_name": "Max", "last_name": "Mustermann"}, instance=user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        user.refresh_from_db()
        self.assertEqual(user.username, "newname")
        self.assertEqual(user.first_name, "Max")
        self.assertEqual(user.last_name, "Mustermann")


class EmailChangeFormTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ec", password="pw123456", email="me@old.de")

    def test_rejects_same_email(self):
        from accounts.forms import EmailChangeForm
        form = EmailChangeForm(user=self.user, data={"new_email": "me@old.de"})
        self.assertFalse(form.is_valid())
        self.assertIn("new_email", form.errors)

    def test_rejects_existing_email(self):
        User.objects.create_user(username="other", password="pw123456", email="taken@x.de")
        from accounts.forms import EmailChangeForm
        form = EmailChangeForm(user=self.user, data={"new_email": "taken@x.de"})
        self.assertFalse(form.is_valid())
        self.assertIn("new_email", form.errors)

    def test_accepts_new_unique_email(self):
        from accounts.forms import EmailChangeForm
        form = EmailChangeForm(user=self.user, data={"new_email": "fresh@x.de"})
        self.assertTrue(form.is_valid(), form.errors)
```

- [ ] **Schritt 2: Test muss FAIL sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test accounts.tests.ProfileFormTest accounts.tests.EmailChangeFormTest -v 2 2>&1 | tail -10
```

- [ ] **Schritt 3: `accounts/forms.py` ergänzen**

Read `/home/stefan/Projekte/Wochi/accounts/forms.py` first. Append after the existing `RegisterForm`:

```python


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
        }
        labels = {
            "username": "Benutzername",
            "first_name": "Vorname",
            "last_name": "Nachname",
        }


class EmailChangeForm(forms.Form):
    new_email = forms.EmailField(
        label="Neue E-Mail-Adresse",
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_new_email(self):
        new_email = self.cleaned_data["new_email"]
        if self.user and new_email.lower() == (self.user.email or "").lower():
            raise forms.ValidationError("Das ist bereits deine aktuelle Adresse.")
        qs = User.objects.filter(email__iexact=new_email)
        if self.user:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError("Diese Adresse wird bereits verwendet.")
        return new_email
```

- [ ] **Schritt 4: Tests müssen PASS sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test accounts.tests.ProfileFormTest accounts.tests.EmailChangeFormTest -v 2 2>&1 | tail -10
```

- [ ] **Schritt 5: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add accounts/ && git commit -m "feat: add ProfileForm and EmailChangeForm"
```

---

## Task 3: Profile-View + URLs + Template

**Files:**
- Modify: `accounts/views.py`
- Modify: `accounts/urls.py`
- Modify: `accounts/tests.py`
- Create: `templates/accounts/profile.html`

- [ ] **Schritt 1: Failing tests anhängen**

Append to `/home/stefan/Projekte/Wochi/accounts/tests.py`:

```python
class ProfileViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="pv", password="pw123456", email="pv@x.de", first_name="Anna")
        self.client.login(username="pv", password="pw123456")

    def test_get_loads(self):
        response = self.client.get("/accounts/profil/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anna")
        self.assertContains(response, "pv@x.de")

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get("/accounts/profil/")
        self.assertRedirects(response, "/accounts/login/?next=/accounts/profil/")

    def test_post_updates_user_fields(self):
        response = self.client.post("/accounts/profil/", {
            "username": "pv",
            "first_name": "Bertha",
            "last_name": "Beispiel",
        })
        self.assertRedirects(response, "/accounts/profil/")
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Bertha")
        self.assertEqual(self.user.last_name, "Beispiel")
```

- [ ] **Schritt 2: Test muss FAIL sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test accounts.tests.ProfileViewTest -v 2 2>&1 | tail -10
```

- [ ] **Schritt 3: View zu `accounts/views.py` hinzufügen**

Read `/home/stefan/Projekte/Wochi/accounts/views.py` first. Append:

```python
from django.contrib import messages
from .forms import ProfileForm


@login_required
def profile_view(request):
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profil aktualisiert.")
            return redirect("profile")
    else:
        form = ProfileForm(instance=request.user)
    return render(request, "accounts/profile.html", {"form": form, "profile": getattr(request.user, "userprofile", None)})
```

- [ ] **Schritt 4: URL anhängen**

Replace `/home/stefan/Projekte/Wochi/accounts/urls.py` with:

```python
from django.urls import path
from .views import home, register_view, profile_view

urlpatterns = [
    path("", home, name="home"),
    path("register/", register_view, name="register"),
    path("accounts/profil/", profile_view, name="profile"),
]
```

NOTE: `accounts.urls` is included at the root in `wochi/urls.py` via `path("", include("accounts.urls"))`. So `accounts/profil/` URL pattern here becomes `/accounts/profil/` in the final URL.

- [ ] **Schritt 5: Template erstellen**

Create `/home/stefan/Projekte/Wochi/templates/accounts/profile.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:600px">
    <h1 class="h3 mb-4">Profil</h1>

    {% if messages %}
    <div class="mb-3">
        {% for m in messages %}
        <div class="alert alert-{{ m.tags|default:'info' }} alert-dismissible fade show" role="alert">
            {{ m }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    </div>
    {% endif %}

    <div class="card mb-4">
        <div class="card-body">
            <h5 class="card-title">Persönliche Daten</h5>
            <form method="post">
                {% csrf_token %}
                <div class="mb-3">
                    <label for="{{ form.username.id_for_label }}" class="form-label">{{ form.username.label }}</label>
                    {{ form.username }}
                    {% if form.username.errors %}<div class="invalid-feedback d-block">{{ form.username.errors }}</div>{% endif %}
                </div>
                <div class="mb-3">
                    <label for="{{ form.first_name.id_for_label }}" class="form-label">{{ form.first_name.label }}</label>
                    {{ form.first_name }}
                </div>
                <div class="mb-3">
                    <label for="{{ form.last_name.id_for_label }}" class="form-label">{{ form.last_name.label }}</label>
                    {{ form.last_name }}
                </div>
                <button type="submit" class="btn btn-primary">Speichern</button>
            </form>
        </div>
    </div>

    <div class="card mb-4">
        <div class="card-body">
            <h5 class="card-title">E-Mail</h5>
            <p class="mb-2">Aktuell: <strong>{{ user.email|default:"– keine –" }}</strong></p>
            {% if profile.pending_email %}
            <div class="alert alert-info py-2">
                Bestätigung für <strong>{{ profile.pending_email }}</strong> ausstehend.
                Link gültig bis {{ profile.email_token_expires_at|date:"d.m.Y H:i" }}.
                <form method="post" action="{% url 'email_cancel' %}" class="d-inline">
                    {% csrf_token %}
                    <button type="submit" class="btn btn-sm btn-outline-secondary ms-2">Abbrechen</button>
                </form>
            </div>
            {% endif %}
            <a href="{% url 'email_change' %}" class="btn btn-outline-primary btn-sm">E-Mail ändern</a>
        </div>
    </div>

    <div class="card">
        <div class="card-body">
            <h5 class="card-title">Passwort</h5>
            <a href="{% url 'password_change' %}" class="btn btn-outline-primary btn-sm">Passwort ändern</a>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Schritt 6: Stub-URLs für email_change/email_cancel/password_change** (damit URL-Resolver für Template nicht crasht)

Modify `/home/stefan/Projekte/Wochi/accounts/urls.py` to:

```python
from django.urls import path
from django.contrib.auth import views as auth_views
from .views import home, register_view, profile_view

urlpatterns = [
    path("", home, name="home"),
    path("register/", register_view, name="register"),
    path("accounts/profil/", profile_view, name="profile"),
    # Stubs - implemented in later tasks
    path("accounts/profil/email/", profile_view, name="email_change"),
    path("accounts/profil/email/abbrechen/", profile_view, name="email_cancel"),
    path("accounts/profil/passwort/", auth_views.PasswordChangeView.as_view(), name="password_change"),
]
```

- [ ] **Schritt 7: Tests müssen PASS sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test accounts.tests.ProfileViewTest -v 2 2>&1 | tail -10
```

- [ ] **Schritt 8: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add accounts/ templates/accounts/ && git commit -m "feat: add profile view, template and base URLs"
```

---

## Task 4: E-Mail-Änderung — View, Verifizierung, Cancel

**Files:**
- Modify: `accounts/views.py`
- Modify: `accounts/urls.py`
- Modify: `accounts/tests.py`
- Create: `templates/accounts/email_change.html`
- Create: `templates/accounts/email_verification_sent.html`
- Create: `templates/accounts/email_verify_done.html`
- Create: `templates/accounts/email/verify_email.txt`

- [ ] **Schritt 1: Failing tests anhängen**

Append to `/home/stefan/Projekte/Wochi/accounts/tests.py`:

```python
class EmailChangeViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="ec2", password="pw123456", email="old@x.de")
        self.client.login(username="ec2", password="pw123456")

    def test_get_loads_form(self):
        response = self.client.get("/accounts/profil/email/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Neue E-Mail")

    def test_post_sets_pending_and_sends_mail(self):
        mail.outbox = []
        response = self.client.post("/accounts/profil/email/", {"new_email": "new@x.de"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bestätigung")
        self.user.userprofile.refresh_from_db()
        self.assertEqual(self.user.userprofile.pending_email, "new@x.de")
        self.assertIsNotNone(self.user.userprofile.email_verification_token)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("new@x.de", mail.outbox[0].to)


class EmailVerifyViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ev", password="pw123456", email="old@x.de")
        self.token = uuid.uuid4()
        p = self.user.userprofile
        p.pending_email = "new@x.de"
        p.email_verification_token = self.token
        p.email_token_expires_at = timezone.now() + timedelta(hours=24)
        p.save()

    def test_valid_token_updates_email(self):
        response = self.client.get(f"/accounts/profil/email/bestaetigen/{self.token}/")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.user.userprofile.refresh_from_db()
        self.assertEqual(self.user.email, "new@x.de")
        self.assertIsNone(self.user.userprofile.pending_email)
        self.assertIsNone(self.user.userprofile.email_verification_token)

    def test_expired_token_rejected(self):
        p = self.user.userprofile
        p.email_token_expires_at = timezone.now() - timedelta(hours=1)
        p.save()
        response = self.client.get(f"/accounts/profil/email/bestaetigen/{self.token}/")
        self.assertContains(response, "abgelaufen", status_code=200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "old@x.de")

    def test_unknown_token_rejected(self):
        bogus = uuid.uuid4()
        response = self.client.get(f"/accounts/profil/email/bestaetigen/{bogus}/")
        self.assertContains(response, "ungültig", status_code=200)


class EmailCancelViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="cancel", password="pw123456")
        self.client.login(username="cancel", password="pw123456")
        p = self.user.userprofile
        p.pending_email = "x@y.de"
        p.email_verification_token = uuid.uuid4()
        p.email_token_expires_at = timezone.now() + timedelta(hours=24)
        p.save()

    def test_post_clears_pending(self):
        response = self.client.post("/accounts/profil/email/abbrechen/")
        self.assertRedirects(response, "/accounts/profil/")
        self.user.userprofile.refresh_from_db()
        self.assertIsNone(self.user.userprofile.pending_email)
        self.assertIsNone(self.user.userprofile.email_verification_token)
```

- [ ] **Schritt 2: Test muss FAIL sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test accounts.tests.EmailChangeViewTest accounts.tests.EmailVerifyViewTest accounts.tests.EmailCancelViewTest -v 2 2>&1 | tail -10
```

- [ ] **Schritt 3: Views in `accounts/views.py` anhängen**

```python
import uuid
from datetime import timedelta
from django.utils import timezone
from django.urls import reverse
from django.template.loader import render_to_string
from django.core.mail import send_mail
from .forms import EmailChangeForm


@login_required
def email_change_view(request):
    profile = request.user.userprofile
    if request.method == "POST":
        form = EmailChangeForm(request.POST, user=request.user)
        if form.is_valid():
            token = uuid.uuid4()
            profile.pending_email = form.cleaned_data["new_email"]
            profile.email_verification_token = token
            profile.email_token_expires_at = timezone.now() + timedelta(hours=24)
            profile.save(update_fields=["pending_email", "email_verification_token", "email_token_expires_at"])

            verification_url = request.build_absolute_uri(
                reverse("email_verify", kwargs={"token": token})
            )
            body = render_to_string("accounts/email/verify_email.txt", {
                "user": request.user,
                "verification_url": verification_url,
            })
            try:
                send_mail(
                    subject="Wochii: E-Mail-Adresse bestätigen",
                    message=body,
                    from_email=None,
                    recipient_list=[profile.pending_email],
                    fail_silently=False,
                )
            except Exception as e:
                profile.pending_email = None
                profile.email_verification_token = None
                profile.email_token_expires_at = None
                profile.save(update_fields=["pending_email", "email_verification_token", "email_token_expires_at"])
                messages.error(request, f"E-Mail konnte nicht gesendet werden: {e}")
                return redirect("profile")
            return render(request, "accounts/email_verification_sent.html", {
                "pending_email": profile.pending_email,
                "expires_at": profile.email_token_expires_at,
            })
    else:
        form = EmailChangeForm(user=request.user)
    return render(request, "accounts/email_change.html", {"form": form})


def email_verify_view(request, token):
    from timetracking.models import UserProfile
    try:
        profile = UserProfile.objects.get(email_verification_token=token)
    except UserProfile.DoesNotExist:
        return render(request, "accounts/email_verify_done.html", {"error": "ungültig"})

    if not profile.email_token_expires_at or profile.email_token_expires_at < timezone.now():
        return render(request, "accounts/email_verify_done.html", {"error": "abgelaufen"})

    user = profile.user
    user.email = profile.pending_email
    user.save(update_fields=["email"])
    profile.pending_email = None
    profile.email_verification_token = None
    profile.email_token_expires_at = None
    profile.save(update_fields=["pending_email", "email_verification_token", "email_token_expires_at"])
    return render(request, "accounts/email_verify_done.html", {"new_email": user.email})


@login_required
def email_cancel_view(request):
    if request.method == "POST":
        profile = request.user.userprofile
        profile.pending_email = None
        profile.email_verification_token = None
        profile.email_token_expires_at = None
        profile.save(update_fields=["pending_email", "email_verification_token", "email_token_expires_at"])
        messages.info(request, "E-Mail-Änderung abgebrochen.")
    return redirect("profile")
```

- [ ] **Schritt 4: URLs anpassen**

Replace `/home/stefan/Projekte/Wochi/accounts/urls.py`:

```python
from django.urls import path
from django.contrib.auth import views as auth_views
from .views import (
    home,
    register_view,
    profile_view,
    email_change_view,
    email_verify_view,
    email_cancel_view,
)

urlpatterns = [
    path("", home, name="home"),
    path("register/", register_view, name="register"),
    path("accounts/profil/", profile_view, name="profile"),
    path("accounts/profil/email/", email_change_view, name="email_change"),
    path("accounts/profil/email/bestaetigen/<uuid:token>/", email_verify_view, name="email_verify"),
    path("accounts/profil/email/abbrechen/", email_cancel_view, name="email_cancel"),
    path("accounts/profil/passwort/",
         auth_views.PasswordChangeView.as_view(
             template_name="accounts/password_change_form.html",
             success_url="/accounts/profil/passwort/erfolg/",
         ),
         name="password_change"),
    path("accounts/profil/passwort/erfolg/",
         auth_views.PasswordChangeDoneView.as_view(
             template_name="accounts/password_change_done.html",
         ),
         name="password_change_done"),
]
```

- [ ] **Schritt 5: Templates erstellen**

`/home/stefan/Projekte/Wochi/templates/accounts/email_change.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:500px">
    <h1 class="h3 mb-4">E-Mail ändern</h1>
    <div class="card">
        <div class="card-body">
            <p class="text-muted">Aktuell: <strong>{{ user.email|default:"– keine –" }}</strong></p>
            <form method="post">
                {% csrf_token %}
                <div class="mb-3">
                    <label for="{{ form.new_email.id_for_label }}" class="form-label">{{ form.new_email.label }}</label>
                    {{ form.new_email }}
                    {% if form.new_email.errors %}<div class="invalid-feedback d-block">{{ form.new_email.errors }}</div>{% endif %}
                </div>
                <p class="form-text">Wir senden einen Bestätigungs-Link an die neue Adresse.</p>
                <div class="d-flex gap-2">
                    <button type="submit" class="btn btn-primary">Bestätigungs-Mail senden</button>
                    <a href="{% url 'profile' %}" class="btn btn-outline-secondary">Abbrechen</a>
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}
```

`/home/stefan/Projekte/Wochi/templates/accounts/email_verification_sent.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:500px">
    <h1 class="h3 mb-4">Bestätigung gesendet</h1>
    <div class="card">
        <div class="card-body">
            <p>Eine Bestätigung wurde an <strong>{{ pending_email }}</strong> gesendet.</p>
            <p class="text-muted">Der Link ist gültig bis {{ expires_at|date:"d.m.Y H:i" }}.</p>
            <a href="{% url 'profile' %}" class="btn btn-outline-secondary">Zurück zum Profil</a>
        </div>
    </div>
</div>
{% endblock %}
```

`/home/stefan/Projekte/Wochi/templates/accounts/email_verify_done.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:500px">
    {% if error == "ungültig" %}
    <div class="alert alert-danger">
        Dieser Bestätigungs-Link ist ungültig oder wurde bereits verwendet.
    </div>
    {% elif error == "abgelaufen" %}
    <div class="alert alert-warning">
        Dieser Bestätigungs-Link ist abgelaufen. Bitte E-Mail-Änderung erneut anfordern.
    </div>
    {% else %}
    <div class="alert alert-success">
        E-Mail-Adresse wurde auf <strong>{{ new_email }}</strong> aktualisiert.
    </div>
    {% endif %}
    <a href="{% url 'profile' %}" class="btn btn-outline-secondary">Zum Profil</a>
</div>
{% endblock %}
```

`/home/stefan/Projekte/Wochi/templates/accounts/email/verify_email.txt`:
```
Hallo {{ user.username }},

du möchtest deine E-Mail-Adresse auf Wochii ändern. Bitte bestätige
mit folgendem Link (gültig für 24 Stunden):

{{ verification_url }}

Falls du das nicht warst, ignoriere diese Mail.

— Wochii
```

- [ ] **Schritt 6: Tests müssen PASS sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test accounts.tests.EmailChangeViewTest accounts.tests.EmailVerifyViewTest accounts.tests.EmailCancelViewTest -v 2 2>&1 | tail -10
```
Expected: OK, all tests passing.

- [ ] **Schritt 7: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add accounts/ templates/accounts/ && git commit -m "feat: email change flow with verification link"
```

---

## Task 5: Passwort-Templates

**Files:**
- Create: `templates/accounts/password_change_form.html`
- Create: `templates/accounts/password_change_done.html`
- Modify: `accounts/tests.py`

- [ ] **Schritt 1: Smoke-Test anhängen**

```python
class PasswordChangeSmokeTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="pwc", password="pw123456")
        self.client.login(username="pwc", password="pw123456")

    def test_change_form_loads(self):
        response = self.client.get("/accounts/profil/passwort/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwort")

    def test_done_page_loads(self):
        response = self.client.get("/accounts/profil/passwort/erfolg/")
        self.assertEqual(response.status_code, 200)
```

- [ ] **Schritt 2: Templates erstellen**

`/home/stefan/Projekte/Wochi/templates/accounts/password_change_form.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:500px">
    <h1 class="h3 mb-4">Passwort ändern</h1>
    <div class="card">
        <div class="card-body">
            <form method="post">
                {% csrf_token %}
                {% for field in form %}
                <div class="mb-3">
                    <label for="{{ field.id_for_label }}" class="form-label">{{ field.label }}</label>
                    <input type="password" name="{{ field.name }}" id="{{ field.id_for_label }}" class="form-control" autocomplete="new-password">
                    {% if field.help_text %}<div class="form-text">{{ field.help_text|safe }}</div>{% endif %}
                    {% if field.errors %}<div class="invalid-feedback d-block">{{ field.errors }}</div>{% endif %}
                </div>
                {% endfor %}
                <div class="d-flex gap-2">
                    <button type="submit" class="btn btn-primary">Passwort ändern</button>
                    <a href="{% url 'profile' %}" class="btn btn-outline-secondary">Abbrechen</a>
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}
```

`/home/stefan/Projekte/Wochi/templates/accounts/password_change_done.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:500px">
    <div class="alert alert-success">Dein Passwort wurde aktualisiert.</div>
    <a href="{% url 'profile' %}" class="btn btn-outline-secondary">Zum Profil</a>
</div>
{% endblock %}
```

- [ ] **Schritt 3: Tests müssen PASS sein**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test accounts.tests.PasswordChangeSmokeTest -v 2 2>&1 | tail -10
```

- [ ] **Schritt 4: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add templates/accounts/ accounts/tests.py && git commit -m "feat: bootstrap-styled password change templates"
```

---

## Task 6: Sidebar-Username klickbar

**Files:**
- Modify: `templates/base.html`

- [ ] **Schritt 1: Beide Sidebars anpassen**

In `/home/stefan/Projekte/Wochi/templates/base.html`, finde alle Vorkommen von:
```html
<span class="sidebar-user">{{ user.username }}</span>
```
und ersetze sie durch:
```html
<a href="{% url 'profile' %}" class="sidebar-user">{{ user.username }}</a>
```

Es gibt **zwei** Vorkommen (Mobile Offcanvas + Desktop Sidebar) — beide ersetzen.

- [ ] **Schritt 2: Django check + smoke**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py check && python manage.py test accounts -v 0 2>&1 | tail -5
```
Expected: System check OK, all accounts tests OK.

- [ ] **Schritt 3: Commit**

```bash
cd /home/stefan/Projekte/Wochi && git add templates/base.html && git commit -m "feat: sidebar username links to profile"
```

---

## Abschluss

- [ ] **Alle Tests laufen durch**

```bash
cd /home/stefan/Projekte/Wochi && source venv/bin/activate && python manage.py test 2>&1 | tail -5
```
Expected: All tests OK.

- [ ] **Push**

```bash
cd /home/stefan/Projekte/Wochi && git push origin main
```
