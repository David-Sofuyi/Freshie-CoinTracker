from django.conf import settings
from django.shortcuts import render


def dashboard(request):
    return render(
        request,
        "market/dashboard.html",
        {"coins": settings.DEFAULT_COINS, "vs": settings.DEFAULT_VS_CURRENCY},
    )
