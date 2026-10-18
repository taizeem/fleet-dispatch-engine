import json
import logging
from typing import Optional, Tuple, List
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.contrib.gis.measure import D
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
import redis

from dispatch.models import Driver, DriverStatus, DriverLocation, RideRequest, RideRequestStatus
from dispatch.redis_client import RedisClientService

logger = logging.getLogger(__name__)


class DispatcherService:
    DISPATCH_RADIUS_KM = 3.0
    CANDIDATE_LIMIT = 5
    OFFER_TIMEOUT_SECONDS = 15

    def __init__(self):
        self.redis_service = RedisClientService.get_instance()
        self.channel_layer = get_channel_layer()

    def dispatch_ride(self, ride_request_id: str) -> Tuple[RideRequest, Optional[Driver], str]:
        ride = RideRequest.objects.select_related('rider').get(id=ride_request_id)
        if ride.status not in (RideRequestStatus.REQUESTED, RideRequestStatus.OFFERED):
            return ride, ride.driver, 'ALREADY_ASSIGNED'

        pickup_point = ride.pickup_location
        pickup_lon = pickup_point.x
        pickup_lat = pickup_point.y

        # 1. Fetch nearby candidates from Redis GEO
        candidates: List[dict] = []
        try:
            candidates = self.redis_service.find_nearby_drivers(
                longitude=pickup_lon,
                latitude=pickup_lat,
                radius_km=self.DISPATCH_RADIUS_KM,
                limit=self.CANDIDATE_LIMIT,
            )
        except (redis.RedisError, Exception) as exc:
            logger.warning('Redis geospatial search failed: %s', exc)

        # 2. Fallback to PostGIS if Redis returned zero candidates or threw error
        if not candidates:
            return self._dispatch_postgis_fallback(ride, pickup_point)

        # 3. Filter candidates to ensure they are confirmed ONLINE in database
        candidate_ids = [c['driver_id'] for c in candidates]
        online_driver_ids = set(
            Driver.objects.filter(id__in=candidate_ids, status=DriverStatus.ONLINE)
            .values_list('id', flat=True)
        )
        online_candidates = [c for c in candidates if uuid_or_str(c['driver_id']) in online_driver_ids]

        if not online_candidates:
            return self._dispatch_postgis_fallback(ride, pickup_point)

        # 4. Initiate 15-second Offer Cascade starting with the closest candidate
        return self._offer_to_next_candidate(ride, online_candidates, current_index=0)

    def _offer_to_next_candidate(self, ride: RideRequest, candidates: list, current_index: int) -> Tuple[RideRequest, Optional[Driver], str]:
        if current_index >= len(candidates):
            ride.status = RideRequestStatus.REQUESTED
            ride.offered_driver = None
            ride.save(update_fields=['status', 'offered_driver', 'updated_at'])
            return ride, None, 'NO_DRIVER_FOUND'

        target_candidate = candidates[current_index]
        target_driver_id = str(target_candidate['driver_id'])

        driver = Driver.objects.filter(id=target_driver_id, status=DriverStatus.ONLINE).first()
        if not driver:
            # Skip driver if they went offline/busy between search and offer
            return self._offer_to_next_candidate(ride, candidates, current_index + 1)

        with transaction.atomic():
            ride.offered_driver = driver
            ride.status = RideRequestStatus.OFFERED
            ride.save(update_fields=['offered_driver', 'status', 'updated_at'])

        # Store offer state in Redis with a 15-second TTL
        offer_key = f'ride:{ride.id}:offer'
        offer_data = {
            'ride_id': str(ride.id),
            'driver_id': target_driver_id,
            'current_index': current_index,
            'candidates': candidates,
        }
        self.redis_service.client.setex(
            offer_key,
            self.OFFER_TIMEOUT_SECONDS,
            json.dumps(offer_data),
        )

        # Broadcast offer event to the Driver's WebSocket channel group
        self._broadcast_driver_offer(ride, driver, target_candidate['distance_km'])

        return ride, driver, 'OFFER_SENT'

    def cascade_next_driver(self, ride_request_id: str) -> Tuple[RideRequest, Optional[Driver], str]:
        """
        Called when a driver explicitly declines or an offer times out.
        """
        ride = RideRequest.objects.get(id=ride_request_id)
        if ride.status != RideRequestStatus.OFFERED:
            return ride, ride.driver, 'ALREADY_HANDLED'

        offer_key = f'ride:{ride.id}:offer'
        raw_offer = self.redis_service.client.get(offer_key)

        if not raw_offer:
            # Fallback to fresh dispatch if offer cache was evicted
            return self.dispatch_ride(str(ride.id))

        offer_data = json.loads(raw_offer)
        candidates = offer_data.get('candidates', [])
        next_index = offer_data.get('current_index', 0) + 1

        return self._offer_to_next_candidate(ride, candidates, next_index)

    def _broadcast_driver_offer(self, ride: RideRequest, driver: Driver, distance_km: float):
        group_name = f'driver_{driver.id}'
        message = {
            'type': 'driver_offer',
            'data': {
                'type': 'ride_offer',
                'ride_id': str(ride.id),
                'rider_name': ride.rider.name,
                'pickup_coordinates': {'lat': ride.pickup_location.y, 'lon': ride.pickup_location.x},
                'dropoff_coordinates': {'lat': ride.dropoff_location.y, 'lon': ride.dropoff_location.x},
                'distance_to_pickup_km': round(distance_km, 2),
                'timeout_seconds': self.OFFER_TIMEOUT_SECONDS,
            },
        }
        try:
            async_to_sync(self.channel_layer.group_send)(group_name, message)
        except Exception as e:
            logger.error('Failed to broadcast offer to driver %s: %s', driver.id, e)

    def _dispatch_postgis_fallback(self, ride: RideRequest, pickup_point: Point) -> Tuple[RideRequest, Optional[Driver], str]:
        with transaction.atomic():
            nearby_loc = (
                DriverLocation.objects.filter(
                    driver__status=DriverStatus.ONLINE,
                    location__distance_lte=(pickup_point, D(km=self.DISPATCH_RADIUS_KM)),
                )
                .annotate(distance=Distance('location', pickup_point))
                .order_by('distance')
                .select_related('driver')
                .first()
            )

            if nearby_loc:
                matched_driver = nearby_loc.driver
                matched_driver.status = DriverStatus.BUSY
                matched_driver.save(update_fields=['status', 'updated_at'])

                ride.driver = matched_driver
                ride.offered_driver = None
                ride.status = RideRequestStatus.ACCEPTED
                ride.save(update_fields=['driver', 'offered_driver', 'status', 'updated_at'])
                return ride, matched_driver, 'POSTGIS_FALLBACK'

        ride.status = RideRequestStatus.REQUESTED
        ride.save(update_fields=['status', 'updated_at'])
        return ride, None, 'NO_DRIVER_FOUND'


def uuid_or_str(val):
    import uuid
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError):
        return val