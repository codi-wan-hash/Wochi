from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from households.utils import get_current_household
from .models import ShoppingItem
from .forms import ShoppingItemForm

@login_required
def shopping_list(request):
    household = get_current_household(request.user)

    if not household:
        return render(request, "shopping/no_household.html")
    
    items = ShoppingItem.objects.filter(household=household)

    status_filter = request.GET.get("status")
    if status_filter == "open":
        items = items.filter(is_bought=False)
    elif status_filter == "bought":
        items = items.filter(is_bought=True)

    return render(request, "shopping/shopping_list.html", {
        "items": items,
        "household": household,
        "status_filter": status_filter,
    })

@login_required
def shopping_create(request):
    household = get_current_household(request.user)

    if not household:
        return render(request, "shopping/no_household.html")
    
    if request. method == "POST":
        form = ShoppingItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.household = household
            item.added_by = request.user
            item.save()
            return redirect("shopping_list")
    else:
        form = ShoppingItemForm()

    return render(request, "shopping/shopping_form.html", {
        "form": form,
        "title": "Artikel hinzufügen",
    })

@login_required
def shopping_update(request, pk):
    household = get_current_household(request.user)
    item = get_object_or_404(ShoppingItem, pk=pk, household=household)

    if request.method == "POST":
        form = ShoppingItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            return redirect("shopping_list")
    else:
        form = ShoppingItemForm(instance=item)

    return render(request, "shopping/shopping_form.html", {
        "form": form,
        "title": "Artikel bearbeiten",
    })

@login_required
def shopping_delete(request, pk):
    household = get_current_household(request.user)
    item = get_object_or_404(ShoppingItem, pk=pk, household=household)

    if request.method == "POST":
        item.delete()
        return redirect("shopping_list")
    
    return render(request, "shopping/shopping_confirm_delete.html", {"item": item})

@login_required
def shopping_toggle_bought(request, pk):
    household = get_current_household(request.user)
    item = get_object_or_404(ShoppingItem, pk=pk, household=household)

    item.is_bought = not item.is_bought
    item.save()

    return redirect("shopping_list")
        