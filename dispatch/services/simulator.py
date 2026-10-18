import math
import random
from typing import Tuple, Optional
from django.utils import timezone
from dispatch.models import Driver, DriverStatus, RideRequest, RideRequestStatus

EARTH_RADIUS_METERS = 6371000.0


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Returns great-circle distance between two points in meters."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Returns initial compass bearing from point 1 to point 2 in degrees (0-360)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)

    y = math.sin(delta_lambda) * math.cos(phi2)
    x = (math.cos(phi1) * math.sin(phi2) -
         math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda))
    initial_bearing = math.atan2(y, x)
    return (math.degrees(initial_bearing) + 360.0) % 360.0


def project_coordinate(lat: float, lon: float, bearing_deg: float, distance_meters: float) -> Tuple[float, float]:
    """Projects a coordinate along a bearing for a given distance in meters."""
    delta = distance_meters / EARTH_RADIUS_METERS
    theta = math.radians(bearing_deg)
    phi1 = math.radians(lat)
    lambda1 = math.radians(lon)

    phi2 = math.asin(
        math.sin(phi1) * math.cos(delta) +
        math.cos(phi1) * math.sin(delta) * math.cos(theta)
    )
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2)
    )

    return (math.degrees(phi2), (math.degrees(lambda2) + 540.0) % 360.0 - 180.0)


class SimulatedVehicle:
    def __init__(self, driver: Driver, initial_lat: float, initial_lon: float, speed_kmh: float = 35.0):
        self.driver = driver
        self.latitude = initial_lat
        self.longitude = initial_lon
        self.speed_kmh = speed_kmh
        self.current_bearing = random.uniform(0, 360)

    def step(self, delta_seconds: float) -> dict:
        speed_mps = (self.speed_kmh * 1000.0) / 3600.0
        distance_step_meters = speed_mps * delta_seconds

        target_coords = self._get_active_target_coordinates()

        if target_coords:
            # Destination-Seeking Mode: Steer directly toward active target
            target_lat, target_lon = target_coords
            dist_to_target = haversine_distance(self.latitude, self.longitude, target_lat, target_lon)

            if dist_to_target <= distance_step_meters:
                self.latitude = target_lat
                self.longitude = target_lon
            else:
                self.current_bearing = calculate_bearing(self.latitude, self.longitude, target_lat, target_lon)
                self.latitude, self.longitude = project_coordinate(
                    self.latitude, self.longitude, self.current_bearing, distance_step_meters
                )
        else:
            # Wandering Mode: Apply minor random curve perturbation (+/- 15 degrees)
            self.current_bearing = (self.current_bearing + random.uniform(-15.0, 15.0)) % 360.0
            self.latitude, self.longitude = project_coordinate(
                self.latitude, self.longitude, self.current_bearing, distance_step_meters
            )

        return {
            'driver_id': str(self.driver.id),
            'latitude': round(self.latitude, 6),
            'longitude': round(self.longitude, 6),
            'bearing': round(self.current_bearing, 1),
            'speed_kmh': self.speed_kmh,
            'timestamp': timezone.now().isoformat(),
        }

    def _get_active_target_coordinates(self) -> Optional[Tuple[float, float]]:
        active_ride = RideRequest.objects.filter(
            driver=self.driver,
            status__in=[
                RideRequestStatus.ACCEPTED,
                RideRequestStatus.ARRIVED,
                RideRequestStatus.IN_PROGRESS,
            ],
        ).first()

        if not active_ride:
            return None

        # If heading to pickup
        if active_ride.status in (RideRequestStatus.ACCEPTED, RideRequestStatus.ARRIVED):
            return (active_ride.pickup_location.y, active_ride.pickup_location.x)

        # If heading to dropoff
        if active_ride.status == RideRequestStatus.IN_PROGRESS:
            return (active_ride.dropoff_location.y, active_ride.dropoff_location.x)

        return None