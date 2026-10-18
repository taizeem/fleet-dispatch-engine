from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.gis.geos import Point

from .models import RideRequest, RideRequestStatus
from .serializers import (
    DriverLocationPingSerializer,
    RideRequestCreateSerializer,
    RideRequestDetailSerializer,
)
from .kafka_producer import KafkaProducerService
from .services.dispatcher import DispatcherService


class DriverLocationPingView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = DriverLocationPingSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data
        driver_id = str(validated_data['driver_id'])

        payload = {
            'driver_id': driver_id,
            'latitude': validated_data['latitude'],
            'longitude': validated_data['longitude'],
            'timestamp': validated_data['timestamp_iso'],
        }

        producer = KafkaProducerService.get_instance()
        producer.publish_ping(driver_id=driver_id, payload=payload)

        return Response(
            {
                'status': 'accepted',
                'driver_id': driver_id,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class RideRequestCreateView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = RideRequestCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        pickup_point = Point(data['pickup_longitude'], data['pickup_latitude'], srid=4326)
        dropoff_point = Point(data['dropoff_longitude'], data['dropoff_latitude'], srid=4326)

        # 1. Persist the ride request in PostGIS
        ride = RideRequest.objects.create(
            rider_id=data['rider_id'],
            pickup_location=pickup_point,
            dropoff_location=dropoff_point,
            status=RideRequestStatus.REQUESTED,
        )

        # 2. Invoke the Dispatcher Engine
        dispatcher = DispatcherService()
        ride, assigned_driver, strategy = dispatcher.dispatch_ride(str(ride.id))

        response_data = RideRequestDetailSerializer(ride).data
        response_data['dispatch_strategy'] = strategy
        response_data['is_driver_assigned'] = assigned_driver is not None

        return Response(response_data, status=status.HTTP_201_CREATED)