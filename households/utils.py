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
    """Der aktive Haushalt des Benutzers – Grundlage jeder Datenabfrage.

    Hat der Benutzer einen Haushalt ausgewählt und ist dort noch Mitglied,
    gilt dieser, sonst der älteste seiner Haushalte.
    """
    if not user.is_authenticated:
        return None
    from .models import HouseholdSelection

    selection = (
        HouseholdSelection.objects.filter(user=user, household__members=user)
        .select_related("household")
        .first()
    )
    if selection:
        return selection.household
    return user.households.order_by("pk").first()


def set_current_household(user, household):
    """Macht household zum aktiven Haushalt (Mitgliedschaft prüft der Aufrufer)."""
    from .models import HouseholdSelection

    HouseholdSelection.objects.update_or_create(user=user, defaults={"household": household})


def leave_household(user, household):
    """Mitgliedschaft beenden.

    Ist danach niemand mehr Mitglied, wird der Haushalt mit allen Daten
    gelöscht – verwaiste Haushalte wären Datenmüll, den niemand mehr sieht.
    Gibt True zurück, wenn der Haushalt gelöscht wurde.
    """
    from .models import HouseholdSelection

    household.members.remove(user)
    HouseholdSelection.objects.filter(user=user, household=household).delete()
    if not household.members.exists():
        household.delete()
        return True
    return False


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
    """Artikelnamen für die Autovervollständigung.

    Enthält auch Artikel, die längst gekauft und von der Liste entfernt
    wurden (FrequentItem). Gleiche Namen in anderer Schreibweise erscheinen
    nur einmal.
    """
    from shopping.models import FrequentItem, ShoppingItem
    from meals.models import Ingredient

    names = list(FrequentItem.objects.filter(household=household).values_list("name", flat=True))
    names += list(ShoppingItem.objects.filter(household=household).values_list("name", flat=True))
    names += list(Ingredient.objects.filter(recipe__household=household).values_list("name", flat=True))
    unique = {}
    for name in names:
        cleaned = name.strip()
        if cleaned:
            unique.setdefault(cleaned.lower(), cleaned)
    return sorted(unique.values(), key=str.lower)


def get_quantity_suggestions(household):
    from shopping.models import ShoppingItem
    from meals.models import Ingredient
    shopping = ShoppingItem.objects.filter(household=household).values_list("quantity", flat=True)
    ingredients = Ingredient.objects.filter(recipe__household=household).values_list("quantity", flat=True)
    return sorted({q.strip() for q in list(shopping) + list(ingredients) if q.strip()}, key=str.lower)

class MemberRemovalError(Exception):
    """Mitglied darf (von diesem Benutzer) nicht entfernt werden."""


def removable_member_ids(household, user):
    """IDs der Mitglieder, die user entfernen darf: alle, die nach ihm beigetreten sind.

    Einladungslinks dürfen weitergegeben werden und der Beitritt braucht keine
    Freigabe. Ohne diese Regel könnte ein Fremder mit einem geleakten Link
    beitreten und die Familie aus ihrem eigenen Haushalt werfen. So kann er
    niemanden entfernen, der vor ihm da war – die Familie ihn aber schon.
    Die Reihenfolge ergibt sich aus den Zeilen der Mitgliedschaftstabelle.
    """
    from .models import Household

    through = Household.members.through
    rows = dict(through.objects.filter(household=household).values_list("user_id", "pk"))
    own = rows.get(user.pk)
    if own is None:
        return set()
    return {member_id for member_id, row in rows.items() if row > own}


def remove_member(household, acting_user, member):
    """Mitglied aus dem Haushalt entfernen (siehe removable_member_ids)."""
    from .models import HouseholdSelection

    if member.pk == acting_user.pk:
        raise MemberRemovalError("Um selbst zu gehen, nutze „Haushalt verlassen“.")
    if member.pk not in removable_member_ids(household, acting_user):
        raise MemberRemovalError(
            "Entfernen kann nur, wer schon länger im Haushalt ist als die betreffende Person."
        )
    household.members.remove(member)
    HouseholdSelection.objects.filter(user=member, household=household).delete()
