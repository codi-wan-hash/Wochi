from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404

from households.utils import get_current_household, get_item_suggestions, get_quantity_suggestions, merge_quantities
from .models import ShoppingItem, Store, ShoppingSession, StoreItemOrder
from .forms import ShoppingItemForm
from .utils import sort_by_store as _sort_by_store


def _active_session(household):
    return ShoppingSession.objects.filter(household=household, ended_at__isnull=True).first()


@login_required
def shopping_list(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    items = list(ShoppingItem.objects.filter(household=household))
    session = _active_session(household)

    if session:
        bought = [i for i in items if i.is_bought]
        unbought = [i for i in items if not i.is_bought]
        items = _sort_by_store(unbought, session.store) + bought

    return render(request, "shopping/shopping_list.html", {
        "items": items,
        "household": household,
        "active_session": session,
    })


@login_required
def shopping_create(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        form = ShoppingItemForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"].strip()
            quantity = form.cleaned_data["quantity"].strip()
            force = request.POST.get("force") == "true"
            existing = ShoppingItem.objects.filter(
                household=household, name__iexact=name, is_bought=False
            ).first()
            if existing and not force and is_ajax:
                return JsonResponse({
                    "status": "duplicate",
                    "existing_id": existing.pk,
                    "existing_quantity": existing.quantity,
                    "new_quantity": quantity,
                    "name": existing.name,
                })
            if existing and force:
                item = form.save(commit=False)
                item.household = household
                item.added_by = request.user
                item.save()
            elif existing:
                existing.quantity = merge_quantities(existing.quantity, quantity)
                existing.save()
            else:
                item = form.save(commit=False)
                item.household = household
                item.added_by = request.user
                item.save()
            if is_ajax:
                return JsonResponse({"status": "added"})
            return redirect("shopping_list")
    else:
        form = ShoppingItemForm()

    return render(request, "shopping/shopping_form.html", {
        "form": form,
        "title": "Artikel hinzufügen",
        "suggestions": get_item_suggestions(household),
        "quantity_suggestions": get_quantity_suggestions(household),
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
        "suggestions": get_item_suggestions(household),
        "quantity_suggestions": get_quantity_suggestions(household),
    })


@login_required
def shopping_delete(request, pk):
    household = get_current_household(request.user)
    item = get_object_or_404(ShoppingItem, pk=pk, household=household)

    if request.method == "POST":
        item.delete()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"deleted": True})
        return redirect("shopping_list")

    return render(request, "shopping/shopping_confirm_delete.html", {"item": item})


@login_required
def shopping_toggle_bought(request, pk):
    household = get_current_household(request.user)
    item = get_object_or_404(ShoppingItem, pk=pk, household=household)

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

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"is_bought": item.is_bought})
    return redirect("shopping_list")


@login_required
def start_shopping(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    if _active_session(household):
        return redirect("shopping_list")

    stores = Store.objects.filter(household=household)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "select":
            store_id = request.POST.get("store_id")
            store = get_object_or_404(Store, pk=store_id, household=household)
        elif action == "new":
            name = request.POST.get("name", "").strip()
            location = request.POST.get("location", "").strip()
            if not name:
                return render(request, "shopping/start_shopping.html", {
                    "stores": stores,
                    "error": "Bitte einen Ladennamen eingeben.",
                })
            store, _ = Store.objects.get_or_create(
                household=household,
                name=name,
                location=location,
            )
        else:
            return redirect("shopping_list")

        ShoppingSession.objects.create(
            household=household,
            store=store,
            started_by=request.user,
        )
        return redirect("shopping_list")

    return render(request, "shopping/start_shopping.html", {"stores": stores})


@login_required
def shopping_merge_quantity(request, pk):
    household = get_current_household(request.user)
    item = get_object_or_404(ShoppingItem, pk=pk, household=household)

    if request.method == "POST":
        extra = request.POST.get("extra_quantity", "").strip()
        if extra:
            item.quantity = merge_quantities(item.quantity, extra)
        item.save()
        return JsonResponse({"status": "merged", "new_quantity": item.quantity})

    return redirect("shopping_list")


@login_required
def end_shopping(request):
    household = get_current_household(request.user)
    session = _active_session(household)
    if session:
        session.end()
    return redirect("shopping_list")
