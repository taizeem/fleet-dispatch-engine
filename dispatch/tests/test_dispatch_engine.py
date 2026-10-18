import uuid
from unittest.mock import MagicMock, patch
import redis
from django.test import TestCase
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from dispatch.models import Driver, DriverStatus, DriverLocation, Rider, RideRequest, RideRequestStatus
from dispatch.services.dispatcher import DispatcherService


class DispatcherEngineTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('dispatch:ride-request-create')

        self.rider = Rider.objects.create(name='Alice Wonder')

        # Times Square: (-73.9855, 40.7580)
        self.pickup_point = Point(-73.9855, 40.7580, srid=4326)
        # Central Park South: (-73.9760, 40.7660)
        self.dropoff_point = Point(-73.9760, 40.7660, srid=4326)

        # Driver 1: Closest (approx. 400m away), ONLINE
        self.driver_near_online = Driver.objects.create(
            name='Near Online Driver',
            status=DriverStatus.ONLINE,
        )
        # Driver 2: Medium (approx. 1.2km away), ONLINE
        self.driver_medium_online = Driver.objects.create(
            name='Medium Online Driver',
            status=DriverStatus.ONLINE,
        )
        # Driver 3: Very close (approx. 200m away), but BUSY
        self.driver_busy = Driver.objects.create(
            name='Busy Driver',
            status=DriverStatus.BUSY,
        )
        # Driver 4: Far (approx. 5.5km away), ONLINE
        self.driver_far_online = Driver.objects.create(
            name='Far Online Driver',
            status=DriverStatus.ONLINE,
        )

    @patch('dispatch.services.dispatcher.RedisClientService.get_instance')
    def test_redis_dispatch_selects_closest_online_driver(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        # Mock Redis returning 3 candidates sorted ASC:
        # Candidate 1: Busy Driver at 0.2km (must be filtered out)
        # Candidate 2: Near Online Driver at 0.4km (should be matched)
        # Candidate 3: Medium Online Driver at 1.2km
        mock_redis.find_nearby_drivers.return_value = [
            {'driver_id': str(self.driver_busy.id), 'distance_km': 0.2, 'coordinates': (-73.9850, 40.7582)},
            {'driver_id': str(self.driver_near_online.id), 'distance_km': 0.4, 'coordinates': (-73.9840, 40.7590)},
            {'driver_id': str(self.driver_medium_online.id), 'distance_km': 1.2, 'coordinates': (-73.9800, 40.7620)},
        ]

        payload = {
            'rider_id': str(self.rider.id),
            'pickup_latitude': 40.7580,
            'pickup_longitude': -73.9855,
            'dropoff_latitude': 40.7660,
            'dropoff_longitude': -73.9760,
        }

        response = self.client.post(self.url, data=payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], RideRequestStatus.ASSIGNED)
        self.assertEqual(str(response.data['driver']), str(self.driver_near_online.id))
        self.assertEqual(response.data['dispatch_strategy'], 'REDIS_GEO')
        self.assertTrue(response.data['is_driver_assigned'])

        # Verify driver status flipped to BUSY
        self.driver_near_online.refresh_from_db()
        self.assertEqual(self.driver_near_online.status, DriverStatus.BUSY)

        # Verify busy driver was not assigned
        self.driver_busy.refresh_from_db()
        self.assertEqual(self.driver_busy.status, DriverStatus.BUSY)

    @patch('dispatch.services.dispatcher.RedisClientService.get_instance')
    def test_postgis_fallback_when_redis_fails(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_redis.find_nearby_drivers.side_effect = redis.ConnectionError('Redis cluster unreachable')
        mock_get_redis.return_value = mock_redis

        # Store locations in PostGIS:
        # Near Driver: Empire State (~1.07km)
        DriverLocation.objects.create(
            driver=self.driver_near_online,
            location=Point(-73.9857, 40.7484, srid=4326),
        )
        # Medium Driver: (~2.2km)
        DriverLocation.objects.create(
            driver=self.driver_medium_online,
            location=Point(-73.9800, 40.7400, srid=4326),
        )
        # Far Driver: Brooklyn Bridge (~5.8km, outside 3km radius)
        DriverLocation.objects.create(
            driver=self.driver_far_online,
            location=Point(-73.9969, 40.7061, srid=4326),
        )

        ride = RideRequest.objects.create(
            rider=self.rider,
            pickup_location=self.pickup_point,
            dropoff_location=self.dropoff_point,
            status=RideRequestStatus.REQUESTED,
        )

        dispatcher = DispatcherService()
        dispatcher.redis_service = mock_redis
        ride, assigned_driver, strategy = dispatcher.dispatch_ride(str(ride.id))

        self.assertEqual(strategy, 'POSTGIS_FALLBACK')
        self.assertIsNotNone(assigned_driver)
        self.assertEqual(assigned_driver.id, self.driver_near_online.id)
        self.assertEqual(ride.status, RideRequestStatus.ASSIGNED)

    @patch('dispatch.services.dispatcher.RedisClientService.get_instance')
    def test_no_driver_found_when_beyond_3km(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_redis.find_nearby_drivers.return_value = []
        mock_get_redis.return_value = mock_redis

        payload = {
            'rider_id': str(self.rider.id),
            'pickup_latitude': 40.7580,
            'pickup_longitude': -73.9855,
            'dropoff_latitude': 40.7660,
            'dropoff_longitude': -73.9760,
        }

        response = self.client.post(self.url, data=payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], RideRequestStatus.REQUESTED)
        self.assertIsNone(response.data['driver'])
        self.assertEqual(response.data['dispatch_strategy'], 'NO_DRIVER_FOUND')
        self.assertFalse(response.data['is_driver_assigned'])