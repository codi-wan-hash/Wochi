from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from households.models import Household
from tasks.models import Task
from meals.models import Recipe, Ingredient, MealPlan
from shopping.models import ShoppingItem, Store, ShoppingSession

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Andere Haushaltsmitglieder – bewusst ohne E-Mail-Adresse.

    Jeder, der per Einladungslink beitritt, sieht diese Daten; die Adresse
    gibt es nur für das eigene Konto (MeSerializer).
    """

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name"]


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name"]


class RegisterSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["username", "email", "password"]

    def validate_username(self, value):
        value = value.strip()
        # Benutzernamen sind in Django case-sensitiv; „Anna" und „anna" als
        # zwei Konten führen am Handy zu Verwechslungen beim Anmelden.
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Dieser Benutzername ist schon vergeben.")
        return value

    def validate_email(self, value):
        value = value.strip()
        # Eindeutig, weil Passwort-Reset und Anmeldung per E-Mail sonst nicht
        # wissen, welches Konto gemeint ist.
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Diese E-Mail-Adresse wird bereits verwendet.")
        return value

    def validate(self, attrs):
        candidate = User(username=attrs.get("username", ""), email=attrs.get("email", ""))
        try:
            password_validation.validate_password(attrs.get("password", ""), candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
        )


class HouseholdSerializer(serializers.ModelSerializer):
    members = UserSerializer(many=True, read_only=True)
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = Household
        fields = ["id", "name", "members", "invite_token", "created_at", "is_current"]

    def get_is_current(self, household):
        return household.pk == self.context.get("current_id")


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
            "status", "recurrence", "assigned_to", "assigned_to_ids", "created_by", "created_at",
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

    def validate_title(self, value):
        value = value.strip()
        household = self.context.get("household")
        if household is not None:
            duplicates = Recipe.objects.filter(household=household, title__iexact=value)
            if self.instance is not None:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise serializers.ValidationError("Es gibt schon ein Rezept mit diesem Namen.")
        return value


class MealPlanSerializer(serializers.ModelSerializer):
    recipe = RecipeSerializer(read_only=True)
    recipe_id = serializers.PrimaryKeyRelatedField(
        queryset=Recipe.objects.none(), write_only=True, source="recipe", required=False
    )
    # Alternativ zu recipe_id: ein Gericht einfach per Name planen („Reste",
    # „Pizza bestellen"). Gibt es kein Rezept mit dem Namen, wird es angelegt.
    recipe_title = serializers.CharField(write_only=True, required=False, max_length=200)
    assigned_to = UserSerializer(read_only=True)
    assigned_to_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.none(), write_only=True, source="assigned_to",
        required=False, allow_null=True
    )

    class Meta:
        model = MealPlan
        fields = [
            "id", "date", "meal_type", "recipe", "recipe_id", "recipe_title",
            "assigned_to", "assigned_to_id", "created_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        household = self.context.get("household")
        if household is not None:
            self.fields["recipe_id"].queryset = Recipe.objects.filter(household=household)
            self.fields["assigned_to_id"].queryset = household.members.all()

    def validate(self, attrs):
        household = self.context.get("household")
        title = (attrs.pop("recipe_title", "") or "").strip()

        date = attrs.get("date", getattr(self.instance, "date", None))
        meal_type = attrs.get("meal_type", getattr(self.instance, "meal_type", None))
        if household is not None and date and meal_type:
            taken = MealPlan.objects.filter(household=household, date=date, meal_type=meal_type)
            if self.instance is not None:
                taken = taken.exclude(pk=self.instance.pk)
            if taken.exists():
                label = dict(MealPlan.MEAL_TYPE_CHOICES).get(meal_type, meal_type)
                raise serializers.ValidationError(
                    {"non_field_errors": [f"Für diesen Tag ist schon ein {label} geplant."]}
                )

        if "recipe" not in attrs and title and household is not None:
            # Erst nach allen Prüfungen anlegen, damit ein abgelehnter
            # Request kein verwaistes Rezept hinterlässt.
            recipe = Recipe.objects.filter(household=household, title__iexact=title).first()
            if recipe is None:
                request = self.context.get("request")
                recipe = Recipe.objects.create(
                    household=household, title=title,
                    created_by=request.user if request else None,
                )
            attrs["recipe"] = recipe
        if self.instance is None and "recipe" not in attrs:
            raise serializers.ValidationError({"recipe_id": "Bitte ein Gericht auswählen oder eingeben."})
        return attrs


class ShoppingItemSerializer(serializers.ModelSerializer):
    added_by = UserSerializer(read_only=True)

    class Meta:
        model = ShoppingItem
        fields = ["id", "client_id", "name", "quantity", "is_bought", "added_by", "created_at"]


class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ["id", "name", "location", "created_at"]


class ShoppingSessionSerializer(serializers.ModelSerializer):
    store = StoreSerializer(read_only=True)
    started_by = UserSerializer(read_only=True)

    class Meta:
        model = ShoppingSession
        fields = ["id", "client_id", "store", "started_by", "started_at", "ended_at", "is_active", "check_counter"]
