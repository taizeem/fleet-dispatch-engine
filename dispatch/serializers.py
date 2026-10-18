from rest_framework import serializers
from django.utils import timezone
from .models import RideRequest, Driver, Rider, RideRequestStatus


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
        attrs['timestamp_iso'] = attrs['timestamp'].isoformat()
        return attrs


class RideRequestCreateSerializer(serializers.Serializer):
    rider_id = serializers.UUIDField(required=True)
    pickup_latitude = serializers.FloatField(required=True, min_value=-90.0, max_value=90.0)
    pickup_longitude = serializers.FloatField(required=True, min_value=-180.0, max_value=180.0)
    dropoff_latitude = serializers.FloatField(required=True, min_value=-90.0, max_value=90.0)
    dropoff_longitude = serializers.FloatField(required=True, min_value=-180.0, max_value=180.0)

    def validate_rider_id(self, value):
        if not Rider.objects.filter(id=value).exists():
            raise serializers.ValidationError('Rider does not exist.')
        return value


class RideRequestDetailSerializer(serializers.ModelSerializer):
    pickup_coordinates = serializers.SerializerMethodField()
    dropoff_coordinates = serializers.SerializerMethodField()
    driver_name = serializers.CharField(source='driver.name', read_only=True, default=None)

    class Meta:
        model = RideRequest
        fields = [
            'id',
            'rider',
            'driver',
            'driver_name',
            'status',
            'pickup_coordinates',
            'dropoff_coordinates',
            'created_at',
            'updated_at',
        ]

    def get_pickup_coordinates(self, obj):
        return {'latitude': obj.pickup_location.y, 'longitude': obj.pickup_location.x}

    def get_dropoff_coordinates(self, obj):
        return {'latitude': obj.dropoff_location.y, 'longitude': obj.dropoff_location.x}