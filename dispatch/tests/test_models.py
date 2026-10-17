from django.test import TestCase
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.contrib.gis.db.models.functions import Distance
from django.utils import timezone
from dispatch.models import (
    Driver,
    DriverStatus,
    DriverLocation,
    Rider,
    RideRequest,
    RideRequestStatus,
)


class SpatialModelTests(TestCase):
    def setUp(self):
        # Coordinates in (Longitude, Latitude)
        # Times Square, NYC: (-73.9855, 40.7580)
        self.times_square = Point(-73.9855, 40.7580, srid=4326)
        # Empire State Building, NYC: (-73.9857, 40.7484) ~1.07 km south
        self.empire_state = Point(-73.9857, 40.7484, srid=4326)
        # Brooklyn Bridge: (-73.9969, 40.7061) ~5.8 km south
        self.brooklyn_bridge = Point(-73.9969, 40.7061, srid=4326)

        self.driver = Driver.objects.create(
            name='John Doe',
            status=DriverStatus.ONLINE,
        )
        self.rider = Rider.objects.create(
            name='Alice Smith',
        )

    def test_driver_creation_and_defaults(self):
        driver = Driver.objects.create(name='Jane Smith')
        self.assertEqual(driver.status, DriverStatus.OFFLINE)
        self.assertIsNotNone(driver.id)
        self.assertIn('Jane Smith', str(driver))

    def test_driver_location_spatial_point(self):
        location_record = DriverLocation.objects.create(
            driver=self.driver,
            location=self.times_square,
            recorded_at=timezone.now(),
        )
        self.assertEqual(location_record.location.x, -73.9855)
        self.assertEqual(location_record.location.y, 40.7580)
        self.assertEqual(location_record.location.srid, 4326)
        self.assertIn(self.driver.name, str(location_record))

    def test_ride_request_creation_and_spatial_distance(self):
        ride = RideRequest.objects.create(
            rider=self.rider,
            driver=self.driver,
            pickup_location=self.times_square,
            dropoff_location=self.empire_state,
            status=RideRequestStatus.REQUESTED,
        )
        self.assertEqual(ride.status, RideRequestStatus.REQUESTED)
        self.assertEqual(ride.driver, self.driver)
        self.assertEqual(ride.rider, self.rider)

        # Calculate spherical distance using PostGIS geography function
        annotated_ride = (
            RideRequest.objects.annotate(
                trip_distance=Distance('pickup_location', 'dropoff_location')
            )
            .get(id=ride.id)
        )
        # Approximate straight line distance between Times Square and Empire State is ~1070 meters
        distance_meters = annotated_ride.trip_distance.m
        self.assertGreater(distance_meters, 1000)
        self.assertLess(distance_meters, 1200)

    def test_spatial_proximity_query(self):
        # Create a driver location at Empire State
        DriverLocation.objects.create(
            driver=self.driver,
            location=self.empire_state,
        )

        # Query drivers located within 2km of Times Square
        nearby_pings = DriverLocation.objects.filter(
            location__distance_lte=(self.times_square, D(km=2))
        )
        self.assertEqual(nearby_pings.count(), 1)
        self.assertEqual(nearby_pings.first().driver, self.driver)

        # Query drivers located within 500m of Times Square (should exclude Empire State)
        far_pings = DriverLocation.objects.filter(
            location__distance_lte=(self.times_square, D(m=500))
        )
        self.assertEqual(far_pings.count(), 0)

    def test_cascade_delete_driver_deletes_locations(self):
        DriverLocation.objects.create(
            driver=self.driver,
            location=self.times_square,
        )
        self.assertEqual(DriverLocation.objects.filter(driver=self.driver).count(), 1)
        self.driver.delete()
        self.assertEqual(DriverLocation.objects.filter(driver_id=self.driver.id).count(), 0)