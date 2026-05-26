from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from households.models import Household
from meals.models import Recipe, Ingredient
from meals.utils import get_ingredient_autocomplete
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

        result = get_ingredient_autocomplete(self.household)

        self.assertEqual(result, ["Hähnchen", "Reis", "Tomaten"])

    def test_autocomplete_scoped_to_household(self):
        other = Household.objects.create(name="Other")
        other_user = User.objects.create_user(username="other", password="pw123456")
        other.members.add(other_user)
        other_recipe = Recipe.objects.create(household=other, title="X", created_by=other_user)
        Ingredient.objects.create(recipe=other_recipe, name="DoNotShow", quantity="")

        result = get_ingredient_autocomplete(self.household)

        self.assertNotIn("DoNotShow", result)

    def test_autocomplete_empty_household_returns_empty_list(self):
        self.assertEqual(get_ingredient_autocomplete(self.household), [])

    def test_autocomplete_skips_whitespace_only_names(self):
        recipe = Recipe.objects.create(household=self.household, title="R", created_by=self.user)
        Ingredient.objects.create(recipe=recipe, name="   ", quantity="")
        Ingredient.objects.create(recipe=recipe, name="Reis", quantity="200g")
        result = get_ingredient_autocomplete(self.household)
        self.assertEqual(result, ["Reis"])


from django.urls import reverse


class AIGeneratorRoutingTest(TestCase):
    def test_urls_resolve(self):
        self.assertEqual(reverse("ai_generator_form"), "/meals/ai-generator/")
        self.assertEqual(reverse("ai_generator_suggest"), "/meals/ai-generator/suggest/")
        self.assertEqual(reverse("ai_generator_save"), "/meals/ai-generator/save/")


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
        self.household.members.clear()
        response = self.client.get("/meals/ai-generator/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/households/choose/", response["Location"])


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
