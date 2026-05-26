# Meals: AI-Rezept-Generator aus Zutaten

**Status:** Design approved (2026-05-26)
**Owner:** Wochi-Team
**Spec-Type:** Feature

## Context

Die meals-App enthält bereits eine OpenAI-Integration: `recipe_ai_suggest` generiert 3 Varianten zu einem **existierenden** Rezept-Titel. Diese Funktion löst nicht die häufige Alltagsfrage "Ich habe diese Zutaten zu Hause — was kann ich daraus kochen?".

Dieser Generator beantwortet genau das. Der User gibt die vorhandenen Zutaten ein, OpenAI antwortet mit 3 kompletten Rezeptvorschlägen (Titel, Zutaten mit Mengen, Anleitung). Der User wählt einen aus, der dann als regulärer `Recipe`-Eintrag inklusive `Ingredient`s im Haushalt gespeichert wird.

OpenAI-Integration, JSON-Response-Format und Error-Handling werden 1:1 nach dem Muster von `recipe_ai_suggest` umgesetzt, damit nur ein einziges Code-Pattern für AI-Endpoints im Projekt existiert.

## Goals

- Dashboard-Card "Was koche ich? 🍳" als Eintrittspunkt.
- Tag-basierte Zutaten-Eingabe mit Autocomplete aus den im Haushalt vorhandenen Ingredient- und ShoppingItem-Namen.
- Portionen-Auswahl (Default 2, freie Number-Input).
- Diet-Filter (Vegetarisch, Vegan, Glutenfrei, Schnell <30min) als Checkboxes.
- 3 Vorschläge per AJAX inline, ohne Page-Reload.
- "Speichern"-Button pro Vorschlag → erstellt Recipe + Ingredients → leitet zu Recipe-Detail um.
- Kein automatisches Bildgenerieren (Kostenkontrolle). User kann auf Recipe-Detail manuell triggern.

## Non-Goals

- Sammeln mehrerer Vorschläge gleichzeitig.
- Multi-Step-Wizards / komplexe Diet-Profile.
- Automatisches Hinzufügen zum Wochenplan.
- Eigene `Recipe`-Flag oder Tabelle für „AI-generiert".

## Architecture

### URL-Routing (`meals/urls.py`)

```
/meals/ai-generator/                GET  → ai_generator_form
/meals/ai-generator/suggest/        POST → ai_generator_suggest (JSON)
/meals/ai-generator/save/           POST → ai_generator_save (JSON, returns recipe pk)
```

### Komponenten

| Datei | Änderung |
|---|---|
| `meals/views.py` | + `ai_generator_form`, `ai_generator_suggest`, `ai_generator_save` |
| `meals/urls.py` | + 3 path-Einträge |
| `meals/utils.py` | NEU: `get_ingredient_autocomplete(household) → list[str]` (deduped, alpha-sortiert, aus Ingredient + ShoppingItem) |
| `templates/meals/ai_generator.html` | NEU: Form + AJAX-Result-Bereich |
| `templates/` Dashboard-Template | + Card "Was koche ich? 🍳" mit Link |
| `meals/tests.py` | Tests für die 3 Endpoints + Util |

Bestehendes `recipe_ai_suggest` bleibt unverändert. AI-Pattern wird wiederverwendet, nicht refactored.

### Dashboard-Card Verortung

Das Wochi-Dashboard ist die `home`-View in `accounts/`. Karte wird dort eingefügt, oberhalb der bestehenden Sections (oder dort, wo andere Quick-Action-Cards leben — beim Implementieren kurz prüfen).

## UI / Form

```
┌─ /meals/ai-generator/ ─────────────────────────────┐
│ ← zurück                                            │
│ Was koche ich? 🍳                                   │
│ Gib Zutaten ein, AI schlägt 3 Rezepte vor.          │
│                                                     │
│ Zutaten                                             │
│ [hähnchen ×] [reis ×] [tomaten ×] [Zutat...]        │
│ <datalist: alle Ingredient + ShoppingItem-Namen>    │
│                                                     │
│ Portionen: [ 2 ]    Filter:                         │
│                     ☐ Vegetarisch  ☐ Vegan          │
│                     ☐ Glutenfrei   ☐ Schnell <30m   │
│                                                     │
│   [ 3 Vorschläge generieren ]                       │
│                                                     │
│ ── Vorschläge erscheinen hier nach Submit ──        │
│                                                     │
│ Vorschlag 1: Hähnchen-Reis-Pfanne                   │
│ ~25 min · 2 Portionen                                │
│ Zutaten: 300g Hähnchen, 200g Reis, ...              │
│ Anleitung: 1. Reis aufsetzen. 2. ...                 │
│ [ Speichern ]                                        │
│ (Vorschlag 2/3 analog)                              │
└─────────────────────────────────────────────────────┘
```

**Tag-Input-Implementierung**:
- Sichtbares Text-`<input>` mit `list="ingredient-suggestions"` (Browser-`<datalist>` für Autocomplete).
- Komma oder Enter pusht neuen Tag als Pill (Bootstrap-Badge mit Close-Button).
- Backspace bei leerem Input löscht letzten Tag.
- Hidden `<input name="ingredients">` enthält bei Submit alle Tags kommasepariert.
- Pure-JS, ~50 Zeilen, kein Framework.

**Loading-State**: Submit-Button disabled + Spinner. Result-Section zeigt Skeleton-Karten.

**Bootstrap 5.3** durchgängig, konsistent mit restlicher App.

## AI-Integration

### Prompt

```python
prompt = f"""Du bist Kochassistent. User hat folgende Zutaten zur Verfügung: {ingredients_csv}.
Erstelle genau 3 verschiedene Rezeptvorschläge für {portions} Portion(en).
Filter (falls aktiv): {filter_csv}.

Regeln:
- Nutze möglichst nur die genannten Zutaten. Übliche Pantry-Items (Salz, Pfeffer, Öl, Wasser) darfst du ergänzen.
- Bei Filter 'vegetarisch': kein Fleisch/Fisch.
- Bei Filter 'vegan': zusätzlich keine tierischen Produkte.
- Bei Filter 'glutenfrei': kein Weizen/Roggen/Gerste.
- Bei Filter 'schnell': Zubereitung max 30 Minuten.

Antworte ausschließlich mit folgendem JSON:
{{
  "suggestions": [
    {{
      "title": "Kurzer prägnanter Rezeptname",
      "duration_min": 25,
      "ingredients": [{{"name": "Hähnchenbrust", "quantity": "300g"}}],
      "instructions": "1. Reis aufsetzen.\\n2. Hähnchen würfeln und anbraten.\\n3. ..."
    }}
  ]
}}
Genau 3 Vorschläge. Mengen in deutscher Notation (g, ml, EL, TL, Stück)."""
```

### Call

```python
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": prompt}],
    response_format={"type": "json_object"},
    temperature=0.7,
)
```

### Server-Validierung

- `len(data["suggestions"]) == 3` — bei Mismatch HTTP 502 „AI-Antwort unbrauchbar, bitte erneut versuchen".
- Jeder Vorschlag hat `title`, `ingredients` (list), `instructions` (string non-empty).
- Bei Validierungsfehler: 502 mit Fehler-Toast.

## Save-Flow

```
POST /meals/ai-generator/save/
Body: {
  "title": "Hähnchen-Reis-Pfanne",
  "duration_min": 25,
  "ingredients": [{"name": "Hähnchen", "quantity": "300g"}, ...],
  "instructions": "1. ..."
}
→ Recipe.objects.create(
    household=household,
    title=title,
    instructions=instructions,
    notes=f"~{duration_min} min · per AI generiert",
    created_by=request.user,
  )
→ Ingredient.objects.bulk_create([
    Ingredient(recipe=recipe, name=..., quantity=...) for ...
  ])
→ Response: {"recipe_id": recipe.pk, "redirect_url": "/meals/recipes/<pk>/"}
```

**Frontend**: JS macht POST, dann `window.location = redirect_url`.

**Edge Case Titel-Kollision**: `Recipe.Meta.unique_together = ("household", "title")`. Bei Konflikt: title bekommt Suffix `" (2)"`, `" (3)"` etc. bis frei. Server-side.

## Error-Cases (alle JsonResponse)

| Bedingung | Status | Body |
|---|---|---|
| Kein API-Key | 503 | `{"error": "Kein OpenAI API-Key konfiguriert."}` |
| `RateLimitError` | 429 | `{"error": "Aktuell sind keine Rezeptvorschläge verfügbar."}` |
| Andere OpenAI-Exception | 500 | `{"error": str(e)}` |
| Leerer Zutaten-Input | 400 | `{"error": "Mindestens 1 Zutat angeben."}` |
| >30 Zutaten | 400 | `{"error": "Maximal 30 Zutaten."}` |
| Portionen <1 oder >50 | 400 | `{"error": "Portionen müssen zwischen 1 und 50 liegen."}` |
| AI-Response nicht 3 Vorschläge | 502 | `{"error": "AI-Antwort unbrauchbar, bitte erneut versuchen."}` |

Frontend zeigt Toast mit Error-Body.

## Tests

`meals/tests.py` neue Test-Klasse `RecipeAIGeneratorTest`:

1. `test_ai_generator_form_loads` — GET-Endpoint rendert.
2. `test_ai_generator_form_requires_login` — anonymer GET redirected.
3. `test_ai_generator_form_requires_household` — User ohne Household → redirect.
4. `test_suggest_validates_empty_ingredients` — 400.
5. `test_suggest_validates_too_many_ingredients` — 31 Zutaten → 400.
6. `test_suggest_validates_portions_range` — 0 oder 51 → 400.
7. `test_suggest_handles_missing_api_key` (settings override OPENAI_API_KEY=""), → 503.
8. `test_save_creates_recipe_and_ingredients` — POST mit gültigem Payload → Recipe + Ingredients existieren, household-scoped, redirect_url korrekt.
9. `test_save_handles_title_collision` — gleicher Titel existiert → Recipe-Titel bekommt " (2)" Suffix.
10. `test_save_household_isolation` — User aus Household A kann nicht in Household B speichern.
11. `test_get_ingredient_autocomplete_dedupes` — Util-Test: doppelte Namen aus Ingredient + ShoppingItem werden dedupliziert (case-insensitive).

OpenAI-Call selbst wird via `unittest.mock.patch` gemockt — keine echten API-Calls in CI.

## Performance & Cost

- gpt-4o-mini: ~$0.15 / 1M input tokens, $0.60 / 1M output tokens. Pro Generate-Call ca. ~500 input + ~800 output Tokens → ca. $0.0006 pro Generierung. Vernachlässigbar.
- Keine Caching-Layer in v1 (kann später Redis-cached werden wenn relevant).
- Autocomplete-Util: kleiner Query, deduped in-memory, kein N+1.

## Open Questions (nichts blockiert Plan)

- Diet-Filter „Glutenfrei" reicht in v1; Allergie-Profile pro User wären Folge-Feature.
- Mengen-Skalierung post-save: bestehende `ingredient_scale`-Funktion klappt direkt; falls User nachträglich Portionen ändert.

## Migration

Keine DB-Schema-Änderung. Nur neue Views, URLs, Template, Util.

## Rollout

Direkt nach Merge sichtbar. Kein Feature-Flag nötig. Bei API-Key-Fehlen zeigt die Card weiterhin den Link, der dann auf der Generator-Seite eine 503-Meldung anzeigt — ok.
