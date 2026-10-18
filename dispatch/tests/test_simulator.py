from unittest.mock import MagicMock, patch
from django.test import TestCase
from django.contrib.gis.geos import Point

from dispatch.models import Driver, DriverStatus, Rider, RideRequest, RideRequestStatus
from dispatch.services.simulator import (
    haversine_distance,
    calculate_bearing,
    project_coordinate,
    SimulatedVehicle,
)
from dispatch.management.commands.simulate_fleet import Command as SimulatorCommand


class SimulatorMathAndVehicleTests(TestCase):
    def test_haversine_distance_accurate(self):
        # Times Square to Empire State Building (~1070 meters)
        lat1, lon1 = 40.7580, -73.9855
        lat2, lon2 = 40.7484, -73.9857
        dist = haversine_distance(lat1, lon1, lat2, lon2)
        self.assertGreater(dist, 1000)
        self.assertLess(dist, 1150)

    def test_calculate_bearing_south(self):
        # Point A to Point B directly South
        bearing = calculate_bearing(40.80, -73.98, 40.70, -73.98)
        self.assertAlmostEqual(bearing, 180.0, delta=1.0)

    def test_project_coordinate_moves_correctly(self):
        start_lat, start_lon = 40.7580, -73.9855
        # Move 500 meters North (bearing 0)
        new_lat, new_lon = project_coordinate(start_lat, start_lon, bearing_deg=0.0, distance_meters=500.0)
        self.assertGreater(new_lat, start_lat)
        self.assertAlmostEqual(new_lon, start_lon, delta=0.0001)

    def test_simulated_vehicle_destination_seeking(self):
        driver = Driver.objects.create(name='Nav Driver', status=DriverStatus.BUSY)
        rider = Rider.objects.create(name='Nav Rider')

        pickup_point = Point(-73.9850, 40.7600, srid=4326)
        dropoff_point = Point(-73.9750, 40.7700, srid=4326)

        RideRequest.objects.create(
            rider=rider,
            driver=driver,
            pickup_location=pickup_point,
            dropoff_location=dropoff_point,
            status=RideRequestStatus.ACCEPTED,
        )

        # Vehicle starts at (40.7580, -73.9855)
        vehicle = SimulatedVehicle(driver, initial_lat=40.7580, initial_lon=-73.9855, speed_kmh=60.0)
        initial_dist = haversine_distance(vehicle.latitude, vehicle.longitude, 40.7600, -73.9850)

        # Step forward 5 seconds
        ping = vehicle.step(delta_seconds=5.0)
        new_dist = haversine_distance(ping['latitude'], ping['longitude'], 40.7600, -73.9850)

        # Assert vehicle drew closer to the pickup destination
        self.assertLess(new_dist, initial_dist)
        self.assertEqual(ping['driver_id'], str(driver.id))


class SimulatorCommandTests(TestCase):
    @patch('dispatch.management.commands.simulate_fleet.KafkaProducerService.get_instance')
    def test_simulate_fleet_command_step(self, mock_get_producer):
        mock_producer = MagicMock()
        mock_get_producer.return_value = mock_producer

        command = SimulatorCommand()

        def stop_after_one_loop(*args, **kwargs):
            command.running = False

        # Run command with 2 drivers and stop after one execution
        with patch('time.sleep', side_effect=stop_after_one_loop):
            command.handle(drivers=2, interval=1.0, speed=40.0, center_lat=40.7580, center_lon=-73.9855)

        self.assertEqual(Driver.objects.filter(name__startswith='Sim Driver').count(), 2)
        # Verify 2 pings published
        self.assertEqual(mock_producer.publish_ping.call_count, 2)