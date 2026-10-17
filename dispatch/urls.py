from django.urls import path
from .views import DriverLocationPingView

app_name = 'dispatch'

urlpatterns = [
    path('api/v1/drivers/location-ping/', DriverLocationPingView.as_view(), name='driver-location-ping'),
]