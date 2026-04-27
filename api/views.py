import json

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from households.models import Household
from households.utils import get_current_household, merge_quantities
from meals.models import MealPlan, Recipe
from shopping.models import ShoppingItem, Store, ShoppingSession, StoreItemOrder
from tasks.models import Task

from .serializers import (
    HouseholdSerializer,
    IngredientSerializer,
    MealPlanSerializer,
    RecipeSerializer,
    RegisterSerializer,
    ShoppingItemSerializer,
    ShoppingSessionSerializer,
    StoreSerializer,
    TaskSerializer,
    UserSerializer,
)

User = get_user_model()


# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


# ── Households ────────────────────────────────────────────────────────────────

class HouseholdListView(APIView):
    def get(self, request):
        households = request.user.households.all()
        return Response(HouseholdSerializer(households, many=True).data)

    def post(self, request):
        name = request.data.get("name", "").strip()
        if not name:
            return Response({"detail": "Name erforderlich."}, status=status.HTTP_400_BAD_REQUEST)
        household = Household.objects.create(name=name)
        household.members.add(request.user)
        return Response(HouseholdSerializer(household).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def join_household(request, pk):
    try:
        household = Household.objects.get(pk=pk)
    except Household.DoesNotExist:
        return Response({"detail": "Haushalt nicht gefunden."}, status=status.HTTP_404_NOT_FOUND)
    household.members.add(request.user)
    return Response(HouseholdSerializer(household).data)


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
        qs = Task.objects.filter(household=household).select_related("created_by").prefetch_related("assigned_to")
        if status_filter in ("open", "done"):
            qs = qs.filter(status=status_filter)
        return Response(TaskSerializer(qs, many=True).data)

    def post(self, request):
        household = self._household(request)
        if not household:
            return Response({"detail": "Kein Haushalt gefunden."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = TaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(household=household, created_by=request.user)
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
        serializer = TaskSerializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

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
    task.status = "done" if task.status == "open" else "open"
    task.save()
    return Response(TaskSerializer(task).data)


# ── Meals ─────────────────────────────────────────────────────────────────────

class MealPlanListCreateView(APIView):
    def _household(self, request):
        return get_current_household(request.user)

    def get(self, request):
        household = self._household(request)
        if not household:
            return Response([])
        qs = MealPlan.objects.filter(household=household).select_related("recipe", "assigned_to")
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return Response(MealPlanSerializer(qs, many=True, context={"request": request}).data)

    def post(self, request):
        household = self._household(request)
        if not household:
            return Response({"detail": "Kein Haushalt gefunden."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = MealPlanSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(household=household)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class MealPlanDetailView(APIView):
    def _get_meal(self, request, pk):
        household = get_current_household(request.user)
        return MealPlan.objects.get(pk=pk, household=household)

    def get(self, request, pk):
        try:
            meal = self._get_meal(request, pk)
        except MealPlan.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(MealPlanSerializer(meal, context={"request": request}).data)

    def put(self, request, pk):
        try:
            meal = self._get_meal(request, pk)
        except MealPlan.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = MealPlanSerializer(meal, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        try:
            meal = self._get_meal(request, pk)
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
        qs = Recipe.objects.filter(household=household).prefetch_related("ingredients")
        return Response(RecipeSerializer(qs, many=True).data)

    def post(self, request):
        household = get_current_household(request.user)
        if not household:
            return Response({"detail": "Kein Haushalt gefunden."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = RecipeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(household=household, created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class RecipeDetailView(APIView):
    def _get_recipe(self, request, pk):
        household = get_current_household(request.user)
        return Recipe.objects.get(pk=pk, household=household)

    def get(self, request, pk):
        try:
            recipe = self._get_recipe(request, pk)
        except Recipe.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(RecipeSerializer(recipe).data)

    def put(self, request, pk):
        try:
            recipe = self._get_recipe(request, pk)
        except Recipe.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = RecipeSerializer(recipe, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        try:
            recipe = self._get_recipe(request, pk)
        except Recipe.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        recipe.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
def recipe_ai_suggest(request, pk):
    household = get_current_household(request.user)
    try:
        recipe = Recipe.objects.get(pk=pk, household=household)
    except Recipe.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        return Response({"error": "KI nicht konfiguriert."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        prompt = (
            f'Du bist ein Kochassistent. Erstelle genau 3 verschiedene Rezeptvarianten für "{recipe.title}". '
            'Antworte ausschließlich mit JSON: '
            '{"suggestions": [{"variant": "kurze Beschreibung (max 8 Wörter)", '
            '"ingredients": [{"name": "Zutat", "quantity": "Menge"}], '
            '"instructions": "Nummerierte Schritt-für-Schritt Zubereitung"}]}'
        )
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        return Response(json.loads(response.choices[0].message.content))
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
def recipe_apply_suggestion(request, pk):
    household = get_current_household(request.user)
    try:
        recipe = Recipe.objects.get(pk=pk, household=household)
    except Recipe.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    from meals.models import Ingredient
    instructions = request.data.get("instructions", "")
    ingredients = request.data.get("ingredients", [])
    save_instructions_only = request.data.get("save_instructions_only", False)

    recipe.instructions = instructions
    recipe.save()

    if not save_instructions_only:
        recipe.ingredients.all().delete()
        for ing in ingredients:
            Ingredient.objects.create(
                recipe=recipe,
                name=ing.get("name", ""),
                quantity=ing.get("quantity", ""),
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


@api_view(["DELETE"])
def ingredient_delete(request, pk):
    from meals.models import Ingredient
    household = get_current_household(request.user)
    try:
        ingredient = Ingredient.objects.get(pk=pk, recipe__household=household)
    except Ingredient.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    ingredient.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
def ingredient_to_shopping(request, pk):
    from meals.models import Ingredient
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
            "existing": ShoppingItemSerializer(existing).data,
            "ingredient": IngredientSerializer(ingredient).data,
        })

    item = ShoppingItem.objects.create(
        household=household,
        name=ingredient.name,
        quantity=ingredient.quantity,
        added_by=request.user,
    )
    return Response({"status": "added", "item": ShoppingItemSerializer(item).data}, status=status.HTTP_201_CREATED)


# ── Shopping ──────────────────────────────────────────────────────────────────

def _active_session(household):
    return ShoppingSession.objects.filter(household=household, ended_at__isnull=True).first()


def _sort_by_store(items, store):
    orders = {
        o.item_name: o.avg_position
        for o in StoreItemOrder.objects.filter(store=store)
    }
    known, unknown = [], []
    for item in items:
        key = item.name.lower().strip()
        if key in orders:
            known.append((orders[key], item))
        else:
            unknown.append(item)
    known.sort(key=lambda x: x[0])
    return [item for _, item in known] + unknown


class ShoppingListCreateView(APIView):
    def _household(self, request):
        return get_current_household(request.user)

    def get(self, request):
        household = self._household(request)
        if not household:
            return Response([])
        items = list(ShoppingItem.objects.filter(household=household).select_related("added_by"))
        session = _active_session(household)
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
        serializer.save(household=household, added_by=request.user)
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
    item.is_bought = not item.is_bought
    item.save()
    if item.is_bought:
        session = _active_session(household)
        if session:
            session.check_counter += 1
            session.save()
            order, _ = StoreItemOrder.objects.get_or_create(
                store=session.store,
                item_name=item.name.lower().strip(),
            )
            order.record(session.check_counter)
    return Response(ShoppingItemSerializer(item).data)


@api_view(["POST"])
def shopping_merge(request, pk):
    household = get_current_household(request.user)
    try:
        item = ShoppingItem.objects.get(pk=pk, household=household)
    except ShoppingItem.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    new_qty = request.data.get("quantity", "")
    item.quantity = merge_quantities(item.quantity, new_qty)
    item.save()
    return Response(ShoppingItemSerializer(item).data)


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
        name = request.data.get("name", "").strip()
        location = request.data.get("location", "").strip()
        if not name:
            return Response({"detail": "Name erforderlich."}, status=status.HTTP_400_BAD_REQUEST)
        store, _ = Store.objects.get_or_create(household=household, name=name, location=location)
        return Response(StoreSerializer(store).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def shopping_session_active(request):
    household = get_current_household(request.user)
    if not household:
        return Response(None)
    session = _active_session(household)
    if not session:
        return Response(None)
    return Response(ShoppingSessionSerializer(session).data)


@api_view(["POST"])
def shopping_start(request):
    household = get_current_household(request.user)
    if not household:
        return Response({"detail": "Kein Haushalt gefunden."}, status=status.HTTP_400_BAD_REQUEST)

    if _active_session(household):
        return Response({"detail": "Es läuft bereits eine Einkaufs-Session."}, status=status.HTTP_400_BAD_REQUEST)

    store_id = request.data.get("store_id")
    try:
        store = Store.objects.get(pk=store_id, household=household)
    except Store.DoesNotExist:
        return Response({"detail": "Supermarkt nicht gefunden."}, status=status.HTTP_404_NOT_FOUND)

    session = ShoppingSession.objects.create(household=household, store=store, started_by=request.user)
    return Response(ShoppingSessionSerializer(session).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def shopping_end(request):
    household = get_current_household(request.user)
    if not household:
        return Response({"detail": "Kein Haushalt gefunden."}, status=status.HTTP_400_BAD_REQUEST)
    session = _active_session(household)
    if not session:
        return Response({"detail": "Keine aktive Session."}, status=status.HTTP_400_BAD_REQUEST)
    session.end()
    return Response({"detail": "Einkauf beendet."})
