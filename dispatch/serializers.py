from rest_framework import serializers
from django.utils import timezone


class DriverLocationPingSerializer(serializers.Serializer):
    driver_id = serializers.UUIDField(required=True)
    latitude = serializers.FloatField(
        required=True,
        min_value=-90.0,
        max_value=90.0,
    )
    longitude = serializers.FloatField(
        required=True,
        min_value=-180.0,
        max_value=180.0,
    )
    timestamp = serializers.DateTimeField(
        required=False,
        default=timezone.now,
    )

    def validate(self, attrs):
        # Format timestamp to ISO 8601 string for Kafka serialization
        attrs['timestamp_iso'] = attrs['timestamp'].isoformat()
        return attrs