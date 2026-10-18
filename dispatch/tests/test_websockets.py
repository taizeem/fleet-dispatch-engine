import json
import uuid
from channels.testing import WebsocketCommunicator
from channels.layers import get_channel_layer
from asgiref.sync import sync_to_async
from django.test import TransactionTestCase
from django.contrib.gis.geos import Point

from config.asgi import application
from dispatch.models import Driver, DriverStatus, Rider, RideRequest, RideRequestStatus
from dispatch.management.commands.consume_driver_locations import Command as ConsumeCommand


class WebSocketTrackingTests(TransactionTestCase):
    async def test_rider_websocket_connection_and_subscription(self):
        ride_id = str(uuid.uuid4())
        communicator = WebsocketCommunicator(application, f'/ws/rides/{ride_id}/')

        connected, subprotocol = await communicator.connect()
        self.assertTrue(connected)

        # Receive connection established confirmation
        response = await communicator.receive_json_from()
        self.assertEqual(response['type'], 'connection_established')
        self.assertEqual(response['ride_id'], ride_id)

        await communicator.disconnect()

    async def test_driver_location_broadcast_received_by_rider(self):
        ride_id = str(uuid.uuid4())
        communicator = WebsocketCommunicator(application, f'/ws/rides/{ride_id}/')

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Consume initial handshake message
        await communicator.receive_json_from()

        # Simulate channel layer broadcasting a driver location
        channel_layer = get_channel_layer()
        broadcast_payload = {
            'type': 'driver_location_update',
            'data': {
                'type': 'driver_location',
                'ride_id': ride_id,
                'driver_id': 'driver-999',
                'latitude': 40.7580,
                'longitude': -73.9855,
                'timestamp': '2026-10-18T12:00:00Z',
            },
        }

        await channel_layer.group_send(f'ride_{ride_id}', broadcast_payload)

        # Assert WebSocket client receives broadcast
        received = await communicator.receive_json_from()
        self.assertEqual(received['type'], 'driver_location')
        self.assertEqual(received['ride_id'], ride_id)
        self.assertEqual(received['latitude'], 40.7580)
        self.assertEqual(received['longitude'], -73.9855)

        await communicator.disconnect()

    async def test_kafka_consumer_broadcasts_when_driver_has_active_ride(self):
        # Create Rider, Driver, and Active RideRequest in DB
        driver = await sync_to_async(Driver.objects.create)(
            name='Speedy Driver',
            status=DriverStatus.BUSY,
        )
        rider = await sync_to_async(Rider.objects.create)(name='Rider Mark')

        ride = await sync_to_async(RideRequest.objects.create)(
            rider=rider,
            driver=driver,
            pickup_location=Point(-73.9855, 40.7580, srid=4326),
            dropoff_location=Point(-73.9760, 40.7660, srid=4326),
            status=RideRequestStatus.ASSIGNED,
        )

        communicator = WebsocketCommunicator(application, f'/ws/rides/{ride.id}/')
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.receive_json_from()  # Discard handshake

        # Simulate Kafka consumer processing a ping for this driver
        command = ConsumeCommand()
        payload = {
            'driver_id': str(driver.id),
            'latitude': 40.7595,
            'longitude': -73.9840,
            'timestamp': '2026-10-18T12:00:05Z',
        }

        await sync_to_async(command.process_location_ping)(payload)

        # Assert WebSocket received the update emitted by consumer
        live_update = await communicator.receive_json_from()
        self.assertEqual(live_update['type'], 'driver_location')
        self.assertEqual(live_update['driver_id'], str(driver.id))
        self.assertEqual(live_update['latitude'], 40.7595)
        self.assertEqual(live_update['longitude'], -73.9840)

        await communicator.disconnect()