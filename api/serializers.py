from django.contrib.auth import get_user_model
from rest_framework import serializers

from households.models import Household
from tasks.models import Task
from meals.models import Recipe, Ingredient, MealPlan
from shopping.models import ShoppingItem, Store, ShoppingSession

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["username", "email", "password"]

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data["username"],
            email=validated_data.get("email", ""),
            password=validated_data["password"],
        )


class HouseholdSerializer(serializers.ModelSerializer):
    members = UserSerializer(many=True, read_only=True)

    class Meta:
        model = Household
        fields = ["id", "name", "members", "invite_token", "created_at"]


class TaskSerializer(serializers.ModelSerializer):
    assigned_to = UserSerializer(many=True, read_only=True)
    assigned_to_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=User.objects.none(), write_only=True,
        source="assigned_to", required=False
    )
    created_by = UserSerializer(read_only=True)

    class Meta:
        model = Task
        fields = [
            "id", "title", "description", "due_date", "priority",
            "status", "assigned_to", "assigned_to_ids", "created_by", "created_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request:
            from households.utils import get_current_household
            household = get_current_household(request.user)
            if household:
                self.fields["assigned_to_ids"].child_relation.queryset = household.members.all()

    def create(self, validated_data):
        assigned = validated_data.pop("assigned_to", [])
        task = Task.objects.create(**validated_data)
        task.assigned_to.set(assigned)
        return task

    def update(self, instance, validated_data):
        assigned = validated_data.pop("assigned_to", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if assigned is not None:
            instance.assigned_to.set(assigned)
        return instance


class IngredientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ingredient
        fields = ["id", "name", "quantity"]


class RecipeSerializer(serializers.ModelSerializer):
    ingredients = IngredientSerializer(many=True, read_only=True)
    created_by = UserSerializer(read_only=True)

    class Meta:
        model = Recipe
        fields = ["id", "title", "notes", "instructions", "ingredients", "created_by", "created_at"]
        read_only_fields = ["created_by", "created_at"]


class MealPlanSerializer(serializers.ModelSerializer):
    recipe = RecipeSerializer(read_only=True)
    recipe_id = serializers.PrimaryKeyRelatedField(
        queryset=Recipe.objects.none(), write_only=True, source="recipe"
    )
    assigned_to = UserSerializer(read_only=True)
    assigned_to_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), write_only=True, source="assigned_to",
        required=False, allow_null=True
    )

    class Meta:
        model = MealPlan
        fields = [
            "id", "date", "meal_type", "recipe", "recipe_id",
            "assigned_to", "assigned_to_id", "created_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request:
            from households.utils import get_current_household
            household = get_current_household(request.user)
            if household:
                self.fields["recipe_id"].queryset = Recipe.objects.filter(household=household)
                self.fields["assigned_to_id"].queryset = household.members.all()


class ShoppingItemSerializer(serializers.ModelSerializer):
    added_by = UserSerializer(read_only=True)

    class Meta:
        model = ShoppingItem
        fields = ["id", "name", "quantity", "is_bought", "added_by", "created_at"]


class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ["id", "name", "location", "created_at"]


class ShoppingSessionSerializer(serializers.ModelSerializer):
    store = StoreSerializer(read_only=True)
    started_by = UserSerializer(read_only=True)

    class Meta:
        model = ShoppingSession
        fields = ["id", "store", "started_by", "started_at", "ended_at", "is_active", "check_counter"]
