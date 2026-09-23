# Overhaul Web-App + App: Alltagstauglichkeit, Offline-Einkauf, Sicherheit

Stand: 2026-09-23. Auftrag: Overhaul von Web-App (dieses Repo) und Mobile-App
(`../wochi-app`), Prüfung auf Alltagstauglichkeit, Bugs, Sicherheit und
UI/UX; Einkauf in der App auch ohne Netz; Samsung-Navigationsleiste und
Tastatur; Cache-Hygiene; Passwort-Reset in der App; danach Expo-Build.
Alle Entscheidungen wurden eigenständig getroffen (Auftraggeber abwesend).

Grundlage: eigenes Code-Review der App, Security-Review und UX-/Bug-Review der
Web-App (beide mit verifizierten Befunden), Recherche zu App-Standards.

## Leitentscheidungen

1. **Offline-first nur für den Einkauf, Lese-Cache für den Rest.**
   Die Einkaufsliste wird in der App lokal gespeichert; jede Änderung wird
   sofort lokal angewendet und zusätzlich in eine Warteschlange (Outbox)
   gelegt. Die Outbox wird gebündelt an `POST /api/shopping/sync/` geschickt.
   Aufgaben, Essensplan und Rezepte zeigen offline den letzten Stand an
   (nur lesen); Änderungen dort brauchen Netz und sagen das klar.
2. **Idempotenz statt Konfliktauflösung.** Jede Sync-Operation ist
   wiederholbar: `client_id` (UUID) für neu angelegte Artikel und
   Einkäufe, `set_bought` setzt absolut statt umzuschalten, fehlende Artikel
   werden übersprungen. Der Request nennt den Haushalt explizit
   (`household_id`), damit ein Haushaltswechsel im Web nie offline gesammelte
   Änderungen in den falschen Haushalt schreibt.
3. **Formulare als eigene Screens statt Bottom-Sheets mit Tastatur.**
   Die bisherige Keyboard-Rechnung im Modal ist auf Samsung/Edge-to-Edge
   fragil. Neue Formulare sind Stack-Screens mit Kopfzeile (immer ein
   Zurück-Weg) und `KeyboardAwareScrollView`
   (react-native-keyboard-controller). Bottom-Sheets nur noch für Auswahlen
   ohne Texteingabe. Artikel hinzufügen: Eingabezeile am unteren Rand, die
   über der Tastatur klebt (mehrere Artikel nacheinander, Tastatur bleibt
   offen).
4. **Erledigte Artikel verschwinden.** „Einkauf beenden" (Web und App)
   entfernt abgehakte Artikel; zusätzlich „Erledigte entfernen". Die
   Vorschläge beim Hinzufügen kommen aus dem neuen Modell `FrequentItem`
   (pro Haushalt max. 500 Namen), damit nichts verloren geht.
5. **Haushalt wechseln/verlassen.** `HouseholdSelection` speichert den
   aktiven Haushalt; `get_current_household` berücksichtigt ihn. Beitritt
   per Link/Token macht den neuen Haushalt aktiv. Verlässt das letzte
   Mitglied einen Haushalt, wird er samt Daten gelöscht (mit Warnung).
6. **Konto löschen** (Store-Pflicht bei Apple und Google) in Web und App.
   Dafür stehen `created_by`/`added_by`/`started_by` jetzt auf `SET_NULL` –
   bisher hätte das Löschen eines Nutzers Rezepte, Aufgaben und
   Einkaufsartikel des ganzen Haushalts mitgelöscht.
7. **Cache-Hygiene in der App.** Alle Daten unter einem Präfix, pro Nutzer
   und Haushalt; jede Ressource genau ein Snapshot (überschreibt sich);
   Outbox wird verdichtet und ist begrenzt. Abmelden löscht alles (mit
   Warnung bei nicht synchronisierten Änderungen), Haushaltswechsel löscht
   die Daten des alten Haushalts, beim Start werden fremde/alte Schlüssel
   entfernt. Im Profil: Speicherbelegung, ausstehende Änderungen,
   „Jetzt synchronisieren", „Offline-Daten löschen".
8. **Sitzungen:** Refresh-Token rotieren (gleitende Anmeldung, aktive Nutzer
   werden nicht mehr nach 30 Tagen hart abgemeldet); Access-Token kurz.
   Widerruf ohne Blacklist-Tabelle über `tokens_valid_after` (Passwort
   ändern/Konto löschen macht alle Tokens ungültig). Netzfehler beim Refresh
   melden die App **nicht** mehr ab (bisher: App ohne Netz starten =
   abgemeldet).

## Offline-Sync-Protokoll

`POST /api/shopping/sync/` mit `{"household_id": 7, "ops": [...]}` (max. 200).
Antwort: `{"results": [{"op_id", "status": "ok|skipped|error", "detail"}],
"items": [...], "session": {...}|null, "stores": [{..., "item_order":
{name: pos}}], "suggestions": [...], "server_time"}`. Ohne `ops` = reiner
Abruf. 403, wenn der Nutzer nicht (mehr) Mitglied ist.

| type | Felder | idempotent über |
|---|---|---|
| add | client_id, name, quantity | client_id |
| update | item{id,client_id}, name?, quantity? | absolute Werte |
| set_bought | item, is_bought | absoluter Wert |
| delete | items[] | fehlend = übersprungen |
| start_session | client_id, store_id und/oder store_name/store_location | client_id; läuft schon ein anderer Einkauf → übersprungen |
| end_session | session{id,client_id} | beendet nur genau diese Session |

Die App sortiert selbst (offen vor erledigt; mit Einkauf nach gelernter
Laden-Reihenfolge, sonst alphabetisch) und wendet nach jeder Antwort die
noch nicht gesendeten Operationen erneut auf den Server-Stand an.

## Nicht Teil dieses Overhauls (bewusst)

- Offline-Bearbeitung von Aufgaben/Essensplan/Rezepten (nur Lese-Cache).
- Push-Benachrichtigungen auf Android: dafür fehlt die Firebase-Konfiguration
  (`google-services.json`), das kann nur der Kontoinhaber einrichten.
- Impressum/Datenschutzerklärung: braucht echte Betreiberangaben.
- Container als Nicht-Root, Redis-Cache, CSP mit Nonces: Empfehlungen im
  Abschlussbericht, weil ohne Serverzugang nicht gefahrlos testbar.
