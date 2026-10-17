from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import DriverLocationPingSerializer
from .kafka_producer import KafkaProducerService


class DriverLocationPingView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = DriverLocationPingSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data
        driver_id = str(validated_data['driver_id'])

        payload = {
            'driver_id': driver_id,
            'latitude': validated_data['latitude'],
            'longitude': validated_data['longitude'],
            'timestamp': validated_data['timestamp_iso'],
        }

        producer = KafkaProducerService.get_instance()
        producer.publish_ping(driver_id=driver_id, payload=payload)

        return Response(
            {
                'status': 'accepted',
                'driver_id': driver_id,
            },
            status=status.HTTP_202_ACCEPTED,
        )