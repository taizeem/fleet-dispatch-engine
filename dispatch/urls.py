from django.urls import path
from .views import DriverLocationPingView, RideRequestCreateView

app_name = 'dispatch'

urlpatterns = [
    path('api/v1/drivers/location-ping/', DriverLocationPingView.as_view(), name='driver-location-ping'),
    path('api/v1/rides/request/', RideRequestCreateView.as_view(), name='ride-request-create'),
]