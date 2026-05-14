import uuid
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.shortcuts import render, redirect
from django.utils import timezone
from django.urls import reverse
from django.template.loader import render_to_string
from django.core.mail import send_mail

from households.utils import get_current_household
from tasks.models import Task
from meals.models import MealPlan
from shopping.models import ShoppingItem

from django.contrib import messages

from .forms import RegisterForm, ProfileForm, EmailChangeForm


def register_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("choose_household")
        
    else:
        form = RegisterForm()

    return render(request, "registration/register.html", {"form": form})

        
    

@login_required
def home(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    context = {
        "household": household,
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