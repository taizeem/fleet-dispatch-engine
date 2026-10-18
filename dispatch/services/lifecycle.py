from decimal import Decimal
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.contrib.gis.db.models.functions import Distance
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from dispatch.models import Driver, DriverStatus, RideRequest, RideRequestStatus
from dispatch.redis_client import RedisClientService
from dispatch.services.dispatcher import DispatcherService


class RideLifecycleService:
    BASE_FARE = Decimal('3.00')
    PER_KM_RATE = Decimal('1.50')

    def __init__(self):
        self.channel_layer = get_channel_layer()
        self.redis_service = RedisClientService.get_instance()

    def respond_to_offer(self, ride_id: str, driver_id: str, action: str) -> dict:
        ride = RideRequest.objects.select_related('rider', 'offered_driver').get(id=ride_id)

        if ride.status != RideRequestStatus.OFFERED:
            raise ValidationError(f'Ride is not in OFFERED state (current: {ride.status}).')

        if not ride.offered_driver or str(ride.offered_driver.id) != str(driver_id):
            raise ValidationError('Driver does not match the currently offered candidate.')

        if action.lower() == 'decline':
            # Remove active offer key from Redis and cascade to next driver
            self.redis_service.client.delete(f'ride:{ride.id}:offer')
            dispatcher = DispatcherService()
            ride, next_driver, strategy = dispatcher.cascade_next_driver(str(ride.id))
            return {
                'status': 'declined',
                'ride_id': str(ride.id),
                'cascaded_to': str(next_driver.id) if next_driver else None,
                'strategy': strategy,
            }

        if action.lower() == 'accept':
            with transaction.atomic():
                driver = Driver.objects.select_for_update().get(id=driver_id)
                driver.status = DriverStatus.BUSY
                driver.save(update_fields=['status', 'updated_at'])

                ride.driver = driver
                ride.offered_driver = None
                ride.status = RideRequestStatus.ACCEPTED
                ride.save(update_fields=['driver', 'offered_driver', 'status', 'updated_at'])

            # Delete Redis offer key
            self.redis_service.client.delete(f'ride:{ride.id}:offer')

            # Notify Rider over WebSockets that Driver accepted (including security OTP)
            self._broadcast_to_ride(
                ride_id=ride.id,
                payload={
                    'type': 'driver_accepted',
                    'ride_id': str(ride.id),
                    'driver_id': str(driver.id),
                    'driver_name': driver.name,
                    'otp': ride.otp,
                    'message': f'{driver.name} accepted your ride! Give OTP {ride.otp} upon boarding.',
                },
            )

            return {
                'status': 'accepted',
                'ride_id': str(ride.id),
                'driver_id': str(driver.id),
                'driver_name': driver.name,
                'otp': ride.otp,
            }

        raise ValidationError('Action must be either "accept" or "decline".')

    def mark_driver_arrived(self, ride_id: str, driver_id: str) -> RideRequest:
        ride = RideRequest.objects.get(id=ride_id)

        if ride.status != RideRequestStatus.ACCEPTED:
            raise ValidationError(f'Cannot mark arrived from status {ride.status}. Must be ACCEPTED.')

        if not ride.driver or str(ride.driver.id) != str(driver_id):
            raise ValidationError('Unauthorized driver for this ride.')

        ride.status = RideRequestStatus.ARRIVED
        ride.save(update_fields=['status', 'updated_at'])

        # Notify Rider of driver arrival
        self._broadcast_to_ride(
            ride_id=ride.id,
            payload={
                'type': 'driver_arrived',
                'ride_id': str(ride.id),
                'message': f'Your driver {ride.driver.name} has arrived at pickup location!',
            },
        )
        return ride

    def start_trip(self, ride_id: str, driver_id: str, entered_otp: str) -> RideRequest:
        ride = RideRequest.objects.get(id=ride_id)

        if ride.status != RideRequestStatus.ARRIVED:
            raise ValidationError(f'Cannot start trip from status {ride.status}. Driver must mark ARRIVED first.')

        if not ride.driver or str(ride.driver.id) != str(driver_id):
            raise ValidationError('Unauthorized driver for this ride.')

        if str(ride.otp).strip() != str(entered_otp).strip():
            raise ValidationError('Invalid OTP. Please check with rider.')

        ride.status = RideRequestStatus.IN_PROGRESS
        ride.save(update_fields=['status', 'updated_at'])

        self._broadcast_to_ride(
            ride_id=ride.id,
            payload={
                'type': 'trip_started',
                'ride_id': str(ride.id),
                'message': 'Trip has officially started! Enjoy your ride.',
            },
        )
        return ride

    def complete_trip(self, ride_id: str, driver_id: str) -> RideRequest:
        ride = RideRequest.objects.get(id=ride_id)

        if ride.status != RideRequestStatus.IN_PROGRESS:
            raise ValidationError(f'Cannot complete trip from status {ride.status}. Trip must be IN_PROGRESS.')

        if not ride.driver or str(ride.driver.id) != str(driver_id):
            raise ValidationError('Unauthorized driver for this ride.')

        # Calculate spherical trip distance using PostGIS geography calculation
        annotated_ride = (
            RideRequest.objects.annotate(trip_dist=Distance('pickup_location', 'dropoff_location'))
            .get(id=ride.id)
        )
        distance_meters = annotated_ride.trip_dist.m
        distance_km = round(distance_meters / 1000.0, 2)
        fare = self.BASE_FARE + (self.PER_KM_RATE * Decimal(str(distance_km)))

        with transaction.atomic():
            driver = Driver.objects.select_for_update().get(id=driver_id)
            driver.status = DriverStatus.ONLINE
            driver.save(update_fields=['status', 'updated_at'])

            ride.status = RideRequestStatus.COMPLETED
            ride.distance_km = distance_km
            ride.fare_amount = fare
            ride.save(update_fields=['status', 'distance_km', 'fare_amount', 'updated_at'])

        # Notify Rider of trip completion and final fare receipt
        self._broadcast_to_ride(
            ride_id=ride.id,
            payload={
                'type': 'trip_completed',
                'ride_id': str(ride.id),
                'distance_km': distance_km,
                'fare_amount': float(fare),
                'message': f'Trip completed! Total: ${fare:.2f} for {distance_km} km.',
            },
        )
        return ride

    def _broadcast_to_ride(self, ride_id: str, payload: dict):
        group_name = f'ride_{ride_id}'
        try:
            async_to_sync(self.channel_layer.group_send)(
                group_name,
                {
                    'type': 'driver_location_update',
                    'data': payload,
                },
            )
        except Exception as e:
            pass