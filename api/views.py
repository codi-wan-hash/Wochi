import datetime
import json
import logging
import re
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.services import delete_account
from households.models import Household, HouseholdSelection
from households.utils import get_current_household, leave_household, set_current_household
from meals.ai import QUOTA_MESSAGE, ai_quota_available, openai_client
from meals.models import Ingredient, MealPlan, Recipe
from shopping import services as shopping_services
from shopping.models import ShoppingItem, Store, ShoppingSession
from shopping.sync import MAX_OPS_PER_REQUEST, apply_ops, snapshot
from shopping.utils import sort_by_store as _sort_by_store
from tasks.models import Task
from wochi.ratelimit import allow
from .authentication import (
    WochiiTokenObtainPairSerializer,
    WochiiTokenRefreshSerializer,
    tokens_for_user,
)
from .models import PushToken
from .push import notify_household, notify_users

from .serializers import (
    HouseholdSerializer,
    IngredientSerializer,
    MealPlanSerializer,
    MeSerializer,
    RecipeSerializer,
    RegisterSerializer,
    ShoppingItemSerializer,
    ShoppingSessionSerializer,
    StoreSerializer,
    TaskSerializer,
    UserSerializer,
)

User = get_user_model()
logger = logging.getLogger(__name__)

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

# Erledigte Aufgaben, die die Liste höchstens mitliefert. Offene Aufgaben
# kommen immer vollständig – vorher schnitt ein festes [:100] nach Datum ab,
# und neue Aufgaben verschwanden aus der App, sobald alte sich häuften.
DONE_TASKS_IN_LIST = 50


def _parse_date(value):
    """ISO-Datum aus Query/Body; None, wenn leer oder ungültig."""
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        return None


# ── Push Notifications ────────────────────────────────────────────────────────

@api_view(["POST"])
def register_push_token(request):
    token = (request.data.get("token") or "").strip()
    if not token or len(token) > 300:
        return Response({"detail": "Token erforderlich."}, status=status.HTTP_400_BAD_REQUEST)
    # Ein Gerät gehört immer nur zum zuletzt angemeldeten Konto – sonst
    # bekäme ein geteiltes Handy weiter die Nachrichten des alten Kontos.
    PushToken.objects.filter(token=token).exclude(user=request.user).delete()
    PushToken.objects.update_or_create(user=request.user, defaults={"token": token})
    return Response({"detail": "OK"})


@api_view(["POST"])
def unregister_push_token(request):
    """Beim Abmelden: dieses Gerät bekommt keine Nachrichten mehr."""
    token = (request.data.get("token") or "").strip()
    tokens = PushToken.objects.filter(user=request.user)
    if token:
        tokens = tokens.filter(token=token)
    tokens.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginView(TokenObtainPairView):
    serializer_class = WochiiTokenObtainPairSerializer
    throttle_scope = "auth"


class RefreshView(TokenRefreshView):
    serializer_class = WochiiTokenRefreshSerializer
    throttle_scope = "refresh"


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_scope = "auth"


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user).data)


class PasswordResetRequestView(APIView):
    """Passwort vergessen: schickt dieselbe Mail wie die Web-App.

    Der Link darin öffnet die Web-Seite zum Setzen des neuen Passworts,
    danach meldet man sich in der App mit dem neuen Passwort an. Die Antwort
    ist immer gleich, damit sich nicht herausfinden lässt, welche Adressen
    ein Konto haben.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "password_reset"

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        form = PasswordResetForm({"email": email})
        # Pro Adresse begrenzt, damit niemand ein fremdes Postfach flutet.
        if form.is_valid() and allow(f"pwreset-mail:{email.lower()}", 3, 60 * 60):
            form.save(
                request=request,
                use_https=request.is_secure(),
                email_template_name="registration/password_reset_email.txt",
                subject_template_name="registration/password_reset_subject.txt",
            )
        return Response({
            "detail": "Wenn es ein Konto mit dieser Adresse gibt, ist jetzt eine E-Mail "
                      "mit einem Link zum Zurücksetzen unterwegs."
        })


class PasswordChangeView(APIView):
    throttle_scope = "auth"

    def post(self, request):
        user = request.user
        if not user.check_password(request.data.get("old_password") or ""):
            return Response(
                {"old_password": ["Das aktuelle Passwort stimmt nicht."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        new_password = request.data.get("new_password") or ""
        try:
            password_validation.validate_password(new_password, user)
        except DjangoValidationError as exc:
            return Response({"new_password": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save(update_fields=["password"])
        # Alle anderen Geräte sind damit abgemeldet (siehe authentication.py);
        # dieses Gerät bekommt neue Tokens und bleibt angemeldet.
        return Response(tokens_for_user(user))


class DeleteAccountView(APIView):
    throttle_scope = "auth"

    def post(self, request):
        if not request.user.check_password(request.data.get("password") or ""):
            return Response(
                {"password": ["Das Passwort stimmt nicht."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        delete_account(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Households ────────────────────────────────────────────────────────────────

def _household_payload(request, households):
    current = get_current_household(request.user)
    current_id = current.pk if current else None
    # Aktiver Haushalt zuerst: ältere App-Versionen nehmen households[0].
    ordered = sorted(households, key=lambda h: (h.pk != current_id, h.name.lower(), h.pk))
    return HouseholdSerializer(ordered, many=True, context={"current_id": current_id}).data


def _single_household_payload(request, household):
    current = get_current_household(request.user)
    return HouseholdSerializer(
        household, context={"current_id": current.pk if current else None}
    ).data


def _member_household(request, pk):
    return request.user.households.filter(pk=pk).first()


class HouseholdListView(APIView):
    def get(self, request):
        households = list(request.user.households.prefetch_related("members"))
        return Response(_household_payload(request, households))

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "Name erforderlich."}, status=status.HTTP_400_BAD_REQUEST)
        if len(name) > 100:
            return Response({"detail": "Der Name darf höchstens 100 Zeichen lang sein."},
                            status=status.HTTP_400_BAD_REQUEST)
        household = Household.objects.create(name=name)
        household.members.add(request.user)
        set_current_household(request.user, household)
        return Response(_single_household_payload(request, household), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def join_household(request):
    """Beitreten mit Code oder komplettem Einladungslink (beides wird erkannt)."""
    match = UUID_RE.search(request.data.get("token") or "")
    if not match:
        return Response({"detail": "Bitte den Einladungslink oder -code eingeben."},
                        status=status.HTTP_400_BAD_REQUEST)
    household = Household.objects.filter(invite_token=match.group(0).lower()).first()
    if household is None:
        return Response({"detail": "Ungültiger oder abgelaufener Einladungslink."},
                        status=status.HTTP_404_NOT_FOUND)
    household.members.add(request.user)
    set_current_household(request.user, household)
    return Response(_single_household_payload(request, household))


@api_view(["POST"])
def household_activate(request, pk):
    household = _member_household(request, pk)
    if household is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    set_current_household(request.user, household)
    return Response(_single_household_payload(request, household))


@api_view(["POST"])
def household_leave(request, pk):
    household = _member_household(request, pk)
    if household is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    deleted = leave_household(request.user, household)
    return Response({"deleted": deleted})


@api_view(["POST"])
def household_regenerate_invite(request, pk):
    """Neuer Einladungslink – der alte funktioniert danach nicht mehr."""
    household = _member_household(request, pk)
    if household is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    household.invite_token = uuid.uuid4()
    household.save(update_fields=["invite_token"])
    return Response(_single_household_payload(request, household))


@api_view(["POST"])
def household_remove_member(request, pk, user_id):
    household = _member_household(request, pk)
    if household is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    if user_id == request.user.pk:
        return Response({"detail": "Zum Verlassen bitte „Haushalt verlassen“ nutzen."},
                        status=status.HTTP_400_BAD_REQUEST)
    member = household.members.filter(pk=user_id).first()
    if member is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    household.members.remove(member)
    HouseholdSelection.objects.filter(user=member, household=household).delete()
    return Response(_single_household_payload(request, household))


@api_view(["GET"])
def household_members(request):
    household = get_current_household(request.user)
    if not household:
        return Response([])
    return Response(UserSerializer(household.members.all(), many=True).data)


# ── Tasks ─────────────────────────────────────────────────────────────────────

class TaskListCreateView(APIView):
    def _household(self, request):
        return get_current_household(request.user)

    def get(self, request):
        household = self._household(request)
        if not household:
            return Response([], status=status.HTTP_200_OK)
        status_filter = request.query_params.get("status")
        qs = (
            Task.objects.filter(household=household)
            .select_related("created_by")
            .prefetch_related("assigned_to")
        )
        open_tasks = list(qs.filter(status="open").order_by("due_date", "-created_at"))
        done_tasks = list(qs.filter(status="done").order_by("-due_date", "-created_at")[:DONE_TASKS_IN_LIST])
        if status_filter == "open":
            tasks = open_tasks
        elif status_filter == "done":
            tasks = done_tasks
        else:
            tasks = open_tasks + done_tasks
        return Response(TaskSerializer(tasks, many=True).data)

    def post(self, request):
        household = self._household(request)
        if not household:
            return Response({"detail": "Kein Haushalt gefunden."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = TaskSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        task = serializer.save(household=household, created_by=request.user)
        assigned = task.assigned_to.exclude(pk=request.user.pk)
        if assigned.exists():
            notify_users(assigned, "Neue Aufgabe", f"{request.user.username} hat dir „{task.title}“ zugewiesen.")
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TaskDetailView(APIView):
    def _get_task(self, request, pk):
        household = get_current_household(request.user)
        return Task.objects.get(pk=pk, household=household)

    def get(self, request, pk):
        try:
            task = self._get_task(request, pk)
        except Task.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(TaskSerializer(task).data)

    def put(self, request, pk):
        try:
            task = self._get_task(request, pk)
        except Task.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = TaskSerializer(task, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    patch = put

    def delete(self, request, pk):
        try:
            task = self._get_task(request, pk)
        except Task.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        task.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
def task_toggle(request, pk):
    household = get_current_household(request.user)
    try:
        task = Task.objects.get(pk=pk, household=household)
    except Task.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    # Neuere Apps schicken den gewünschten Status mit: mit einer veralteten
    # Liste würde blindes Umschalten sonst die Änderung eines anderen
    # rückgängig machen. Ohne "status" (ältere Apps) wird umgeschaltet.
    target = request.data.get("status") if hasattr(request.data, "get") else None
    if target in ("open", "done"):
        if task.status != target:
            task.set_status(target, request.user)
    else:
        task.toggle(request.user)
    return Response(TaskSerializer(task).data)


@api_view(["POST"])
def tasks_clear_done(request):
    """Alle erledigten Aufgaben des Haushalts löschen."""
    household = get_current_household(request.user)
    if not household:
        return Response({"deleted": 0})
    deleted, _ = Task.objects.filter(household=household, status="done").delete()
    return Response({"deleted": deleted})


# ── Meals ─────────────────────────────────────────────────────────────────────

class MealPlanListCreateView(APIView):
    def _household(self, request):
        return get_current_household(request.user)

    def get(self, request):
        household = self._household(request)
        if not household:
            return Response([])
        qs = MealPlan.objects.filter(household=household).select_related(
            "recipe", "recipe__created_by", "assigned_to"
        ).prefetch_related("recipe__ingredients")
        date_from = _parse_date(request.query_params.get("from"))
        date_to = _parse_date(request.query_params.get("to"))
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return Response(MealPlanSerializer(qs, many=True).data)

    def post(self, request):
        household = self._household(request)
        if not household:
            return Response({"detail": "Kein Haushalt gefunden."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = MealPlanSerializer(
            data=request.data, context={"request": request, "household": household}
        )
        serializer.is_valid(raise_exception=True)
        meal = serializer.save(household=household)
        notify_household(
            household, request.user, "Essensplanung",
            f"{request.user.username} hat {meal.recipe.title} am {meal.date:%d.%m.} geplant.",
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class MealPlanDetailView(APIView):
    def _get_meal(self, request, pk):
        household = get_current_household(request.user)
        return household, MealPlan.objects.get(pk=pk, household=household)

    def get(self, request, pk):
        try:
            _, meal = self._get_meal(request, pk)
        except MealPlan.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(MealPlanSerializer(meal).data)

    def put(self, request, pk):
        try:
            household, meal = self._get_meal(request, pk)
        except MealPlan.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = MealPlanSerializer(
            meal, data=request.data, partial=True,
            context={"request": request, "household": household},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    patch = put

    def delete(self, request, pk):
        try:
            _, meal = self._get_meal(request, pk)
        except MealPlan.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        meal.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Recipes ───────────────────────────────────────────────────────────────────

class RecipeListView(APIView):
    def get(self, request):
        household = get_current_household(request.user)
        if not household:
            return Response([])
        qs = Recipe.objects.filter(household=household).select_related("created_by").prefetch_related("ingredients")
        return Response(RecipeSerializer(qs, many=True).data)

    def post(self, request):
        household = get_current_household(request.user)
        if not household:
            return Response({"detail": "Kein Haushalt gefunden."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = RecipeSerializer(data=request.data, context={"household": household})
        serializer.is_valid(raise_exception=True)
        serializer.save(household=household, created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class RecipeDetailView(APIView):
    def _get_recipe(self, request, pk):
        household = get_current_household(request.user)
        return household, Recipe.objects.get(pk=pk, household=household)

    def get(self, request, pk):
        try:
            _, recipe = self._get_recipe(request, pk)
        except Recipe.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(RecipeSerializer(recipe).data)

    def put(self, request, pk):
        try:
            household, recipe = self._get_recipe(request, pk)
        except Recipe.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = RecipeSerializer(recipe, data=request.data, partial=True, context={"household": household})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    patch = put

    def delete(self, request, pk):
        try:
            _, recipe = self._get_recipe(request, pk)
        except Recipe.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        recipe.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RecipeAiSuggestView(APIView):
    throttle_scope = "ai"

    def post(self, request, pk):
        household = get_current_household(request.user)
        try:
            recipe = Recipe.objects.get(pk=pk, household=household)
        except Recipe.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if not settings.OPENAI_API_KEY:
            return Response({"error": "KI nicht konfiguriert."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not ai_quota_available(request.user):
            return Response({"error": QUOTA_MESSAGE}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        prompt = (
            f'Du bist ein Kochassistent. Erstelle genau 3 verschiedene Rezeptvarianten für "{recipe.title}". '
            'Antworte ausschließlich mit JSON: '
            '{"suggestions": [{"variant": "kurze Beschreibung (max 8 Wörter)", '
            '"ingredients": [{"name": "Zutat", "quantity": "Menge"}], '
            '"instructions": "Nummerierte Schritt-für-Schritt Zubereitung"}]}'
        )
        try:
            response = openai_client().chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.7,
            )
            return Response(json.loads(response.choices[0].message.content))
        except Exception:
            logger.exception("KI-Vorschlag fehlgeschlagen")
            return Response({"error": "KI-Vorschlag konnte nicht generiert werden."},
                            status=status.HTTP_502_BAD_GATEWAY)


recipe_ai_suggest = RecipeAiSuggestView.as_view()


@api_view(["POST"])
def recipe_apply_suggestion(request, pk):
    household = get_current_household(request.user)
    try:
        recipe = Recipe.objects.get(pk=pk, household=household)
    except Recipe.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    instructions = request.data.get("instructions", "")
    ingredients = request.data.get("ingredients", [])
    save_instructions_only = request.data.get("save_instructions_only", False)

    if not isinstance(instructions, str) or len(instructions) > 20000:
        return Response({"detail": "Ungültige Zubereitung."}, status=status.HTTP_400_BAD_REQUEST)
    if not isinstance(ingredients, list) or len(ingredients) > 50:
        return Response({"detail": "Ungültige Zutatenliste."}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        recipe.instructions = instructions
        recipe.save(update_fields=["instructions"])
        if not save_instructions_only:
            recipe.ingredients.all().delete()
            for ing in ingredients:
                if not isinstance(ing, dict):
                    continue
                name = str(ing.get("name", "")).strip()[:200]
                if name:
                    Ingredient.objects.create(
                        recipe=recipe,
                        name=name,
                        quantity=str(ing.get("quantity", "")).strip()[:100],
                    )

    return Response(RecipeSerializer(recipe).data)


class IngredientListCreateView(APIView):
    def _get_recipe(self, request, pk):
        household = get_current_household(request.user)
        return Recipe.objects.get(pk=pk, household=household)

    def post(self, request, pk):
        try:
            recipe = self._get_recipe(request, pk)
        except Recipe.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = IngredientSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(recipe=recipe)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["PUT", "PATCH", "DELETE"])
def ingredient_detail(request, pk):
    household = get_current_household(request.user)
    try:
        ingredient = Ingredient.objects.get(pk=pk, recipe__household=household)
    except Ingredient.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    if request.method == "DELETE":
        ingredient.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    serializer = IngredientSerializer(ingredient, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(["POST"])
def ingredient_to_shopping(request, pk):
    household = get_current_household(request.user)
    try:
        ingredient = Ingredient.objects.get(pk=pk, recipe__household=household)
    except Ingredient.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    existing = ShoppingItem.objects.filter(
        household=household,
        name__iexact=ingredient.name,
        is_bought=False,
    ).first()

    if existing:
        return Response({
            "status": "duplicate",
            "name": ingredient.name,
            "existing_id": existing.pk,
            "existing_quantity": existing.quantity,
            "new_quantity": ingredient.quantity,
        })

    item = ShoppingItem.objects.create(
        household=household,
        name=ingredient.name,
        quantity=ingredient.quantity,
        added_by=request.user,
    )
    return Response({"status": "added", "item": ShoppingItemSerializer(item).data}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def recipe_all_ingredients_to_shopping(request, pk):
    household = get_current_household(request.user)
    try:
        recipe = Recipe.objects.get(pk=pk, household=household)
    except Recipe.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    added, merged = shopping_services.add_ingredients(
        household, request.user, recipe.ingredients.values_list("name", "quantity")
    )
    return Response({"added": added, "merged": merged})


@api_view(["POST"])
def meals_week_to_shopping(request):
    household = get_current_household(request.user)
    if not household:
        return Response({"detail": "Kein Haushalt."}, status=status.HTTP_400_BAD_REQUEST)

    date_from = _parse_date(request.data.get("from"))
    date_to = _parse_date(request.data.get("to"))
    meals = MealPlan.objects.filter(household=household)
    if date_from:
        meals = meals.filter(date__gte=date_from)
    if date_to:
        meals = meals.filter(date__lte=date_to)
    meals = meals.select_related("recipe").prefetch_related("recipe__ingredients")
    # Jede geplante Mahlzeit zählt einzeln: zweimal Kuchen = doppelte Menge.
    ingredients = [(i.name, i.quantity) for meal in meals for i in meal.recipe.ingredients.all()]
    added, merged = shopping_services.add_ingredients(household, request.user, ingredients)
    return Response({"added": added, "merged": merged})


# ── Shopping ──────────────────────────────────────────────────────────────────

class ShoppingListCreateView(APIView):
    def _household(self, request):
        return get_current_household(request.user)

    def get(self, request):
        household = self._household(request)
        if not household:
            return Response([])
        items = list(ShoppingItem.objects.filter(household=household).select_related("added_by"))
        session = shopping_services.active_session(household)
        if session:
            unbought = [i for i in items if not i.is_bought]
            bought = [i for i in items if i.is_bought]
            items = _sort_by_store(unbought, session.store) + bought
        return Response(ShoppingItemSerializer(items, many=True).data)

    def post(self, request):
        household = self._household(request)
        if not household:
            return Response({"detail": "Kein Haushalt gefunden."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = ShoppingItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = serializer.save(household=household, added_by=request.user)
        notify_household(household, request.user, "Einkaufsliste", f"{request.user.username} hat „{item.name}“ hinzugefügt.")
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ShoppingItemDetailView(APIView):
    def _get_item(self, request, pk):
        household = get_current_household(request.user)
        return ShoppingItem.objects.get(pk=pk, household=household)

    def delete(self, request, pk):
        try:
            item = self._get_item(request, pk)
        except ShoppingItem.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
def shopping_toggle(request, pk):
    household = get_current_household(request.user)
    try:
        item = ShoppingItem.objects.get(pk=pk, household=household)
    except ShoppingItem.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    shopping_services.set_bought(household, item, not item.is_bought)
    return Response(ShoppingItemSerializer(item).data)


@api_view(["POST"])
def shopping_merge(request, pk):
    household = get_current_household(request.user)
    try:
        item = ShoppingItem.objects.get(pk=pk, household=household)
    except ShoppingItem.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    # Ältere App-Versionen schicken "extra_quantity" (wie das Web-Formular),
    # neuere "quantity" – bisher kam "extra_quantity" nie an.
    new_qty = request.data.get("quantity") or request.data.get("extra_quantity") or ""
    item.quantity = shopping_services.merge_quantity_text(item.quantity, str(new_qty))
    item.save(update_fields=["quantity"])
    return Response(ShoppingItemSerializer(item).data)


@api_view(["POST"])
def shopping_clear_bought(request):
    household = get_current_household(request.user)
    if not household:
        return Response({"removed": 0})
    return Response({"removed": shopping_services.clear_bought(household)})


@api_view(["POST"])
def shopping_sync(request):
    """Offline-Synchronisation der App, siehe shopping/sync.py."""
    try:
        household_id = int(request.data.get("household_id"))
    except (TypeError, ValueError):
        return Response({"detail": "household_id fehlt."}, status=status.HTTP_400_BAD_REQUEST)
    household = request.user.households.filter(pk=household_id).first()
    if household is None:
        return Response({"detail": "Du bist kein Mitglied dieses Haushalts."},
                        status=status.HTTP_403_FORBIDDEN)
    ops = request.data.get("ops", [])
    if not isinstance(ops, list) or len(ops) > MAX_OPS_PER_REQUEST:
        return Response({"detail": f"ops muss eine Liste mit höchstens {MAX_OPS_PER_REQUEST} Einträgen sein."},
                        status=status.HTTP_400_BAD_REQUEST)

    results, summary = apply_ops(household, request.user, ops)
    added = summary["added"]
    if added:
        if len(added) == 1:
            body = f"{request.user.username} hat „{added[0]}“ hinzugefügt."
        else:
            names = ", ".join(added[:5]) + (" …" if len(added) > 5 else "")
            body = f"{request.user.username} hat {len(added)} Artikel hinzugefügt: {names}"
        notify_household(household, request.user, "Einkaufsliste", body)

    state = snapshot(household)
    return Response({
        "household_id": household.pk,
        "results": results,
        "items": ShoppingItemSerializer(state["items"], many=True).data,
        "session": ShoppingSessionSerializer(state["session"]).data if state["session"] else None,
        "stores": [
            dict(StoreSerializer(store).data, item_order=order)
            for store, order in state["stores"]
        ],
        "suggestions": state["suggestions"],
        "server_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })


# ── Stores & Shopping Session ─────────────────────────────────────────────────

class StoreListCreateView(APIView):
    def get(self, request):
        household = get_current_household(request.user)
        if not household:
            return Response([])
        stores = Store.objects.filter(household=household)
        return Response(StoreSerializer(stores, many=True).data)

    def post(self, request):
        household = get_current_household(request.user)
        if not household:
            return Response({"detail": "Kein Haushalt gefunden."}, status=status.HTTP_400_BAD_REQUEST)
        name = (request.data.get("name") or "").strip()
        location = (request.data.get("location") or "").strip()
        if not name:
            return Response({"detail": "Name erforderlich."}, status=status.HTTP_400_BAD_REQUEST)
        if len(name) > 200 or len(location) > 200:
            return Response({"detail": "Name und Ort dürfen höchstens 200 Zeichen lang sein."},
                            status=status.HTTP_400_BAD_REQUEST)
        store, _ = Store.objects.get_or_create(household=household, name=name, location=location)
        return Response(StoreSerializer(store).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def shopping_session_active(request):
    household = get_current_household(request.user)
    if not household:
        return Response(None)
    session = shopping_services.active_session(household)
    if not session:
        return Response(None)
    return Response(ShoppingSessionSerializer(session).data)


@api_view(["POST"])
def shopping_start(request):
    household = get_current_household(request.user)
    if not household:
        return Response({"detail": "Kein Haushalt gefunden."}, status=status.HTTP_400_BAD_REQUEST)

    if shopping_services.active_session(household):
        return Response({"detail": "Es läuft bereits eine Einkaufs-Session."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        store = Store.objects.get(pk=int(request.data.get("store_id")), household=household)
    except (TypeError, ValueError, Store.DoesNotExist):
        return Response({"detail": "Supermarkt nicht gefunden."}, status=status.HTTP_404_NOT_FOUND)

    session = ShoppingSession.objects.create(household=household, store=store, started_by=request.user)
    return Response(ShoppingSessionSerializer(session).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def shopping_end(request):
    household = get_current_household(request.user)
    if not household:
        return Response({"detail": "Kein Haushalt gefunden."}, status=status.HTTP_400_BAD_REQUEST)
    if not shopping_services.active_session(household):
        return Response({"detail": "Keine aktive Session."}, status=status.HTTP_400_BAD_REQUEST)
    _, removed = shopping_services.finish_shopping(household)
    return Response({"detail": "Einkauf beendet.", "removed": removed})
