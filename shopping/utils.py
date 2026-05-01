from .models import StoreItemOrder


def sort_by_store(items, store):
    orders = {
        o.item_name: o.avg_position
        for o in StoreItemOrder.objects.filter(store=store)
    }
    known, unknown = [], []
    for item in items:
        key = item.name.lower().strip()
        if key in orders:
            known.append((orders[key], item))
        else:
            unknown.append(item)
    known.sort(key=lambda x: x[0])
    return [item for _, item in known] + unknown
