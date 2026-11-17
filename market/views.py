from django.conf import settings
from django.shortcuts import render


def profile_page(request):
    return render(request, "market/profile.html")


def dashboard(request):
    return render(
        request,
        "market/dashboard.html",
        {"coins": settings.DEFAULT_COINS, "vs": settings.DEFAULT_VS_CURRENCY},
    )
