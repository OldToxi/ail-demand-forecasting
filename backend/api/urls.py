from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health),
    # AIL demand-forecasting (read-only)
    path("forecast/ui", views.forecast_ui),
    path("forecast/template", views.forecast_template),
    path("forecast/planner", views.forecast_planner_list),
]
