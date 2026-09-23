from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from households.utils import get_current_household, get_item_suggestions, get_quantity_suggestions
from . import services
from .models import ShoppingItem, Store, ShoppingSession
from .forms import ShoppingItemForm, StoreForm
from .utils import sort_by_store as _sort_by_store


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _list_context(household):
    items = list(ShoppingItem.objects.filter(household=household).select_related("added_by"))
    session = services.active_session(household)
    open_items = [i for i in items if not i.is_bought]
    bought_items = [i for i in items if i.is_bought]
    if session:
        open_items = _sort_by_store(open_items, session.store)
    return {
        "household": household,
        "active_session": session,
        "open_items": open_items,
        "bought_items": bought_items,
    }


@login_required
def shopping_list(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    context = _list_context(household)
    # Die Seite holt sich beim Zurückkehren in den Tab nur die Liste neu,
    # damit zwei Leute im Laden die Häkchen des anderen sehen.
    if request.GET.get("partial") == "1":
        return render(request, "shopping/_list.html", context)
    context.update({
        "form": ShoppingItemForm(),
        "suggestions": get_item_suggestions(household),
    })
    return render(request, "shopping/shopping_list.html", context)


@login_required
def shopping_create(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    is_ajax = _is_ajax(request)

    if request.method == "POST":
        form = ShoppingItemForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"].strip()
            quantity = form.cleaned_data["quantity"].strip()
            force = request.POST.get("force") == "true"
            same_name = ShoppingItem.objects.filter(household=household, name__iexact=name)
            existing = same_name.filter(is_bought=False).first()
            if existing and not force and is_ajax:
                return JsonResponse({
                    "status": "duplicate",
                    "existing_id": existing.pk,
                    "existing_quantity": existing.quantity,
                    "new_quantity": quantity,
                    "name": existing.name,
                })
            if existing and not force:
                existing.quantity = services.merge_quantity_text(existing.quantity, quantity)
                existing.save(update_fields=["quantity"])
                item = existing
            else:
                # Schon gekauft und wieder gebraucht: den alten Eintrag zurück
                # auf die Liste holen statt eine zweite Zeile anzulegen.
                bought = None if force else same_name.filter(is_bought=True).first()
                if bought:
                    bought.is_bought = False
                    bought.quantity = quantity
                    bought.save(update_fields=["is_bought", "quantity"])
                    item = bought
                else:
                    item = form.save(commit=False)
                    item.household = household
                    item.added_by = request.user
                    item.save()
            if is_ajax:
                return JsonResponse({
                    "status": "added",
                    "id": item.pk,
                    "html": render_to_string("shopping/_item_row.html", {"item": item}, request=request),
                })
            messages.success(request, f"„{name}“ zur Einkaufsliste hinzugefügt.")
            return redirect("shopping_list")
        if is_ajax:
            return JsonResponse({"status": "invalid", "errors": form.errors}, status=400)
    else:
        form = ShoppingItemForm()

    return render(request, "shopping/shopping_form.html", {
        "form": form,
        "title": "Artikel hinzufügen",
        "is_edit": False,
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
            messages.success(request, "Artikel aktualisiert.")
            return redirect("shopping_list")
    else:
        form = ShoppingItemForm(instance=item)

    return render(request, "shopping/shopping_form.html", {
        "form": form,
        "item": item,
        "title": "Artikel bearbeiten",
        # Das Bearbeiten-Formular postet ganz normal an seine eigene URL;
        # das AJAX-Skript für Duplikate gilt nur beim Anlegen.
        "is_edit": True,
        "suggestions": get_item_suggestions(household),
        "quantity_suggestions": get_quantity_suggestions(household),
    })


@login_required
def shopping_delete(request, pk):
    household = get_current_household(request.user)
    item = get_object_or_404(ShoppingItem, pk=pk, household=household)

    if request.method == "POST":
        item.delete()
        if _is_ajax(request):
            # Kein messages.success: die Meldung käme erst beim nächsten Aufruf.
            return JsonResponse({"deleted": True})
        messages.success(request, "Artikel gelöscht.")
        return redirect("shopping_list")

    return render(request, "shopping/shopping_confirm_delete.html", {"item": item})


@login_required
@require_POST
def shopping_toggle_bought(request, pk):
    household = get_current_household(request.user)
    item = get_object_or_404(ShoppingItem, pk=pk, household=household)
    services.set_bought(household, item, not item.is_bought)

    if _is_ajax(request):
        return JsonResponse({"is_bought": item.is_bought})
    return redirect("shopping_list")


@login_required
@require_POST
def shopping_clear_bought(request):
    household = get_current_household(request.user)
    if not household:
        return redirect("choose_household")
    removed = services.clear_bought(household)
    if _is_ajax(request):
        return JsonResponse({"removed": removed})
    messages.success(request, f"{removed} erledigte Artikel entfernt.")
    return redirect("shopping_list")


@login_required
def start_shopping(request):
    household = get_current_household(request.user)

    if not household:
        return redirect("choose_household")

    if services.active_session(household):
        return redirect("shopping_list")

    stores = Store.objects.filter(household=household)
    form = StoreForm()

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "select":
            store = get_object_or_404(Store, pk=request.POST.get("store_id"), household=household)
        elif action == "new":
            form = StoreForm(request.POST)
            if not form.is_valid():
                return render(request, "shopping/start_shopping.html", {"stores": stores, "form": form})
            store, _ = Store.objects.get_or_create(
                household=household,
                name=form.cleaned_data["name"],
                location=form.cleaned_data["location"],
            )
        else:
            return redirect("shopping_list")

        ShoppingSession.objects.create(
            household=household,
            store=store,
            started_by=request.user,
        )
        messages.success(request, f"Einkauf bei „{store.name}“ gestartet.")
        return redirect("shopping_list")

    return render(request, "shopping/start_shopping.html", {"stores": stores, "form": form})


@login_required
@require_POST
def shopping_merge_quantity(request, pk):
    household = get_current_household(request.user)
    item = get_object_or_404(ShoppingItem, pk=pk, household=household)
    extra = request.POST.get("extra_quantity", "").strip()
    if extra:
        item.quantity = services.merge_quantity_text(item.quantity, extra)
        item.save(update_fields=["quantity"])
    return JsonResponse({
        "status": "merged",
        "new_quantity": item.quantity,
        "html": render_to_string("shopping/_item_row.html", {"item": item}, request=request),
    })


@login_required
@require_POST
def end_shopping(request):
    household = get_current_household(request.user)
    session, removed = services.finish_shopping(household)
    if session:
        text = "Einkauf beendet."
        if removed:
            text += f" {removed} erledigte Artikel wurden von der Liste entfernt."
        messages.success(request, text)
    return redirect("shopping_list")
