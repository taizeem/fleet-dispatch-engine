from django.urls import path
from .views import (
    DriverLocationPingView,
    RideRequestCreateView,
    OfferResponseView,
    DriverArrivedView,
    StartTripView,
    CompleteTripView,
)

app_name = 'dispatch'

urlpatterns = [
    path('api/v1/drivers/location-ping/', DriverLocationPingView.as_view(), name='driver-location-ping'),
    path('api/v1/rides/request/', RideRequestCreateView.as_view(), name='ride-request-create'),
    path('api/v1/rides/offer-response/', OfferResponseView.as_view(), name='ride-offer-response'),
    path('api/v1/rides/arrived/', DriverArrivedView.as_view(), name='ride-driver-arrived'),
    path('api/v1/rides/start-trip/', StartTripView.as_view(), name='ride-start-trip'),
    path('api/v1/rides/complete-trip/', CompleteTripView.as_view(), name='ride-complete-trip'),
]