from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

from django.utils import timezone

from households.utils import _format_qty, parse_quantity
from meals.models import Ingredient, Recipe
from shopping.models import ShoppingItem

# Obergrenzen für Rezeptdaten aus KI-Antworten und AJAX-Payloads – passend zu
# den Feldlängen (Ingredient.name 200, quantity 100) bzw. der REST-API.
MAX_RECIPE_INGREDIENTS = 50
MAX_INSTRUCTIONS_LENGTH = 20000


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


def planning_range():
    """Heute bis Sonntag nächster Woche – der Zeitraum, den die Essensplanung zeigt.

    Bereits vergangene Tage gehören nicht dazu: deren Zutaten sind gegessen und
    sollen z. B. nicht mehr auf die Einkaufsliste.
    """
    today = timezone.localdate()
    return today, today + timedelta(days=13 - today.weekday())


def find_recipe_by_title(household, title):
    """Gericht des Haushalts mit diesem Namen (Groß-/Kleinschreibung egal) oder None.

    Ältere Daten können "Pizza" und "pizza" nebeneinander enthalten; dann
    gewinnt die exakte Schreibweise.
    """
    matches = list(Recipe.objects.filter(household=household, title__iexact=title))
    for recipe in matches:
        if recipe.title == title:
            return recipe
    return matches[0] if matches else None


def scale_quantity(quantity, factor):
    """Menge mit einem Faktor umrechnen ("200 g" × 1,5 = "300 g").

    Gibt None zurück, wenn die Menge keine Zahl enthält ("etwas", "1 Prise
    Salz") – solche Angaben bleiben unverändert.
    """
    parsed = parse_quantity(quantity or "")
    if not parsed:
        return None
    number, unit = parsed
    scaled = number * factor
    scaled = int(scaled) if scaled == int(scaled) else round(scaled, 2)
    return _format_qty(scaled, unit)[:100]


def clean_ingredient_list(raw):
    """Zutaten aus einer KI-Antwort oder einem Payload als Liste von Dicts.

    Das Modell liefert Mengen gelegentlich als Zahl (300 statt "300 g") oder
    einzelne Einträge in anderer Form; alles wird zu Text auf Feldlänge gekürzt,
    Einträge ohne Namen fallen weg.
    """
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw[:MAX_RECIPE_INGREDIENTS]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:200]
        if not name:
            continue
        quantity = item.get("quantity")
        quantity = "" if quantity is None else str(quantity).strip()[:100]
        cleaned.append({"name": name, "quantity": quantity})
    return cleaned


def cloudinary_thumbnail(url, width=600):
    """Verkleinerte, komprimierte Variante eines Cloudinary-Bildes.

    Generierte Rezeptbilder sind 1024×1024-PNGs mit über einem Megabyte. Für
    Listen liefert Cloudinary über eine Transformation in der URL eine passende
    Größe im besten Format des Browsers. Andere URLs bleiben unverändert.
    """
    if not url:
        return url
    parts = urlsplit(url)
    if parts.hostname != "res.cloudinary.com" or "/upload/" not in parts.path:
        return url
    path = parts.path.replace("/upload/", f"/upload/w_{int(width)},c_fill,f_auto,q_auto/", 1)
    return urlunsplit(parts._replace(path=path))
