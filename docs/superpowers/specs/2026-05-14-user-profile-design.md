# User Profile + E-Mail-Änderung — Design Spec

**Datum:** 2026-05-14
**Status:** Genehmigt

## Überblick

Eingeloggte User bekommen eine eigene Profil-Seite. Sichtbar und änderbar sind:
- Username
- Vorname / Nachname
- E-Mail (mit Verifizierungs-Mail vor Wechsel)
- Passwort (über Djangos Built-in-Flow)

Der Username unten in der Sidebar wird klickbar und führt zum Profil. E-Mail-Änderungen werden durch einen Bestätigungs-Link an die neue Adresse abgesichert.

## Datenmodell

`UserProfile` (timetracking app) bekommt drei neue Felder für den E-Mail-Wechsel:

| Feld | Typ | Beschreibung |
|---|---|---|
| `pending_email` | EmailField (nullable) | Neue E-Mail wartet auf Bestätigung |
| `email_verification_token` | UUIDField (nullable, unique) | Einmaliger Token für den Bestätigungs-Link |
| `email_token_expires_at` | DateTimeField (nullable) | Ablaufzeitpunkt = Generierung + 24h |

Username, Vorname, Nachname, E-Mail bleiben am Standard-`User`-Model (`django.contrib.auth`). Das Passwort wird über Djangos Built-in geändert; kein eigenes Feld nötig.

**Migration:** Drei neue nullable Felder auf `UserProfile`.

## URL-Struktur

Neue URLs unter `/accounts/profil/`:

| URL | View | Zweck |
|---|---|---|
| `/accounts/profil/` | `profile_view` | Übersicht + Inline-Form für Username/Vor-/Nachname |
| `/accounts/profil/email/` | `email_change_view` | Neue E-Mail eingeben → Verifizierungs-Mail |
| `/accounts/profil/email/bestaetigen/<uuid:token>/` | `email_verify_view` | Bestätigung aus dem Mail-Link |
| `/accounts/profil/email/abbrechen/` | `email_cancel_view` | Pending-State löschen (POST) |
| `/accounts/profil/passwort/` | Djangos `PasswordChangeView` | Alt + Neu + Wiederholung |
| `/accounts/profil/passwort/erfolg/` | Djangos `PasswordChangeDoneView` | Bestätigung |

## Views & Logik

### `profile_view` (`GET`/`POST`)

- `GET`: Zeigt Profil-Übersicht mit aktuellen Werten und `ProfileForm` (Username, Vorname, Nachname).
- `POST`: Speichert ProfileForm. Bei Erfolg: Success-Message + Redirect auf `profile_view`.

### `email_change_view` (`GET`/`POST`)

- `GET`: Zeigt `EmailChangeForm`.
- `POST`:
  1. Form validiert: nicht leer, nicht identisch mit `user.email`, nicht von anderem `User` belegt.
  2. Generiert UUID4-Token, setzt `profile.pending_email`, `profile.email_verification_token`, `profile.email_token_expires_at = now + 24h`.
  3. Rendert `accounts/email/verify_email.txt` mit `verification_url = request.build_absolute_uri(reverse('email_verify', kwargs={'token': token}))`.
  4. Versendet via `django.core.mail.send_mail` an die **neue** Adresse.
  5. Bei `Exception` beim Versand: Pending-Felder wieder leeren, Error-Message.
  6. Bei Erfolg: Redirect auf `accounts/email_verification_sent.html` mit `pending_email` im Kontext.

### `email_verify_view(request, token)`

- Sucht `UserProfile.objects.get(email_verification_token=token)`.
- Existiert nicht → Fehler-Page "Link ungültig oder bereits verwendet".
- `email_token_expires_at < now` → Fehler-Page "Link abgelaufen".
- Sonst: `user.email = profile.pending_email; user.save(update_fields=['email'])`, `pending_email/token/expires` auf `None`, Success-Message, Redirect auf `profile_view`.

### `email_cancel_view` (`POST`)

Löscht `pending_email`, `email_verification_token`, `email_token_expires_at` und redirected zurück auf `profile_view`.

### Passwort-Änderung

Verwendet Djangos eingebaute `PasswordChangeView` und `PasswordChangeDoneView`. URLs werden mit `success_url` auf `password_change_done` gesetzt. Template-Override im `accounts/` namespace mit Bootstrap-Styling.

## Forms

### `ProfileForm` (`accounts/forms.py`)

`ModelForm` für `User` mit Feldern `username`, `first_name`, `last_name`. Username-Validierung wie üblich (eindeutig); Bootstrap-Klassen via Widgets.

### `EmailChangeForm` (`accounts/forms.py`)

Einzelnes Feld `new_email = EmailField(required=True)`. `__init__` nimmt `user` als Keyword-Argument. `clean_new_email`:
- Wenn leer → ValidationError.
- Wenn `== user.email` → "Das ist bereits deine aktuelle Adresse".
- Wenn `User.objects.exclude(pk=user.pk).filter(email__iexact=value).exists()` → "Adresse wird bereits verwendet".

## Templates

Alle erben von `base.html`, Bootstrap 5.3.

- `templates/accounts/profile.html` — Übersicht + ProfileForm + Pending-Hinweis falls vorhanden + Links zu E-Mail/Passwort-Änderung.
- `templates/accounts/email_change.html` — `EmailChangeForm` + Hinweis zu aktueller Adresse.
- `templates/accounts/email_verification_sent.html` — "Bestätigung wurde an `{{ pending_email }}` gesendet, gültig bis `{{ expires_at }}`."
- `templates/accounts/email_verify_done.html` — Erfolgs-Page nach Klick auf Link. Bei Fehler: Hinweis + Link zum erneuten Anfordern.
- `templates/accounts/password_change_form.html` — überschreibt Djangos Default mit Bootstrap.
- `templates/accounts/password_change_done.html` — "Passwort geändert"-Bestätigung.
- `templates/accounts/email/verify_email.txt` — Plaintext-Mail mit `verification_url`.

### Pending-Banner auf Profil-Seite

Während `profile.pending_email` gesetzt ist:

```
Eine Bestätigung für [neue@adresse.de] wurde gesendet. Link gültig bis 14.05.2026 14:30.
[Erneut senden]  [Abbrechen]
```

### Sidebar (`templates/base.html`)

In Desktop-Sidebar und Mobile-Offcanvas wird der Username unten zu einem Link auf `/accounts/profil/`. Beispiel:

```html
<a href="{% url 'profile' %}" class="sidebar-user">{{ user.username }}</a>
```

Die Logout-Form bleibt direkt darunter unverändert.

## Tests

Datei: `accounts/tests.py`

- `ProfileViewTest.test_get_requires_login` — anonymous → redirect zum Login.
- `ProfileViewTest.test_post_updates_user_fields` — Username/Name werden gespeichert.
- `EmailChangeFormTest.test_rejects_existing_email` — Validation-Error wenn Adresse vergeben.
- `EmailChangeFormTest.test_rejects_same_email` — Validation-Error wenn identisch.
- `EmailChangeViewTest.test_sets_pending_and_sends_mail` — prüft `pending_email`, Token, `mail.outbox`.
- `EmailVerifyViewTest.test_valid_token_updates_email` — gültiger Token → User-E-Mail aktualisiert.
- `EmailVerifyViewTest.test_expired_token_rejected` — Token mit `expires_at` in der Vergangenheit → Fehler-Page.
- `EmailVerifyViewTest.test_unknown_token_rejected` — beliebige UUID → Fehler-Page.
- `EmailCancelViewTest.test_clears_pending_state` — POST → Pending-Felder leer.
- `PasswordChangeSmokeTest.test_form_loads` — `/accounts/profil/passwort/` rendert 200.

## Nicht im Scope

- Zwei-Faktor-Authentifizierung
- Account-Löschung
- Profilbild
- Abonnement / Benachrichtigungs-Einstellungen
- "Bekannte Geräte" / Session-Verwaltung
- Datenschutz-Export
