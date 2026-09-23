import logging
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth import views as auth_views
from django.db.models import Count
from django.shortcuts import render, redirect
from django.utils import timezone
from django.urls import Resolver404, resolve, reverse
from django.template.loader import render_to_string
from django.core.mail import send_mail

from households.models import Household
from households.utils import get_current_household
from tasks.models import Task
from meals.models import MealPlan
from shopping.models import ShoppingItem
from timetracking.models import UserProfile
from wochi.ratelimit import allow

from django.contrib import messages

from .forms import AccountDeleteForm, EmailChangeForm, LoginForm, ProfileForm, RegisterForm
from .services import delete_account
from .utils import client_ip, safe_next_url

logger = logging.getLogger(__name__)

# Passwort-Reset ist ein bekannter Vektor für Mail-Bombing: wer eine fremde
# Adresse kennt, kann sie ohne Bremse mit Reset-Mails zuschütten.
PASSWORD_RESET_MAX_PER_IP = 5
PASSWORD_RESET_MAX_PER_ADDRESS = 3
PASSWORD_RESET_WINDOW_SECONDS = 60 * 60

# Neue Konten je IP-Adresse – bremst Skripte, die massenhaft Konten anlegen.
REGISTER_MAX_PER_IP = 5
REGISTER_WINDOW_SECONDS = 60 * 60

# Schritte, die das Passwort abfragen, pro Benutzer begrenzen: sonst ließe
# sich mit einer offenen Sitzung das Passwort beliebig oft durchprobieren
# (und über die E-Mail-Änderung fremde Postfächer mit Mails fluten).
EMAIL_CHANGE_MAX_PER_HOUR = 5
ACCOUNT_DELETE_MAX_PER_HOUR = 5


def _is_invite_link(url):
    """Zeigt url auf einen Einladungslink? Dann weist die Anmeldeseite darauf hin."""
    if not url:
        return False
    try:
        return resolve(urlsplit(url).path).url_name == "join_via_link"
    except Resolver404:
        return False


class ThrottledLoginView(auth_views.LoginView):
    """Anmeldung. Die Bremse gegen Passwort-Raten steckt in LoginForm."""

    template_name = "registration/login.html"
    form_class = LoginForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Wer über einen Einladungslink kommt, hat oft noch kein Konto.
        context["is_invite"] = _is_invite_link(context.get(self.redirect_field_name))
        return context


class PasswordResetThrottledView(auth_views.PasswordResetView):
    """Reset-Anfragen pro IP-Adresse und pro Empfängeradresse begrenzen.

    Mit dem Default-Cache (LocMemCache, pro Prozess) ist das eine Bremsschwelle,
    kein harter Schutz — für einen echten Schutz bräuchte es einen geteilten
    Cache (Redis) oder eine Sperre auf Reverse-Proxy-Ebene.
    """

    def form_valid(self, form):
        email = form.cleaned_data["email"].strip().lower()
        within_limits = allow(
            f"pwreset-ip:{client_ip(self.request)}",
            PASSWORD_RESET_MAX_PER_IP,
            PASSWORD_RESET_WINDOW_SECONDS,
        ) and allow(
            # Derselbe Schlüssel wie in der App-API: Web und App teilen sich
            # das Kontingent pro Postfach.
            f"pwreset-mail:{email}",
            PASSWORD_RESET_MAX_PER_ADDRESS,
            PASSWORD_RESET_WINDOW_SECONDS,
        )
        if not within_limits:
            # Bewusst dieselbe Zielseite wie im Erfolgsfall: die Antwort darf
            # nicht verraten, ob eine Adresse existiert oder gesperrt ist.
            return redirect(self.get_success_url())
        return super().form_valid(form)


def register_view(request):
    # Kommt man über einen Einladungslink, geht es nach der Registrierung
    # dorthin zurück – sonst wäre die Einladung verloren.
    next_url = safe_next_url(request)

    if request.user.is_authenticated:
        return redirect(next_url or "home")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            # Gezählt werden nur neue Konten: wer sich beim Passwort vertippt,
            # soll nicht nach fünf Versuchen gesperrt sein.
            if allow(f"register:{client_ip(request)}", REGISTER_MAX_PER_IP, REGISTER_WINDOW_SECONDS):
                user = form.save()
                login(request, user, backend="accounts.backends.UsernameOrEmailBackend")
                return redirect(next_url or "choose_household")
            form.add_error(
                None,
                "Von deinem Internetanschluss wurden in der letzten Stunde schon mehrere "
                "Konten angelegt. Bitte versuche es später noch einmal.",
            )

    else:
        form = RegisterForm()

    return render(request, "registration/register.html", {
        "form": form,
        "next": next_url,
        "is_invite": _is_invite_link(next_url),
    })


@login_required
def home(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    context = {
        "household": household,
        "invite_url": request.build_absolute_uri(
            reverse("join_via_link", args=[household.invite_token])
        ),
        "open_tasks_count": 0,
        "done_tasks_count": 0,
        "planned_meals_count": 0,
        "open_shopping_count": 0,
        "recent_tasks": [],
        "recent_shopping_items": [],
    }

    if household:
        today = timezone.localdate()
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=13)

        open_tasks = Task.objects.filter(household=household, status="open")
        done_tasks = Task.objects.filter(household=household, status="done")
        meals_this_week = MealPlan.objects.filter(
            household=household,
            date__range=[start_of_week, end_of_week]
        )
        open_shopping = ShoppingItem.objects.filter(household=household, is_bought=False)

        context.update({
            "today": today,
            "open_tasks_count": open_tasks.count(),
            "done_tasks_count": done_tasks.count(),
            "planned_meals_count": meals_this_week.count(),
            "open_shopping_count": open_shopping.count(),
            "recent_tasks": open_tasks.order_by("due_date")[:5],
            "recent_shopping_items": open_shopping.order_by("created_at")[:5],
        })

    return render(request, "home.html", context)


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


@login_required
def email_change_view(request):
    # Ältere Konten haben kein UserProfile (das Signal kam später dazu).
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        if not allow(f"email-change:{request.user.pk}", EMAIL_CHANGE_MAX_PER_HOUR, 60 * 60):
            messages.error(
                request,
                "Du hast die Änderung in der letzten Stunde schon mehrmals angefordert. "
                "Bitte versuche es später noch einmal.",
            )
            return redirect("profile")
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
            except Exception:
                # Details (Mailserver, Zugangsdaten) gehören ins Log, nicht auf die Seite.
                logger.exception(
                    "Bestätigungs-Mail zur E-Mail-Änderung für Benutzer %s nicht gesendet",
                    request.user.pk,
                )
                profile.pending_email = None
                profile.email_verification_token = None
                profile.email_token_expires_at = None
                profile.save(update_fields=["pending_email", "email_verification_token", "email_token_expires_at"])
                messages.error(
                    request,
                    "Die Bestätigungs-Mail konnte gerade nicht gesendet werden. "
                    "Bitte versuche es später noch einmal.",
                )
                return redirect("profile")
            return render(request, "accounts/email_verification_sent.html", {
                "pending_email": profile.pending_email,
                "expires_at": profile.email_token_expires_at,
            })
    else:
        form = EmailChangeForm(user=request.user)
    return render(request, "accounts/email_change.html", {"form": form})


def email_verify_view(request, token):
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
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.pending_email = None
        profile.email_verification_token = None
        profile.email_token_expires_at = None
        profile.save(update_fields=["pending_email", "email_verification_token", "email_token_expires_at"])
        messages.info(request, "E-Mail-Änderung abgebrochen.")
    return redirect("profile")


@login_required
def account_delete_view(request):
    """Konto löschen – auch ohne App erreichbar (Vorgabe von Google Play)."""
    if request.method == "POST":
        if not allow(f"account-delete:{request.user.pk}", ACCOUNT_DELETE_MAX_PER_HOUR, 60 * 60):
            messages.error(
                request,
                "Zu viele Versuche in der letzten Stunde. Bitte versuche es später noch einmal.",
            )
            return redirect("account_delete")
        form = AccountDeleteForm(request.POST, user=request.user)
        if form.is_valid():
            delete_account(request.user)
            logout(request)
            messages.success(request, "Dein Konto wurde gelöscht. Schade, dass du gehst!")
            return redirect("login")
    else:
        form = AccountDeleteForm(user=request.user)

    # Pro Haushalt zeigen, was passiert. Über pk__in zählen: direkt auf
    # request.user.households wäre die Mitglieder-Verknüpfung schon auf den
    # Benutzer gefiltert und Count ergäbe immer 1.
    households = (
        Household.objects.filter(pk__in=request.user.households.values("pk"))
        .annotate(member_count=Count("members"))
        .order_by("name")
    )
    return render(request, "accounts/account_delete.html", {
        "form": form,
        "households_deleted": [h for h in households if h.member_count <= 1],
        "households_kept": [h for h in households if h.member_count > 1],
    })
