from django import template

from meals.utils import cloudinary_thumbnail

register = template.Library()


@register.filter
def recipe_thumb(url, width=600):
    """Rezeptbild in passender Größe: {{ recipe.image|recipe_thumb }} oder |recipe_thumb:1024."""
    return cloudinary_thumbnail(url, width)
