_UNIT_FORMS = {
    # maps any written form (lowercase) → (singular, plural)
    "zehe": ("Zehe", "Zehen"), "zehen": ("Zehe", "Zehen"),
    "prise": ("Prise", "Prisen"), "prisen": ("Prise", "Prisen"),
    "tasse": ("Tasse", "Tassen"), "tassen": ("Tasse", "Tassen"),
    "scheibe": ("Scheibe", "Scheiben"), "scheiben": ("Scheibe", "Scheiben"),
    "dose": ("Dose", "Dosen"), "dosen": ("Dose", "Dosen"),
    "packung": ("Packung", "Packungen"), "packungen": ("Packung", "Packungen"),
    "flasche": ("Flasche", "Flaschen"), "flaschen": ("Flasche", "Flaschen"),
    "knolle": ("Knolle", "Knollen"), "knollen": ("Knolle", "Knollen"),
    "stange": ("Stange", "Stangen"), "stangen": ("Stange", "Stangen"),
    "zweig": ("Zweig", "Zweige"), "zweige": ("Zweig", "Zweige"),
    "blatt": ("Blatt", "Blätter"), "blätter": ("Blatt", "Blätter"),
    "bund": ("Bund", "Bünde"), "bünde": ("Bund", "Bünde"),
    "ei": ("Ei", "Eier"), "eier": ("Ei", "Eier"),
    "stück": ("Stück", "Stück"),
    "esslöffel": ("Esslöffel", "Esslöffel"), "el": ("EL", "EL"),
    "teelöffel": ("Teelöffel", "Teelöffel"), "tl": ("TL", "TL"),
    "g": ("g", "g"), "kg": ("kg", "kg"),
    "ml": ("ml", "ml"), "l": ("l", "l"), "cl": ("cl", "cl"),
}


def _normalize_unit(unit):
    """Return the canonical singular form for known units, else the unit as-is."""
    if not unit:
        return ""
    forms = _UNIT_FORMS.get(unit.lower())
    return forms[0].lower() if forms else unit.lower()


def _format_qty(number, unit):
    """Format a number + unit with proper singular/plural."""
    if not unit:
        return str(number)
    forms = _UNIT_FORMS.get(unit.lower())
    if forms:
        display = forms[0] if number == 1 else forms[1]
    else:
        display = unit
    return f"{number} {display}"


def get_current_household(user):
    if user.is_authenticated:
        return user.households.first()
    return None


def parse_quantity(q):
    import re
    q = q.strip().replace(",", ".")
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([a-zA-ZäöüÄÖÜ]*)$', q)
    if match:
        number = float(match.group(1))
        unit_raw = match.group(2)
        return number, unit_raw
    return None


def merge_quantities(q1, q2):
    if not q1:
        return q2
    if not q2:
        return q1
    p1 = parse_quantity(q1)
    p2 = parse_quantity(q2)
    if p1 and p2 and _normalize_unit(p1[1]) == _normalize_unit(p2[1]):
        total = p1[0] + p2[0]
        total = int(total) if total == int(total) else total
        return _format_qty(total, p1[1])
    return f"{q1}, {q2}"


def get_item_suggestions(household):
    from shopping.models import ShoppingItem
    from meals.models import Ingredient

    shopping = ShoppingItem.objects.filter(household=household).values_list("name", flat=True)
    ingredients = Ingredient.objects.filter(recipe__household=household).values_list("name", flat=True)
    return sorted({n.strip() for n in list(shopping) + list(ingredients) if n.strip()}, key=str.lower)


def get_quantity_suggestions(household):
    from shopping.models import ShoppingItem
    from meals.models import Ingredient
    shopping = ShoppingItem.objects.filter(household=household).values_list("quantity", flat=True)
    ingredients = Ingredient.objects.filter(recipe__household=household).values_list("quantity", flat=True)
    return sorted({q.strip() for q in list(shopping) + list(ingredients) if q.strip()}, key=str.lower)