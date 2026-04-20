# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
.venv\Scripts\activate      # Windows
pip install -r requirements.txt

# Run dev server
python manage.py runserver

# Migrations
python manage.py makemigrations
python manage.py migrate

# Run tests
python manage.py test

# Collect static files (production)
python manage.py collectstatic
```

## Architecture

Django 6 multi-tenant household management app. UI is in German. Deployed on Render (https://wochi.onrender.com) with PostgreSQL; SQLite locally.

### Apps

- **accounts** — registration, login, home dashboard
- **households** — household creation and membership (many-to-many with User)
- **tasks** — to-do items per household (priority, status, assignments)
- **meals** — meal planning by date/type + recipe management
- **shopping** — shopping list with bought/unbought toggle

### Key pattern: household isolation

Every request goes through `get_current_household(user)` (defined in `households/`), which returns the user's active household. All model queries are scoped to `household=current_household`. Models use `ForeignKey(Household)` and most have `unique_together` constraints scoped to the household.

### URL structure

```
/                  → accounts (home, register)
/accounts/         → Django auth (login, logout)
/households/       → household selection
/tasks/            → task CRUD + toggle status
/meals/            → meal plan CRUD + recipe CRUD
/shopping/         → shopping list CRUD + toggle bought
/admin/            → Django admin
```

### Frontend

Server-rendered Django templates with Bootstrap 5.3 (CDN). No JavaScript framework. Forms use Django form classes with Bootstrap CSS classes injected via `__init__`.

### Deployment

- `Procfile`: `web: gunicorn wochi.wsgi`
- `build.sh`: installs deps, collects static, runs migrations, optionally creates superuser via env vars (`CREATE_SUPERUSER`, `DJANGO_SUPERUSER_*`)
- WhiteNoise serves static files in production

## Working Rules for Claude

- Always analyze relevant files before making changes
- Propose a short plan before implementing
- Change only the minimal necessary code
- Do not refactor unrelated parts of the codebase
- Follow existing patterns and naming conventions
- Ask for clarification if something is unclear

When modifying models:
- Explain the impact of changes
- Do not remove or rename fields without explicit instruction
- Mention required migrations

When adding features:
- Update views, forms, templates, and tests consistently
- Keep business logic out of templates

## Critical Rule: Household Isolation

All data access MUST be scoped to the current household.

- Always use `get_current_household(user)`
- Never query models without filtering by household
- Prevent cross-household data access at all costs
- When in doubt, double-check query scoping

This is a core security requirement.

## Performance Guidelines

- Avoid N+1 queries
- Use `select_related` and `prefetch_related` where appropriate
- Prefer queryset optimization over Python loops
- Keep database queries minimal and efficient

## Testing

- Always add tests for new features
- Cover both success and failure cases
- Do not break existing tests
- Use Django TestCase

## Frontend Rules

- Use Django templates only (no JS frameworks)
- Keep templates simple and readable
- Use Bootstrap 5.3 classes consistently
- Handle logic in views, not templates
- Forms must use Django form classes

## Common Pitfalls to Avoid

- Do not duplicate business logic across apps
- Do not introduce unnecessary abstraction
- Do not bypass Django forms for validation
- Do not mix household data
- Do not introduce breaking changes without explanation

## Code Style

- Prefer clear and simple solutions over clever ones
- Use descriptive variable and function names
- Follow Django conventions
- Keep views thin, move logic to models/services