# Meals AI Recipe Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dashboard-linked page that turns a list of pantry ingredients into 3 OpenAI-generated recipe suggestions, one of which the user can save as a regular `Recipe` (with `Ingredient`s).

**Architecture:** Three Django views in `meals/` (form GET, suggest POST→JSON via `gpt-4o-mini`, save POST→JSON+redirect). One new util for autocomplete. One template with vanilla-JS tag-input + AJAX. A new card on `templates/home.html`. Mocks all OpenAI calls in tests.

**Tech Stack:** Django 6, Bootstrap 5.3, OpenAI Python SDK (already pinned in `requirements.txt`), `unittest.mock` for tests, vanilla JS for tag-input (no framework).

**Reference spec:** `docs/superpowers/specs/2026-05-26-meals-ai-recipe-generator-design.md`.

---

## Task 1: Autocomplete-Util (`get_ingredient_autocomplete`)

**Files:**
- Create: `meals/utils.py`
- Modify: `meals/tests.py` (append new test class)

- [ ] **Step 1.1: Write the failing test**

Append to `meals/tests.py` (create the file with imports if it does not exist; check first with `cat meals/tests.py`):

```python
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from households.models import Household
from meals.models import Recipe, Ingredient
from shopping.models import ShoppingItem

User = get_user_model()


class IngredientAutocompleteUtilTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="autoco", password="pw123456")
        self.household = Household.objects.create(name="Casa")
        self.household.members.add(self.user)

    def test_autocomplete_dedupes_case_insensitive_across_sources(self):
        recipe = Recipe.objects.create(household=self.household, title="R", created_by=self.user)
        Ingredient.objects.create(recipe=recipe, name="Tomaten", quantity="200g")
        Ingredient.objects.create(recipe=recipe, name="Reis", quantity="200g")
        ShoppingItem.objects.create(household=self.household, name="tomaten", added_by=self.user)
        ShoppingItem.objects.create(household=self.household, name="Hähnchen", added_by=self.user)

        from meals.utils import get_ingredient_autocomplete
        result = get_ingredient_autocomplete(self.household)

        self.assertEqual(sorted(result), ["Hähnchen", "Reis", "Tomaten"])

    def test_autocomplete_scoped_to_household(self):
        other = Household.objects.create(name="Other")
        other_user = User.objects.create_user(username="other", password="pw123456")
        other.members.add(other_user)
        other_recipe = Recipe.objects.create(household=other, title="X", created_by=other_user)
        Ingredient.objects.create(recipe=other_recipe, name="DoNotShow", quantity="")

        from meals.utils import get_ingredient_autocomplete
        result = get_ingredient_autocomplete(self.household)

        self.assertNotIn("DoNotShow", result)
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
DEBUG=True .venv/bin/python manage.py test meals.tests.IngredientAutocompleteUtilTest -v 2
```
Expected: ImportError or `ModuleNotFoundError: No module named 'meals.utils'`.

- [ ] **Step 1.3: Write minimal implementation**

Create `meals/utils.py`:

```python
from meals.models import Ingredient
from shopping.models import ShoppingItem


def get_ingredient_autocomplete(household) -> list[str]:
    """Return alpha-sorted, case-insensitively deduped ingredient names
    (from Ingredient + ShoppingItem) scoped to the given household."""
    recipe_names = Ingredient.objects.filter(
        recipe__household=household
    ).values_list("name", flat=True)
    shopping_names = ShoppingItem.objects.filter(
        household=household
    ).values_list("name", flat=True)

    seen_lower: set[str] = set()
    out: list[str] = []
    for raw in list(recipe_names) + list(shopping_names):
        name = (raw or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        out.append(name)
    out.sort(key=str.lower)
    return out
```

- [ ] **Step 1.4: Run test to verify it passes**

```bash
DEBUG=True .venv/bin/python manage.py test meals.tests.IngredientAutocompleteUtilTest -v 2
```
Expected: `Ran 2 tests in ... s` `OK`.

- [ ] **Step 1.5: Commit**

```bash
git add meals/utils.py meals/tests.py
git commit -m "feat(meals): add household-scoped ingredient autocomplete util"
```

---

## Task 2: URL routing (3 new paths)

**Files:**
- Modify: `meals/urls.py`

The views referenced here are added in Tasks 3–5; we wire URLs first so they can fail with `ImproperlyConfigured` until the views are added. After Task 5 the routing test passes.

- [ ] **Step 2.1: Write the failing routing test**

Append to `meals/tests.py`:

```python
from django.urls import reverse


class AIGeneratorRoutingTest(TestCase):
    def test_urls_resolve(self):
        self.assertEqual(reverse("ai_generator_form"), "/meals/ai-generator/")
        self.assertEqual(reverse("ai_generator_suggest"), "/meals/ai-generator/suggest/")
        self.assertEqual(reverse("ai_generator_save"), "/meals/ai-generator/save/")
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
DEBUG=True .venv/bin/python manage.py test meals.tests.AIGeneratorRoutingTest -v 2
```
Expected: `NoReverseMatch`.

- [ ] **Step 2.3: Add the URL patterns (still no views — will continue to fail at server-start, but routing test will pass once views exist)**

Edit `meals/urls.py`:

```python
from django.urls import path
from .views import (
    meal_list, meal_history, meal_create, meal_update, meal_delete,
    meals_week_to_shopping,
    recipe_list, recipe_create, recipe_update, recipe_delete, recipe_detail,
    recipe_all_to_shopping,
    ingredient_add, ingredient_delete, ingredient_scale, ingredient_to_shopping,
    shopping_merge_quantity,
    recipe_ai_suggest, recipe_apply_suggestion,
    recipe_generate_image, recipe_upload_image,
    ai_generator_form, ai_generator_suggest, ai_generator_save,
)

urlpatterns = [
    path("", meal_list, name="meal_list"),
    path("history/", meal_history, name="meal_history"),
    path("to-shopping/", meals_week_to_shopping, name="meals_week_to_shopping"),
    path("new/", meal_create, name="meal_create"),
    path("<int:pk>/edit/", meal_update, name="meal_update"),
    path("<int:pk>/delete/", meal_delete, name="meal_delete"),

    path("recipes/", recipe_list, name="recipe_list"),
    path("recipes/new/", recipe_create, name="recipe_create"),
    path("recipes/<int:pk>/", recipe_detail, name="recipe_detail"),
    path("recipes/<int:pk>/edit/", recipe_update, name="recipe_update"),
    path("recipes/<int:pk>/delete/", recipe_delete, name="recipe_delete"),
    path("recipes/<int:pk>/ingredients/add/", ingredient_add, name="ingredient_add"),
    path("ingredients/<int:pk>/to-shopping/", ingredient_to_shopping, name="ingredient_to_shopping"),
    path("ingredients/<int:pk>/delete/", ingredient_delete, name="ingredient_delete"),
    path("ingredients/<int:pk>/scale/", ingredient_scale, name="ingredient_scale"),
    path("shopping/<int:pk>/merge/", shopping_merge_quantity, name="shopping_merge_quantity"),
    path("recipes/<int:pk>/all-to-shopping/", recipe_all_to_shopping, name="recipe_all_to_shopping"),
    path("recipes/<int:pk>/ai-suggest/", recipe_ai_suggest, name="recipe_ai_suggest"),
    path("recipes/<int:pk>/apply-suggestion/", recipe_apply_suggestion, name="recipe_apply_suggestion"),
    path("recipes/<int:pk>/generate-image/", recipe_generate_image, name="recipe_generate_image"),
    path("recipes/<int:pk>/upload-image/", recipe_upload_image, name="recipe_upload_image"),

    path("ai-generator/", ai_generator_form, name="ai_generator_form"),
    path("ai-generator/suggest/", ai_generator_suggest, name="ai_generator_suggest"),
    path("ai-generator/save/", ai_generator_save, name="ai_generator_save"),
]
```

(Server cannot start yet because the 3 view symbols are undefined — that's fine; tests run because routing test fails at import time without affecting other test classes. If `meals.urls` fails to import at all, the import errors will surface in Task 3.)

- [ ] **Step 2.4: Defer commit until Task 3 (views exist).**

Reason: committing URL with non-existent symbols leaves the working tree in a broken state. We commit the URL + the first view together at the end of Task 3.

---

## Task 3: `ai_generator_form` GET view + template skeleton

**Files:**
- Modify: `meals/views.py` (add the view)
- Create: `templates/meals/ai_generator.html` (skeleton, full UI in Task 6)

- [ ] **Step 3.1: Write the failing test**

Append to `meals/tests.py`:

```python
class AIGeneratorFormTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="formgen", password="pw123456")
        self.household = Household.objects.create(name="Casa")
        self.household.members.add(self.user)
        self.client.login(username="formgen", password="pw123456")

    def test_form_get_requires_login(self):
        self.client.logout()
        response = self.client.get("/meals/ai-generator/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_form_get_renders_when_household_exists(self):
        response = self.client.get("/meals/ai-generator/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Was koche ich")

    def test_form_get_redirects_without_household(self):
        # Remove membership
        self.household.members.clear()
        response = self.client.get("/meals/ai-generator/")
        self.assertEqual(response.status_code, 302)
```

- [ ] **Step 3.2: Run test to verify it fails**

```bash
DEBUG=True .venv/bin/python manage.py test meals.tests.AIGeneratorFormTest -v 2
```
Expected: ImportError on `ai_generator_form` from `meals.views`.

- [ ] **Step 3.3: Add the three view stubs in `meals/views.py`**

Append to `meals/views.py` (the `suggest` and `save` get replaced in Tasks 4–5 — for now they only need to exist as importable symbols so `meals/urls.py` imports succeed):

```python
@login_required
def ai_generator_form(request):
    household = get_current_household(request.user)
    if not household:
        return redirect("choose_household")
    from .utils import get_ingredient_autocomplete
    return render(request, "meals/ai_generator.html", {
        "household": household,
        "autocomplete": get_ingredient_autocomplete(household),
        "default_portions": max(household.members.count(), 2),
    })


@login_required
def ai_generator_suggest(request):
    return JsonResponse({"error": "not implemented yet"}, status=501)


@login_required
def ai_generator_save(request):
    return JsonResponse({"error": "not implemented yet"}, status=501)
```

- [ ] **Step 3.4: Create the minimal template**

Create `templates/meals/ai_generator.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:880px">
    <a href="{% url 'meal_list' %}" class="text-decoration-none small text-muted">← zurück</a>
    <h1 class="h3 mt-2">Was koche ich? 🍳</h1>
    <p class="text-muted">Gib Zutaten ein, AI schlägt 3 Rezepte vor.</p>
    {# Full UI added in Task 6 #}
</div>
{% endblock %}
```

- [ ] **Step 3.5: Run all meals tests to verify**

```bash
DEBUG=True .venv/bin/python manage.py test meals.tests.AIGeneratorFormTest meals.tests.AIGeneratorRoutingTest meals.tests.IngredientAutocompleteUtilTest -v 2
```
Expected: 6 tests, all OK.

- [ ] **Step 3.6: Commit URL + view stubs together**

```bash
git add meals/urls.py meals/views.py templates/meals/ai_generator.html meals/tests.py
git commit -m "feat(meals): wire AI generator URLs and form GET view"
```

---

## Task 4: `ai_generator_suggest` POST view (mocked OpenAI)

**Files:**
- Modify: `meals/views.py` (replace stub with real implementation)
- Modify: `meals/tests.py` (append tests)

- [ ] **Step 4.1: Write the failing tests**

Append to `meals/tests.py`:

```python
from unittest.mock import patch, MagicMock
import json


class AIGeneratorSuggestTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="suggester", password="pw123456")
        self.household = Household.objects.create(name="Casa")
        self.household.members.add(self.user)
        self.client.login(username="suggester", password="pw123456")

    def _post(self, **payload):
        return self.client.post(
            "/meals/ai-generator/suggest/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_suggest_requires_post(self):
        response = self.client.get("/meals/ai-generator/suggest/")
        self.assertEqual(response.status_code, 405)

    def test_suggest_rejects_empty_ingredients(self):
        response = self._post(ingredients=[], portions=2, filters=[])
        self.assertEqual(response.status_code, 400)
        self.assertIn("Mindestens", response.json()["error"])

    def test_suggest_rejects_too_many_ingredients(self):
        ingredients = [f"zutat{i}" for i in range(31)]
        response = self._post(ingredients=ingredients, portions=2, filters=[])
        self.assertEqual(response.status_code, 400)
        self.assertIn("Maximal 30", response.json()["error"])

    def test_suggest_rejects_invalid_portions(self):
        response = self._post(ingredients=["a"], portions=0, filters=[])
        self.assertEqual(response.status_code, 400)
        response = self._post(ingredients=["a"], portions=51, filters=[])
        self.assertEqual(response.status_code, 400)

    @patch("meals.views.settings")
    def test_suggest_missing_api_key_returns_503(self, mock_settings):
        mock_settings.OPENAI_API_KEY = ""
        response = self._post(ingredients=["reis"], portions=2, filters=[])
        self.assertEqual(response.status_code, 503)

    @patch("meals.views.OpenAI")
    @patch("meals.views.settings")
    def test_suggest_happy_path_returns_three(self, mock_settings, mock_openai_cls):
        mock_settings.OPENAI_API_KEY = "test-key"
        fake_payload = {
            "suggestions": [
                {"title": f"R{i}", "duration_min": 20, "ingredients": [{"name": "Reis", "quantity": "200g"}], "instructions": "1. ..."}
                for i in range(3)
            ]
        }
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps(fake_payload)
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_openai_cls.return_value.chat.completions.create.return_value = mock_response

        response = self._post(ingredients=["reis", "huhn"], portions=2, filters=["vegetarisch"])
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["suggestions"]), 3)
        self.assertEqual(data["suggestions"][0]["title"], "R0")

    @patch("meals.views.OpenAI")
    @patch("meals.views.settings")
    def test_suggest_rejects_malformed_ai_response(self, mock_settings, mock_openai_cls):
        mock_settings.OPENAI_API_KEY = "test-key"
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps({"suggestions": [{"title": "only-one"}]})
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_openai_cls.return_value.chat.completions.create.return_value = mock_response

        response = self._post(ingredients=["reis"], portions=2, filters=[])
        self.assertEqual(response.status_code, 502)
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
DEBUG=True .venv/bin/python manage.py test meals.tests.AIGeneratorSuggestTest -v 2
```
Expected: All 7 fail (501 from stub instead of expected codes).

- [ ] **Step 4.3: Add top-level imports to `meals/views.py`**

Edit `meals/views.py` and ensure these imports exist near the top (add only those missing):

```python
import json
from django.conf import settings
from django.http import JsonResponse, HttpResponseNotAllowed
```

Add (next to the existing OpenAI usage) a module-level import. Keep the existing inline `from openai import OpenAI` in `recipe_ai_suggest` to avoid touching that view, BUT add a module-level alias so the tests can `@patch("meals.views.OpenAI")`:

```python
try:
    from openai import OpenAI  # exposed at module-level for test patching
except ImportError:  # pragma: no cover
    OpenAI = None
```

- [ ] **Step 4.4: Replace the `ai_generator_suggest` stub with the real implementation**

In `meals/views.py`, replace:

```python
@login_required
def ai_generator_suggest(request):
    return JsonResponse({"error": "not implemented yet"}, status=501)
```

with:

```python
@login_required
def ai_generator_suggest(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Ungültiges JSON."}, status=400)

    ingredients = [str(x).strip() for x in (payload.get("ingredients") or []) if str(x).strip()]
    if not ingredients:
        return JsonResponse({"error": "Mindestens 1 Zutat angeben."}, status=400)
    if len(ingredients) > 30:
        return JsonResponse({"error": "Maximal 30 Zutaten."}, status=400)

    try:
        portions = int(payload.get("portions") or 2)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Portionen müssen eine Zahl sein."}, status=400)
    if not (1 <= portions <= 50):
        return JsonResponse({"error": "Portionen müssen zwischen 1 und 50 liegen."}, status=400)

    filters = [str(f).strip().lower() for f in (payload.get("filters") or []) if str(f).strip()]

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        return JsonResponse({"error": "Kein OpenAI API-Key konfiguriert."}, status=503)

    ingredients_csv = ", ".join(ingredients)
    filter_csv = ", ".join(filters) if filters else "keine"
    prompt = (
        f"Du bist Kochassistent. User hat folgende Zutaten zur Verfügung: {ingredients_csv}.\n"
        f"Erstelle genau 3 verschiedene Rezeptvorschläge für {portions} Portion(en).\n"
        f"Filter (falls aktiv): {filter_csv}.\n\n"
        "Regeln:\n"
        "- Nutze möglichst nur die genannten Zutaten. Übliche Pantry-Items (Salz, Pfeffer, Öl, Wasser) darfst du ergänzen.\n"
        "- Bei Filter 'vegetarisch': kein Fleisch/Fisch.\n"
        "- Bei Filter 'vegan': zusätzlich keine tierischen Produkte.\n"
        "- Bei Filter 'glutenfrei': kein Weizen/Roggen/Gerste.\n"
        "- Bei Filter 'schnell': Zubereitung max 30 Minuten.\n\n"
        "Antworte ausschließlich mit folgendem JSON:\n"
        "{\n"
        '  "suggestions": [\n'
        '    {\n'
        '      "title": "Kurzer prägnanter Rezeptname",\n'
        '      "duration_min": 25,\n'
        '      "ingredients": [{"name": "Hähnchenbrust", "quantity": "300g"}],\n'
        '      "instructions": "1. Reis aufsetzen.\\n2. ..."\n'
        '    }\n'
        '  ]\n'
        "}\n"
        "Genau 3 Vorschläge. Mengen in deutscher Notation (g, ml, EL, TL, Stück)."
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        data = json.loads(response.choices[0].message.content)
    except Exception as e:
        try:
            from openai import RateLimitError
            if isinstance(e, RateLimitError):
                return JsonResponse({"error": "Aktuell sind keine Rezeptvorschläge verfügbar."}, status=429)
        except ImportError:
            pass
        return JsonResponse({"error": str(e)}, status=500)

    suggestions = data.get("suggestions") or []
    if len(suggestions) != 3:
        return JsonResponse({"error": "AI-Antwort unbrauchbar, bitte erneut versuchen."}, status=502)
    for s in suggestions:
        if not (s.get("title") and isinstance(s.get("ingredients"), list) and s.get("instructions")):
            return JsonResponse({"error": "AI-Antwort unbrauchbar, bitte erneut versuchen."}, status=502)

    return JsonResponse({"suggestions": suggestions})
```

- [ ] **Step 4.5: Run tests to verify they pass**

```bash
DEBUG=True .venv/bin/python manage.py test meals.tests.AIGeneratorSuggestTest -v 2
```
Expected: 7 tests, all OK.

- [ ] **Step 4.6: Commit**

```bash
git add meals/views.py meals/tests.py
git commit -m "feat(meals): AI suggest endpoint with validation and mocked tests"
```

---

## Task 5: `ai_generator_save` POST view (incl. title-collision suffix)

**Files:**
- Modify: `meals/views.py` (replace stub)
- Modify: `meals/tests.py` (append tests)

- [ ] **Step 5.1: Write the failing tests**

Append to `meals/tests.py`:

```python
class AIGeneratorSaveTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="saver", password="pw123456")
        self.household = Household.objects.create(name="Casa")
        self.household.members.add(self.user)
        self.client.login(username="saver", password="pw123456")

    def _payload(self, **overrides):
        payload = {
            "title": "Hähnchen-Reis-Pfanne",
            "duration_min": 25,
            "ingredients": [
                {"name": "Hähnchen", "quantity": "300g"},
                {"name": "Reis", "quantity": "200g"},
            ],
            "instructions": "1. Reis aufsetzen.\n2. Hähnchen anbraten.",
        }
        payload.update(overrides)
        return payload

    def _post(self, payload):
        return self.client.post(
            "/meals/ai-generator/save/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_save_requires_post(self):
        response = self.client.get("/meals/ai-generator/save/")
        self.assertEqual(response.status_code, 405)

    def test_save_requires_household(self):
        self.household.members.clear()
        response = self._post(self._payload())
        self.assertEqual(response.status_code, 400)

    def test_save_rejects_empty_title(self):
        response = self._post(self._payload(title=""))
        self.assertEqual(response.status_code, 400)

    def test_save_creates_recipe_and_ingredients(self):
        response = self._post(self._payload())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        recipe = Recipe.objects.get(pk=body["recipe_id"])
        self.assertEqual(recipe.household, self.household)
        self.assertEqual(recipe.created_by, self.user)
        self.assertEqual(recipe.title, "Hähnchen-Reis-Pfanne")
        self.assertIn("~25 min", recipe.notes)
        self.assertEqual(recipe.ingredients.count(), 2)
        self.assertEqual(body["redirect_url"], f"/meals/recipes/{recipe.pk}/")

    def test_save_collision_appends_suffix(self):
        Recipe.objects.create(household=self.household, title="Hähnchen-Reis-Pfanne", created_by=self.user)
        response = self._post(self._payload())
        self.assertEqual(response.status_code, 200)
        recipe = Recipe.objects.get(pk=response.json()["recipe_id"])
        self.assertEqual(recipe.title, "Hähnchen-Reis-Pfanne (2)")

    def test_save_collision_walks_to_three(self):
        Recipe.objects.create(household=self.household, title="Hähnchen-Reis-Pfanne", created_by=self.user)
        Recipe.objects.create(household=self.household, title="Hähnchen-Reis-Pfanne (2)", created_by=self.user)
        response = self._post(self._payload())
        recipe = Recipe.objects.get(pk=response.json()["recipe_id"])
        self.assertEqual(recipe.title, "Hähnchen-Reis-Pfanne (3)")
```

- [ ] **Step 5.2: Run tests to verify they fail**

```bash
DEBUG=True .venv/bin/python manage.py test meals.tests.AIGeneratorSaveTest -v 2
```
Expected: All 6 fail (501 from stub).

- [ ] **Step 5.3: Replace the `ai_generator_save` stub**

In `meals/views.py`, replace the stub with:

```python
@login_required
def ai_generator_save(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    household = get_current_household(request.user)
    if not household:
        return JsonResponse({"error": "Kein Haushalt aktiv."}, status=400)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Ungültiges JSON."}, status=400)

    title = (payload.get("title") or "").strip()
    if not title:
        return JsonResponse({"error": "Titel fehlt."}, status=400)

    instructions = (payload.get("instructions") or "").strip()
    duration_min = payload.get("duration_min")
    notes_bits = []
    if duration_min:
        notes_bits.append(f"~{duration_min} min")
    notes_bits.append("per AI generiert")
    notes = " · ".join(notes_bits)

    # Title-collision: append " (2)", " (3)", … until unique within household.
    final_title = title
    counter = 2
    while Recipe.objects.filter(household=household, title=final_title).exists():
        final_title = f"{title} ({counter})"
        counter += 1

    recipe = Recipe.objects.create(
        household=household,
        title=final_title,
        notes=notes,
        instructions=instructions,
        created_by=request.user,
    )

    ingredients_payload = payload.get("ingredients") or []
    Ingredient.objects.bulk_create([
        Ingredient(recipe=recipe, name=(i.get("name") or "").strip(), quantity=(i.get("quantity") or "").strip())
        for i in ingredients_payload if (i.get("name") or "").strip()
    ])

    return JsonResponse({
        "recipe_id": recipe.pk,
        "redirect_url": f"/meals/recipes/{recipe.pk}/",
    })
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
DEBUG=True .venv/bin/python manage.py test meals.tests.AIGeneratorSaveTest -v 2
```
Expected: 6 tests, all OK.

- [ ] **Step 5.5: Run full meals test suite to confirm no regressions**

```bash
DEBUG=True .venv/bin/python manage.py test meals -v 2
```
Expected: all OK.

- [ ] **Step 5.6: Commit**

```bash
git add meals/views.py meals/tests.py
git commit -m "feat(meals): AI generator save endpoint with title-collision suffix"
```

---

## Task 6: Generator template — full UI (form + tag-input + AJAX result area)

**Files:**
- Modify: `templates/meals/ai_generator.html`

No new unit tests: existing `AIGeneratorFormTest` covers GET-render. We will verify by manual smoke at end of Task 8.

- [ ] **Step 6.1: Replace the template content**

Overwrite `templates/meals/ai_generator.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:880px">
    <a href="{% url 'meal_list' %}" class="text-decoration-none small text-muted">← zurück</a>
    <h1 class="h3 mt-2">Was koche ich? 🍳</h1>
    <p class="text-muted">Gib Zutaten ein, AI schlägt 3 Rezepte vor.</p>

    <div class="card border-0 shadow-sm rounded-4 mb-4">
        <div class="card-body p-4">
            <label class="form-label fw-semibold">Zutaten</label>
            <div id="tag-box" class="form-control d-flex flex-wrap gap-2 align-items-center" style="min-height: 48px;">
                <input type="text" id="tag-input" list="ingredient-suggestions"
                       class="border-0 flex-grow-1" style="outline:none; min-width:120px;"
                       placeholder="z. B. Hähnchen, Reis, Tomaten">
            </div>
            <datalist id="ingredient-suggestions">
                {% for name in autocomplete %}<option value="{{ name }}">{% endfor %}
            </datalist>
            <div class="form-text">Komma oder Enter fügt eine Zutat hinzu. Backspace löscht die letzte.</div>

            <div class="row g-3 mt-3">
                <div class="col-md-3">
                    <label for="portions" class="form-label">Portionen</label>
                    <input type="number" id="portions" class="form-control" min="1" max="50" value="{{ default_portions }}">
                </div>
                <div class="col-md-9">
                    <label class="form-label">Filter (optional)</label>
                    <div class="d-flex flex-wrap gap-3">
                        <div class="form-check"><input class="form-check-input filter-cb" type="checkbox" value="vegetarisch" id="f-veg"><label class="form-check-label" for="f-veg">Vegetarisch</label></div>
                        <div class="form-check"><input class="form-check-input filter-cb" type="checkbox" value="vegan" id="f-vegan"><label class="form-check-label" for="f-vegan">Vegan</label></div>
                        <div class="form-check"><input class="form-check-input filter-cb" type="checkbox" value="glutenfrei" id="f-glut"><label class="form-check-label" for="f-glut">Glutenfrei</label></div>
                        <div class="form-check"><input class="form-check-input filter-cb" type="checkbox" value="schnell" id="f-fast"><label class="form-check-label" for="f-fast">Schnell &lt;30min</label></div>
                    </div>
                </div>
            </div>

            <button id="generate-btn" class="btn btn-primary mt-3" type="button">
                <span id="generate-btn-label">3 Vorschläge generieren</span>
                <span id="generate-btn-spinner" class="spinner-border spinner-border-sm ms-2 d-none" role="status"></span>
            </button>
            <div id="gen-error" class="alert alert-danger mt-3 d-none"></div>
        </div>
    </div>

    <div id="results" class="d-none">
        <h2 class="h5 mb-3">Vorschläge</h2>
        <div id="suggestion-cards" class="d-flex flex-column gap-3"></div>
    </div>
</div>

{% csrf_token %}
<script>
(function () {
    const tagBox = document.getElementById('tag-box');
    const tagInput = document.getElementById('tag-input');
    const tags = [];

    function renderTags() {
        tagBox.querySelectorAll('.tag-pill').forEach(p => p.remove());
        tags.forEach((t, i) => {
            const pill = document.createElement('span');
            pill.className = 'badge bg-secondary tag-pill d-inline-flex align-items-center gap-1';
            pill.textContent = t;
            const close = document.createElement('button');
            close.type = 'button';
            close.className = 'btn-close btn-close-white btn-sm';
            close.style.fontSize = '0.6rem';
            close.addEventListener('click', () => { tags.splice(i, 1); renderTags(); });
            pill.appendChild(close);
            tagBox.insertBefore(pill, tagInput);
        });
    }

    function pushTag(raw) {
        const v = (raw || '').trim().replace(/,$/, '');
        if (!v) return;
        if (!tags.some(t => t.toLowerCase() === v.toLowerCase())) {
            tags.push(v);
            renderTags();
        }
    }

    tagInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            pushTag(tagInput.value);
            tagInput.value = '';
        } else if (e.key === 'Backspace' && tagInput.value === '' && tags.length > 0) {
            tags.pop();
            renderTags();
        }
    });
    tagInput.addEventListener('change', () => {
        // datalist click → fires 'change'
        if (tagInput.value) {
            pushTag(tagInput.value);
            tagInput.value = '';
        }
    });
    tagBox.addEventListener('click', () => tagInput.focus());

    const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
    const btn = document.getElementById('generate-btn');
    const btnLbl = document.getElementById('generate-btn-label');
    const btnSpin = document.getElementById('generate-btn-spinner');
    const errBox = document.getElementById('gen-error');
    const resultsBox = document.getElementById('results');
    const cardsBox = document.getElementById('suggestion-cards');

    function setLoading(on) {
        btn.disabled = on;
        btnSpin.classList.toggle('d-none', !on);
        btnLbl.textContent = on ? 'Generiere…' : '3 Vorschläge generieren';
    }
    function showError(msg) {
        errBox.textContent = msg;
        errBox.classList.remove('d-none');
    }

    async function generate() {
        errBox.classList.add('d-none');
        if (tags.length === 0) { showError('Mindestens 1 Zutat angeben.'); return; }
        const filters = [...document.querySelectorAll('.filter-cb:checked')].map(c => c.value);
        const portions = parseInt(document.getElementById('portions').value, 10);
        setLoading(true);
        cardsBox.innerHTML = '';
        resultsBox.classList.add('d-none');
        try {
            const r = await fetch("{% url 'ai_generator_suggest' %}", {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
                body: JSON.stringify({ ingredients: tags, portions, filters }),
            });
            const data = await r.json();
            if (!r.ok) { showError(data.error || 'Fehler.'); return; }
            renderSuggestions(data.suggestions);
            resultsBox.classList.remove('d-none');
        } catch (e) {
            showError('Netzwerkfehler.');
        } finally {
            setLoading(false);
        }
    }

    function renderSuggestions(suggestions) {
        suggestions.forEach((s, idx) => {
            const card = document.createElement('div');
            card.className = 'card border-0 shadow-sm rounded-4';
            const ingHtml = (s.ingredients || []).map(i =>
                `<li>${escapeHtml(i.quantity || '')} ${escapeHtml(i.name || '')}</li>`
            ).join('');
            card.innerHTML = `
                <div class="card-body p-4">
                    <div class="d-flex justify-content-between align-items-start">
                        <h3 class="h5 mb-1">${idx + 1}. ${escapeHtml(s.title)}</h3>
                        <span class="text-muted small">~${s.duration_min || '?'} min · ${parseInt(document.getElementById('portions').value, 10)} Portion(en)</span>
                    </div>
                    <h4 class="h6 mt-3">Zutaten</h4>
                    <ul class="mb-3">${ingHtml}</ul>
                    <h4 class="h6">Zubereitung</h4>
                    <p class="text-pre-wrap mb-3" style="white-space: pre-wrap;">${escapeHtml(s.instructions || '')}</p>
                    <button class="btn btn-success save-btn" type="button">Diesen Vorschlag speichern</button>
                    <span class="save-status ms-2"></span>
                </div>`;
            card.querySelector('.save-btn').addEventListener('click', () => save(card, s));
            cardsBox.appendChild(card);
        });
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    async function save(card, suggestion) {
        const status = card.querySelector('.save-status');
        const saveBtn = card.querySelector('.save-btn');
        saveBtn.disabled = true;
        status.textContent = 'Speichern…';
        try {
            const r = await fetch("{% url 'ai_generator_save' %}", {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
                body: JSON.stringify(suggestion),
            });
            const data = await r.json();
            if (!r.ok) { status.textContent = data.error || 'Fehler beim Speichern.'; saveBtn.disabled = false; return; }
            window.location = data.redirect_url;
        } catch (e) {
            status.textContent = 'Netzwerkfehler.';
            saveBtn.disabled = false;
        }
    }

    btn.addEventListener('click', generate);
})();
</script>
{% endblock %}
```

- [ ] **Step 6.2: Run the form test to ensure GET still renders cleanly**

```bash
DEBUG=True .venv/bin/python manage.py test meals.tests.AIGeneratorFormTest -v 2
```
Expected: 3 tests, all OK.

- [ ] **Step 6.3: Commit**

```bash
git add templates/meals/ai_generator.html
git commit -m "feat(meals): AI generator UI with tag input and AJAX suggestion cards"
```

---

## Task 7: Dashboard card on home.html

**Files:**
- Modify: `templates/home.html`

- [ ] **Step 7.1: Add the new card next to Aufgaben / Essensplanung / Einkaufsliste**

Edit `templates/home.html`. Find the row starting at the line that contains:

```html
<div class="row g-4 mb-5">
    <div class="col-lg-4">
        <div class="card border-0 shadow-sm rounded-4 h-100">
            <div class="card-body p-4">
                <h4 class="mb-3">Aufgaben</h4>
```

Change the outer row's columns from `col-lg-4` to `col-lg-3` (4 cards in a row on large screens) and append a new card after the "Einkaufsliste" card (just before the closing `</div>` of the row). The full replacement of that row block:

```html
<div class="row g-4 mb-5">
    <div class="col-md-6 col-lg-3">
        <div class="card border-0 shadow-sm rounded-4 h-100">
            <div class="card-body p-4">
                <h4 class="mb-3">Aufgaben</h4>
                <p class="text-muted">Plane Aufgaben für eure Woche.</p>
                <a href="{% url 'task_list' %}" class="btn btn-dark">Zu den Aufgaben</a>
            </div>
        </div>
    </div>

    <div class="col-md-6 col-lg-3">
        <div class="card border-0 shadow-sm rounded-4 h-100">
            <div class="card-body p-4">
                <h4 class="mb-3">Essensplanung</h4>
                <p class="text-muted">Plane eure Mahlzeiten für die Woche.</p>
                <a href="{% url 'meal_list' %}" class="btn btn-dark">Zur Essensplanung</a>
            </div>
        </div>
    </div>

    <div class="col-md-6 col-lg-3">
        <div class="card border-0 shadow-sm rounded-4 h-100">
            <div class="card-body p-4">
                <h4 class="mb-3">Einkaufsliste</h4>
                <p class="text-muted">Behalte offene Einkäufe im Blick.</p>
                <a href="{% url 'shopping_list' %}" class="btn btn-dark">Zur Einkaufsliste</a>
            </div>
        </div>
    </div>

    <div class="col-md-6 col-lg-3">
        <div class="card border-0 shadow-sm rounded-4 h-100">
            <div class="card-body p-4">
                <h4 class="mb-3">Was koche ich? 🍳</h4>
                <p class="text-muted">AI schlägt Rezepte aus deinen Zutaten vor.</p>
                <a href="{% url 'ai_generator_form' %}" class="btn btn-dark">Rezept generieren</a>
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 7.2: Manually verify the dashboard renders the card**

```bash
DEBUG=True .venv/bin/python manage.py runserver 8000
```
Open `http://localhost:8000/`, log in, confirm the new "Was koche ich? 🍳" card appears next to the other three. Click it → should reach the generator page. Stop server with Ctrl-C.

- [ ] **Step 7.3: Commit**

```bash
git add templates/home.html
git commit -m "feat(home): add 'Was koche ich?' card linking to AI recipe generator"
```

---

## Task 8: Full-test sweep, manual smoke, push

**Files:** none (verification only)

- [ ] **Step 8.1: Run the full meals test suite**

```bash
DEBUG=True .venv/bin/python manage.py test meals -v 1
```
Expected: all OK. Document the count (should be ≈ 18 new tests added across Tasks 1–5).

- [ ] **Step 8.2: Run all tests across all apps to verify no regressions**

```bash
DEBUG=True .venv/bin/python manage.py test 2>&1 | tail -5
```
Expected: all OK, except the 2 pre-existing WeasyPrint `ReportPDFTest` errors on macOS without `libgobject-2.0` — these are environmental and unrelated.

- [ ] **Step 8.3: Manual smoke with a real OpenAI key**

Requires `OPENAI_API_KEY` set in environment (or in `.env`). Skip if no key is available — in that case verify only the 503 branch by visiting `/meals/ai-generator/` and clicking "Generieren" without a key configured (should show the 503 error toast).

```bash
DEBUG=True OPENAI_API_KEY=sk-... .venv/bin/python manage.py runserver 8000
```
1. Login, visit `/meals/ai-generator/`.
2. Add tags: `Hähnchen`, `Reis`, `Tomaten`.
3. Check "Schnell <30min".
4. Click "3 Vorschläge generieren" → wait → confirm 3 cards appear with titles, ingredients, instructions.
5. Click "Diesen Vorschlag speichern" on the first card → redirected to `/meals/recipes/<pk>/`.
6. Confirm recipe shows ingredients and instructions.
7. Repeat with an existing-title collision: pick the same title twice in a row (or via DB), confirm second save lands at `Title (2)`.

- [ ] **Step 8.4: Push**

```bash
git push origin main
```

---

## Self-Review Notes

- Spec coverage: every spec section (URL routing, components, UI, AI integration, save flow, error cases, tests) is mapped to a task above. The "Open Questions" section in the spec is intentionally not implemented.
- Title-collision: spec mentions appending " (2)", " (3)" etc. — implemented in Task 5 with explicit tests at 5.1.
- Autocomplete dedup: spec says "deduped" — Task 1 tests case-insensitive dedup across both source tables.
- `recipe_ai_suggest` is **not** modified; spec calls this out as wiseful (no shared refactor in v1).
- `meals/views.py` gains module-level `OpenAI` and `settings` imports so tests can `@patch("meals.views.OpenAI")` / `@patch("meals.views.settings")` cleanly without touching the existing `recipe_ai_suggest` inline-import pattern.
- All OpenAI calls in tests are mocked; CI does not need a real key.
- No model or migration changes — none required.

