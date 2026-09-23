from django.db import transaction

from households.utils import leave_household


@transaction.atomic
def delete_account(user):
    """Konto endgültig löschen.

    Der Benutzer verlässt zuerst alle Haushalte; Haushalte, in denen danach
    niemand mehr ist, werden samt Daten gelöscht. In gemeinsam genutzten
    Haushalten bleiben Aufgaben, Rezepte und Einkaufsartikel erhalten (die
    Verweise auf den Ersteller werden per SET_NULL geleert). Persönliche
    Daten wie die Arbeitszeiterfassung werden mit dem Konto gelöscht.
    """
    for household in list(user.households.all()):
        leave_household(user, household)
    user.delete()
