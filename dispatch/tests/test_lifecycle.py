import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch
from django.test import TestCase
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from dispatch.models import Driver, DriverStatus, Rider, RideRequest, RideRequestStatus
from dispatch.services.lifecycle import RideLifecycleService


class RideLifecycleTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.rider = Rider.objects.create(name='Test Rider Alice')

        self.driver_1 = Driver.objects.create(name='Driver One', status=DriverStatus.ONLINE)
        self.driver_2 = Driver.objects.create(name='Driver Two', status=DriverStatus.ONLINE)

        # Times Square to Central Park South (~900m)
        self.pickup = Point(-73.9855, 40.7580, srid=4326)
        self.dropoff = Point(-73.9760, 40.7660, srid=4326)

        self.ride = RideRequest.objects.create(
            rider=self.rider,
            pickup_location=self.pickup,
            dropoff_location=self.dropoff,
            status=RideRequestStatus.OFFERED,
            offered_driver=self.driver_1,
            otp='1234',
        )

    @patch('dispatch.services.lifecycle.RedisClientService.get_instance')
    def test_driver_accepts_offer_transitions_to_accepted(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        url = reverse('dispatch:ride-offer-response')
        payload = {
            'ride_id': str(self.ride.id),
            'driver_id': str(self.driver_1.id),
            'action': 'accept',
        }

        response = self.client.post(url, data=payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'accepted')
        self.assertEqual(response.data['otp'], '1234')

        self.ride.refresh_from_db()
        self.assertEqual(self.ride.status, RideRequestStatus.ACCEPTED)
        self.assertEqual(self.ride.driver, self.driver_1)
        self.assertIsNone(self.ride.offered_driver)

        # Assert Driver 1 became BUSY
        self.driver_1.refresh_from_db()
        self.assertEqual(self.driver_1.status, DriverStatus.BUSY)

    @patch('dispatch.services.dispatcher.RedisClientService.get_instance')
    @patch('dispatch.services.lifecycle.RedisClientService.get_instance')
    def test_driver_declines_cascades_to_next_candidate(self, mock_get_redis_life, mock_get_redis_disp):
        mock_redis = MagicMock()
        # Mock cached candidate queue in Redis
        offer_cache = {
            'candidates': [
                {'driver_id': str(self.driver_1.id), 'distance_km': 0.5},
                {'driver_id': str(self.driver_2.id), 'distance_km': 1.2},
            ],
            'current_index': 0,
        }
        import json
        mock_redis.client.get.return_value = json.dumps(offer_cache)
        mock_get_redis_life.return_value = mock_redis
        mock_get_redis_disp.return_value = mock_redis

        url = reverse('dispatch:ride-offer-response')
        payload = {
            'ride_id': str(self.ride.id),
            'driver_id': str(self.driver_1.id),
            'action': 'decline',
        }

        response = self.client.post(url, data=payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'declined')
        self.assertEqual(response.data['cascaded_to'], str(self.driver_2.id))

        self.ride.refresh_from_db()
        self.assertEqual(self.ride.status, RideRequestStatus.OFFERED)
        self.assertEqual(self.ride.offered_driver, self.driver_2)

    def test_driver_arrived_at_pickup(self):
        self.ride.status = RideRequestStatus.ACCEPTED
        self.ride.driver = self.driver_1
        self.ride.offered_driver = None
        self.ride.save()

        url = reverse('dispatch:ride-driver-arrived')
        payload = {
            'ride_id': str(self.ride.id),
            'driver_id': str(self.driver_1.id),
        }

        response = self.client.post(url, data=payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], RideRequestStatus.ARRIVED)

        self.ride.refresh_from_db()
        self.assertEqual(self.ride.status, RideRequestStatus.ARRIVED)

    def test_start_trip_with_invalid_otp_fails(self):
        self.ride.status = RideRequestStatus.ARRIVED
        self.ride.driver = self.driver_1
        self.ride.save()

        url = reverse('dispatch:ride-start-trip')
        payload = {
            'ride_id': str(self.ride.id),
            'driver_id': str(self.driver_1.id),
            'otp': '9999',  # Incorrect OTP
        }

        response = self.client.post(url, data=payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.ride.refresh_from_db()
        self.assertEqual(self.ride.status, RideRequestStatus.ARRIVED)

    def test_start_trip_with_valid_otp_succeeds(self):
        self.ride.status = RideRequestStatus.ARRIVED
        self.ride.driver = self.driver_1
        self.ride.save()

        url = reverse('dispatch:ride-start-trip')
        payload = {
            'ride_id': str(self.ride.id),
            'driver_id': str(self.driver_1.id),
            'otp': '1234',  # Correct OTP
        }

        response = self.client.post(url, data=payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], RideRequestStatus.IN_PROGRESS)

        self.ride.refresh_from_db()
        self.assertEqual(self.ride.status, RideRequestStatus.IN_PROGRESS)

    def test_complete_trip_calculates_distance_fare_and_frees_driver(self):
        self.ride.status = RideRequestStatus.IN_PROGRESS
        self.ride.driver = self.driver_1
        self.ride.save()
        self.driver_1.status = DriverStatus.BUSY
        self.driver_1.save()

        url = reverse('dispatch:ride-complete-trip')
        payload = {
            'ride_id': str(self.ride.id),
            'driver_id': str(self.driver_1.id),
        }

        response = self.client.post(url, data=payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], RideRequestStatus.COMPLETED)
        self.assertGreater(float(response.data['fare_amount']), 3.0)
        self.assertGreater(response.data['distance_km'], 0.5)

        self.ride.refresh_from_db()
        self.assertEqual(self.ride.status, RideRequestStatus.COMPLETED)

        # Assert Driver 1 was released back to ONLINE
        self.driver_1.refresh_from_db()
        self.assertEqual(self.driver_1.status, DriverStatus.ONLINE)