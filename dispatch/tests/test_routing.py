from unittest.mock import MagicMock, patch
from django.test import TestCase
from django.contrib.gis.geos import Point

from dispatch.services.routing import RoutingService
from dispatch.services.dispatcher import DispatcherService
from dispatch.models import Driver, DriverStatus, Rider, RideRequest, RideRequestStatus


class RoutingServiceTests(TestCase):
    def setUp(self):
        self.routing_service = RoutingService()

    @patch('urllib.request.urlopen')
    def test_get_driving_route_parses_osrm_response(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        osrm_payload = {
            'code': 'Ok',
            'routes': [{
                'distance': 1850.0,  # 1.85 km
                'duration': 240.0,   # 4 minutes
                'geometry': {
                    'coordinates': [
                        [-73.9855, 40.7580],
                        [-73.9820, 40.7600],
                        [-73.9760, 40.7660],
                    ]
                }
            }]
        }
        import json
        mock_response.read.return_value = json.dumps(osrm_payload).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        route = self.routing_service.get_driving_route(40.7580, -73.9855, 40.7660, -73.9760)

        self.assertEqual(route['strategy'], 'OSRM_NETWORK')
        self.assertEqual(route['distance_km'], 1.85)
        self.assertEqual(route['duration_minutes'], 4.0)
        # Leaflet coordinates must be [lat, lon]
        self.assertEqual(route['coordinates'][0], [40.7580, -73.9855])
        self.assertEqual(route['coordinates'][-1], [40.7660, -73.9760])

    @patch('urllib.request.urlopen')
    def test_get_driving_route_fallback_on_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError('OSRM server timed out')

        route = self.routing_service.get_driving_route(40.7580, -73.9855, 40.7660, -73.9760)

        self.assertEqual(route['strategy'], 'HAVERSINE_FALLBACK')
        self.assertGreater(route['distance_km'], 0.5)
        self.assertGreater(route['duration_minutes'], 0)
        self.assertEqual(len(route['coordinates']), 2)


class DispatcherETARankingTests(TestCase):
    def setUp(self):
        self.rider = Rider.objects.create(name='ETA Rider')
        self.pickup = Point(-73.9855, 40.7580, srid=4326)
        self.dropoff = Point(-73.9760, 40.7660, srid=4326)

        self.driver_fast = Driver.objects.create(name='Fast Highway Driver', status=DriverStatus.ONLINE)
        self.driver_slow = Driver.objects.create(name='Slow Traffic Driver', status=DriverStatus.ONLINE)

    @patch('dispatch.services.dispatcher.RoutingService.get_driving_route')
    @patch('dispatch.services.dispatcher.RedisClientService.get_instance')
    def test_dispatcher_ranks_candidates_by_fastest_eta(self, mock_get_redis, mock_get_route):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        # Redis returns 2 candidates:
        # Driver Slow is geometrically closer (0.3km)
        # Driver Fast is slightly further (0.6km)
        mock_redis.find_nearby_drivers.return_value = [
            {'driver_id': str(self.driver_slow.id), 'distance_km': 0.3, 'coordinates': (-73.9850, 40.7585)},
            {'driver_id': str(self.driver_fast.id), 'distance_km': 0.6, 'coordinates': (-73.9800, 40.7600)},
        ]

        # But OSRM calculates that Driver Fast has a highway path (2.0 mins ETA)
        # while Driver Slow is stuck on congested one-ways (6.0 mins ETA)
        def route_side_effect(start_lat, start_lon, end_lat, end_lon):
            if start_lat == 40.7585:  # Slow Driver
                return {'distance_km': 0.4, 'duration_minutes': 6.0, 'coordinates': []}
            else:  # Fast Driver
                return {'distance_km': 0.7, 'duration_minutes': 2.0, 'coordinates': []}

        mock_get_route.side_effect = route_side_effect

        ride = RideRequest.objects.create(
            rider=self.rider,
            pickup_location=self.pickup,
            dropoff_location=self.dropoff,
            status=RideRequestStatus.REQUESTED,
        )

        dispatcher = DispatcherService()
        dispatcher.redis_service = mock_redis
        ride, matched_driver, strategy = dispatcher.dispatch_ride(str(ride.id))

        # Assert Driver Fast was offered FIRST despite being further in straight-line distance
        self.assertEqual(matched_driver.id, self.driver_fast.id)
        self.assertEqual(ride.offered_driver, self.driver_fast)
        self.assertEqual(ride.status, RideRequestStatus.OFFERED)