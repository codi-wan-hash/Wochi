from django.urls import path

from . import views

urlpatterns = [
    # Push
    path("push/register/", views.register_push_token, name="api_push_register"),
    path("push/unregister/", views.unregister_push_token, name="api_push_unregister"),

    # Auth
    path("auth/register/", views.RegisterView.as_view(), name="api_register"),
    path("auth/login/", views.LoginView.as_view(), name="api_login"),
    path("auth/refresh/", views.RefreshView.as_view(), name="api_refresh"),
    path("auth/me/", views.MeView.as_view(), name="api_me"),
    path("auth/password-reset/", views.PasswordResetRequestView.as_view(), name="api_password_reset"),
    path("auth/password-change/", views.PasswordChangeView.as_view(), name="api_password_change"),
    path("auth/delete-account/", views.DeleteAccountView.as_view(), name="api_delete_account"),

    # Households
    path("households/", views.HouseholdListView.as_view(), name="api_households"),
    path("households/members/", views.household_members, name="api_household_members"),
    path("households/join/", views.join_household, name="api_household_join"),
    path("households/<int:pk>/activate/", views.household_activate, name="api_household_activate"),
    path("households/<int:pk>/leave/", views.household_leave, name="api_household_leave"),
    path("households/<int:pk>/invite/regenerate/", views.household_regenerate_invite, name="api_household_regenerate_invite"),
    path("households/<int:pk>/members/<int:user_id>/remove/", views.household_remove_member, name="api_household_remove_member"),

    # Tasks
    path("tasks/", views.TaskListCreateView.as_view(), name="api_tasks"),
    path("tasks/clear-done/", views.tasks_clear_done, name="api_tasks_clear_done"),
    path("tasks/<int:pk>/", views.TaskDetailView.as_view(), name="api_task_detail"),
    path("tasks/<int:pk>/toggle/", views.task_toggle, name="api_task_toggle"),

    # Meals
    path("meals/", views.MealPlanListCreateView.as_view(), name="api_meals"),
    path("meals/to-shopping/", views.meals_week_to_shopping, name="api_meals_to_shopping"),
    path("meals/<int:pk>/", views.MealPlanDetailView.as_view(), name="api_meal_detail"),

    # Recipes
    path("recipes/", views.RecipeListView.as_view(), name="api_recipes"),
    path("recipes/<int:pk>/", views.RecipeDetailView.as_view(), name="api_recipe_detail"),
    path("recipes/<int:pk>/ingredients/", views.IngredientListCreateView.as_view(), name="api_recipe_ingredients"),
    path("recipes/<int:pk>/to-shopping/", views.recipe_all_ingredients_to_shopping, name="api_recipe_to_shopping"),
    path("recipes/<int:pk>/ai-suggest/", views.recipe_ai_suggest, name="api_recipe_ai_suggest"),
    path("recipes/<int:pk>/apply-suggestion/", views.recipe_apply_suggestion, name="api_recipe_apply_suggestion"),

    # Ingredients
    path("ingredients/<int:pk>/", views.ingredient_detail, name="api_ingredient_delete"),
    path("ingredients/<int:pk>/to-shopping/", views.ingredient_to_shopping, name="api_ingredient_to_shopping"),

    # Shopping
    path("shopping/", views.ShoppingListCreateView.as_view(), name="api_shopping"),
    path("shopping/sync/", views.shopping_sync, name="api_shopping_sync"),
    path("shopping/clear-bought/", views.shopping_clear_bought, name="api_shopping_clear_bought"),
    path("shopping/stores/", views.StoreListCreateView.as_view(), name="api_stores"),
    path("shopping/session/", views.shopping_session_active, name="api_shopping_session"),
    path("shopping/start/", views.shopping_start, name="api_shopping_start"),
    path("shopping/end/", views.shopping_end, name="api_shopping_end"),
    path("shopping/<int:pk>/", views.ShoppingItemDetailView.as_view(), name="api_shopping_detail"),
    path("shopping/<int:pk>/toggle/", views.shopping_toggle, name="api_shopping_toggle"),
    path("shopping/<int:pk>/merge/", views.shopping_merge, name="api_shopping_merge"),
]
