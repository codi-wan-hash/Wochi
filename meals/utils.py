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
