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
