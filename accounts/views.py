from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from households.utils import get_current_household

@login_required
def home(request):
    household = get_current_household(request.user)
    return render(request, "home.html", {"household": household})
