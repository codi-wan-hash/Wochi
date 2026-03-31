def get_current_household(user):
    if user.is_authenticated:
        return user.households.first()
    return None