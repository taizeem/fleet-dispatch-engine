from django.urls import re_path
from .consumers import RideTrackingConsumer

websocket_urlpatterns = [
    re_path(r'^ws/rides/(?P<ride_id>[0-9a-fA-F-]+)/$', RideTrackingConsumer.as_asgi()),
]