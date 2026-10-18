import uuid
import time
from unittest.mock import MagicMock, patch
from django.test import TestCase
from django.contrib.gis.geos import Point
from django.utils import timezone
from dispatch.models import Driver, DriverLocation
from dispatch.redis_client import RedisClientService
from dispatch.management.commands.consume_driver_locations import Command as ConsumeCommand


class RedisClientServiceTests(TestCase):
    @patch('dispatch.redis_client.redis.Redis')
    def test_update_driver_location_calls_geoadd_and_pipeline(self, mock_redis_cls):
        mock_client = MagicMock()
        mock_pipeline = MagicMock()
        mock_client.pipeline.return_value = mock_pipeline
        mock_redis_cls.return_value = mock_client

        service = RedisClientService()
        service.client = mock_client

        driver_id = str(uuid.uuid4())
        lon = -73.9855
        lat = 40.7580
        ts = '2026-10-17T12:00:00Z'

        service.update_driver_location(driver_id, lon, lat, ts)

        mock_client.pipeline.assert_called_once()
        mock_pipeline.geoadd.assert_called_once_with('drivers:locations', (lon, lat, driver_id))
        mock_pipeline.hset.assert_called_once()
        mock_pipeline.expire.assert_called_once()
        mock_pipeline.execute.assert_called_once()

    @patch('dispatch.redis_client.redis.Redis')
    def test_get_driver_location_returns_coordinates(self, mock_redis_cls):
        mock_client = MagicMock()
        mock_client.geopos.return_value = [(-73.9855, 40.7580)]
        mock_redis_cls.return_value = mock_client

        service = RedisClientService()
        service.client = mock_client

        coords = service.get_driver_location('driver-123')
        self.assertEqual(coords, (-73.9855, 40.7580))
        mock_client.geopos.assert_called_once_with('drivers:locations', 'driver-123')


class ConsumerBatchingToPostGISTests(TestCase):
    def setUp(self):
        self.driver = Driver.objects.create(name='Batch Driver')

    @patch('dispatch.management.commands.consume_driver_locations.RedisClientService.get_instance')
    def test_process_ping_updates_redis_and_buffers_object(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        command = ConsumeCommand()
        command.redis_service = mock_redis

        payload = {
            'driver_id': str(self.driver.id),
            'latitude': 40.7580,
            'longitude': -73.9855,
            'timestamp': '2026-10-17T12:00:00Z',
        }

        command.process_location_ping(payload)

        mock_redis.update_driver_location.assert_called_once_with(
            driver_id=str(self.driver.id),
            longitude=-73.9855,
            latitude=40.7580,
            timestamp_iso='2026-10-17T12:00:00Z',
        )
        self.assertEqual(len(command.location_buffer), 1)
        self.assertEqual(command.location_buffer[0].driver_id, str(self.driver.id))

    @patch('dispatch.management.commands.consume_driver_locations.RedisClientService.get_instance')
    def test_flush_buffer_creates_records_in_postgis(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        command = ConsumeCommand()
        command.redis_service = mock_redis

        # Add 3 items to buffer
        for i in range(3):
            command.location_buffer.append(
                DriverLocation(
                    driver_id=self.driver.id,
                    location=Point(-73.9855 + (i * 0.001), 40.7580, srid=4326),
                    recorded_at=timezone.now(),
                )
            )

        self.assertEqual(DriverLocation.objects.count(), 0)
        command.flush_buffer()

        # Assert all records are now written to PostGIS
        self.assertEqual(DriverLocation.objects.count(), 3)
        self.assertEqual(len(command.location_buffer), 0)

    @patch('dispatch.management.commands.consume_driver_locations.RedisClientService.get_instance')
    def test_batch_size_threshold_triggers_automatic_flush(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        command = ConsumeCommand()
        command.redis_service = mock_redis
        command.batch_size = 2  # Low threshold for test

        payload1 = {'driver_id': str(self.driver.id), 'latitude': 40.7580, 'longitude': -73.9855}
        payload2 = {'driver_id': str(self.driver.id), 'latitude': 40.7581, 'longitude': -73.9856}

        command.process_location_ping(payload1)
        self.assertEqual(DriverLocation.objects.count(), 0)

        # Second ping reaches threshold 2 and triggers flush
        command.process_location_ping(payload2)
        self.assertEqual(DriverLocation.objects.count(), 2)
        self.assertEqual(len(command.location_buffer), 0)