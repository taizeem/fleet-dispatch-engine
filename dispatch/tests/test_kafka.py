import json
import uuid
from unittest.mock import MagicMock, patch
from confluent_kafka import Message
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from dispatch.management.commands.consume_driver_locations import Command as ConsumeCommand


class KafkaProducerEndpointTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('dispatch:driver-location-ping')
        self.driver_id = str(uuid.uuid4())

    @patch('dispatch.views.KafkaProducerService.get_instance')
    def test_location_ping_success_202_accepted(self, mock_get_producer):
        mock_producer = MagicMock()
        mock_get_producer.return_value = mock_producer

        payload = {
            'driver_id': self.driver_id,
            'latitude': 40.7580,
            'longitude': -73.9855,
        }

        response = self.client.post(self.url, data=payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data['status'], 'accepted')
        self.assertEqual(response.data['driver_id'], self.driver_id)

        mock_producer.publish_ping.assert_called_once()
        called_args, called_kwargs = mock_producer.publish_ping.call_args
        self.assertEqual(called_kwargs['driver_id'], self.driver_id)
        self.assertEqual(called_kwargs['payload']['latitude'], 40.7580)
        self.assertEqual(called_kwargs['payload']['longitude'], -73.9855)
        self.assertIn('timestamp', called_kwargs['payload'])

    @patch('dispatch.views.KafkaProducerService.get_instance')
    def test_location_ping_invalid_coordinates(self, mock_get_producer):
        mock_producer = MagicMock()
        mock_get_producer.return_value = mock_producer

        # Latitude > 90 is invalid
        payload = {
            'driver_id': self.driver_id,
            'latitude': 105.0,
            'longitude': -73.9855,
        }

        response = self.client.post(self.url, data=payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('latitude', response.data)
        mock_producer.publish_ping.assert_not_called()

    @patch('dispatch.views.KafkaProducerService.get_instance')
    def test_location_ping_missing_fields(self, mock_get_producer):
        mock_producer = MagicMock()
        mock_get_producer.return_value = mock_producer

        payload = {
            'driver_id': self.driver_id,
        }

        response = self.client.post(self.url, data=payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('latitude', response.data)
        self.assertIn('longitude', response.data)
        mock_producer.publish_ping.assert_not_called()


class KafkaConsumerCommandTests(SimpleTestCase):
    @patch('dispatch.management.commands.consume_driver_locations.Consumer')
    def test_consumer_processes_message_successfully(self, mock_consumer_cls):
        mock_consumer = MagicMock()
        mock_consumer_cls.return_value = mock_consumer

        # Prepare mock Kafka message
        payload = {
            'driver_id': str(uuid.uuid4()),
            'latitude': 40.7484,
            'longitude': -73.9857,
            'timestamp': '2026-10-17T12:00:00Z',
        }
        mock_message = MagicMock(spec=Message)
        mock_message.error.return_value = None
        mock_message.value.return_value = json.dumps(payload).encode('utf-8')

        # Poll returns message on first call, then stops loop
        command = ConsumeCommand()

        def side_effect(timeout):
            command.running = False
            return mock_message

        mock_consumer.poll.side_effect = side_effect

        with patch.object(command, 'process_location_ping') as mock_process:
            command.handle()
            mock_process.assert_called_once_with(payload)

        mock_consumer.subscribe.assert_called_once()
        mock_consumer.close.assert_called_once()