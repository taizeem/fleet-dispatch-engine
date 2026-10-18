import logging
from typing import Optional, Tuple
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

    def __init__(self):
        self.redis_service = RedisClientService.get_instance()

    def dispatch_ride(self, ride_request_id: str) -> Tuple[RideRequest, Optional[Driver], str]:
        """
        Attempts to match and assign the closest online driver to a RideRequest.
        Returns: (ride_request, assigned_driver, strategy_used)
        """
        ride = RideRequest.objects.select_related('rider').get(id=ride_request_id)
        if ride.status != RideRequestStatus.REQUESTED:
            return ride, ride.driver, 'ALREADY_ASSIGNED'

        pickup_point = ride.pickup_location
        pickup_lon = pickup_point.x
        pickup_lat = pickup_point.y

        # Strategy 1: Sub-millisecond lookup via Redis GEO
        try:
            nearby_candidates = self.redis_service.find_nearby_drivers(
                longitude=pickup_lon,
                latitude=pickup_lat,
                radius_km=self.DISPATCH_RADIUS_KM,
                limit=self.CANDIDATE_LIMIT,
            )
            assigned_driver = self._assign_from_redis_candidates(ride, nearby_candidates)
            if assigned_driver:
                return ride, assigned_driver, 'REDIS_GEO'
        except (redis.RedisError, Exception) as exc:
            logger.warning('Redis geospatial lookup failed (%s). Falling back to PostGIS spatial query.', exc)

        # Strategy 2: Resilient PostGIS Fallback
        assigned_driver = self._assign_from_postgis_fallback(ride, pickup_point)
        if assigned_driver:
            return ride, assigned_driver, 'POSTGIS_FALLBACK'

        return ride, None, 'NO_DRIVER_FOUND'

    def _assign_from_redis_candidates(self, ride: RideRequest, candidates: list) -> Optional[Driver]:
        if not candidates:
            return None

        candidate_ids = [c['driver_id'] for c in candidates]

        with transaction.atomic():
            # Query and lock available online drivers matching Redis candidates
            online_drivers = {
                str(d.id): d
                for d in Driver.objects.select_for_update()
                .filter(id__in=candidate_ids, status=DriverStatus.ONLINE)
            }

            # Pick the closest candidate that is confirmed online
            for candidate in candidates:
                cand_id = candidate['driver_id']
                if cand_id in online_drivers:
                    matched_driver = online_drivers[cand_id]
                    matched_driver.status = DriverStatus.BUSY
                    matched_driver.save(update_fields=['status', 'updated_at'])

                    ride.driver = matched_driver
                    ride.status = RideRequestStatus.ASSIGNED
                    ride.save(update_fields=['driver', 'status', 'updated_at'])
                    return matched_driver

        return None

    def _assign_from_postgis_fallback(self, ride: RideRequest, pickup_point: Point) -> Optional[Driver]:
        """
        Spatial fallback in PostGIS: finds the closest online driver based on their most recent location ping.
        """
        with transaction.atomic():
            # Subquery the closest online driver whose latest ping is within 3km
            nearby_driver_location = (
                DriverLocation.objects.filter(
                    driver__status=DriverStatus.ONLINE,
                    location__distance_lte=(pickup_point, D(km=self.DISPATCH_RADIUS_KM)),
                )
                .annotate(distance=Distance('location', pickup_point))
                .order_by('distance')
                .select_related('driver')
                .first()
            )

            if nearby_driver_location:
                matched_driver = nearby_driver_location.driver
                # Lock driver
                driver_to_lock = (
                    Driver.objects.select_for_update()
                    .filter(id=matched_driver.id, status=DriverStatus.ONLINE)
                    .first()
                )
                if driver_to_lock:
                    driver_to_lock.status = DriverStatus.BUSY
                    driver_to_lock.save(update_fields=['status', 'updated_at'])

                    ride.driver = driver_to_lock
                    ride.status = RideRequestStatus.ASSIGNED
                    ride.save(update_fields=['driver', 'status', 'updated_at'])
                    return driver_to_lock

        return None