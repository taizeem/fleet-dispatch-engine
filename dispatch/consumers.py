import json
from channels.generic.websocket import AsyncWebsocketConsumer


class RideTrackingConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.ride_id = self.scope['url_route']['kwargs']['ride_id']
        self.room_group_name = f'ride_{self.ride_id}'

        # Join the unique ride broadcast group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )

        await self.accept()

        # Send initial confirmation message
        await self.send(
            text_data=json.dumps({
                'type': 'connection_established',
                'ride_id': self.ride_id,
                'message': f'Subscribed to live location updates for ride {self.ride_id}',
            })
        )

    async def disconnect(self, close_code):
        # Leave the group upon client disconnect
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name,
        )

    async def receive(self, text_data):
        # Handle incoming messages from rider (e.g. ping/heartbeat)
        pass

    async def driver_location_update(self, event):
        # Broadcast the driver location to the WebSocket client
        await self.send(text_data=json.dumps(event['data']))