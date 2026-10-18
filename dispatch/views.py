from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.gis.geos import Point

from .models import RideRequest, RideRequestStatus
from .serializers import (
    DriverLocationPingSerializer,
    RideRequestCreateSerializer,
    RideRequestDetailSerializer,
    OfferResponseSerializer,
    DriverLifecycleActionSerializer,
    StartTripSerializer,
)
from .kafka_producer import KafkaProducerService
from .services.dispatcher import DispatcherService
from .services.lifecycle import RideLifecycleService


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

        ride = RideRequest.objects.create(
            rider_id=data['rider_id'],
            pickup_location=pickup_point,
            dropoff_location=dropoff_point,
            status=RideRequestStatus.REQUESTED,
        )

        dispatcher = DispatcherService()
        ride, target_driver, strategy = dispatcher.dispatch_ride(str(ride.id))

        response_data = RideRequestDetailSerializer(ride).data
        response_data['dispatch_strategy'] = strategy
        response_data['target_driver'] = str(target_driver.id) if target_driver else None
        response_data['is_driver_assigned'] = target_driver is not None

        return Response(response_data, status=status.HTTP_201_CREATED)


class OfferResponseView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = OfferResponseSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        lifecycle = RideLifecycleService()
        result = lifecycle.respond_to_offer(
            ride_id=str(data['ride_id']),
            driver_id=str(data['driver_id']),
            action=data['action'],
        )
        return Response(result, status=status.HTTP_200_OK)


class DriverArrivedView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = DriverLifecycleActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        lifecycle = RideLifecycleService()
        ride = lifecycle.mark_driver_arrived(
            ride_id=str(data['ride_id']),
            driver_id=str(data['driver_id']),
        )
        return Response(RideRequestDetailSerializer(ride).data, status=status.HTTP_200_OK)


class StartTripView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = StartTripSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        lifecycle = RideLifecycleService()
        ride = lifecycle.start_trip(
            ride_id=str(data['ride_id']),
            driver_id=str(data['driver_id']),
            entered_otp=data['otp'],
        )
        return Response(RideRequestDetailSerializer(ride).data, status=status.HTTP_200_OK)


class CompleteTripView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = DriverLifecycleActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        lifecycle = RideLifecycleService()
        ride = lifecycle.complete_trip(
            ride_id=str(data['ride_id']),
            driver_id=str(data['driver_id']),
        )
        return Response(RideRequestDetailSerializer(ride).data, status=status.HTTP_200_OK)