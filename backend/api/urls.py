from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health),
    path("demand-planning/demand-forecast-v2", views.demand_forecast_v2),
    path("demand-planning/bakeoff", views.bakeoff_leaderboard),
    path("demand-planning/market-target", views.market_target),
    path("production/units", views.production_units),
    path("production/materials", views.production_materials),
]
