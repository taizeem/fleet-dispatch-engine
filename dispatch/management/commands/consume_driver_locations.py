import json
import logging
import signal
import sys
from confluent_kafka import Consumer, KafkaError
from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Continuously consumes driver location pings from Kafka topic.'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = True

    def handle_shutdown(self, signum, frame):
        self.stdout.write(self.style.WARNING('\nReceived shutdown signal. Closing consumer...'))
        self.running = False

    def handle(self, *args, **options):
        # Register signal handlers for graceful exit
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

        consumer_conf = {
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'group.id': settings.KAFKA_CONSUMER_GROUP,
            'auto.offset.reset': 'latest',
            'enable.auto.commit': True,
        }

        consumer = Consumer(consumer_conf)
        consumer.subscribe([settings.KAFKA_LOCATION_TOPIC])

        self.stdout.write(
            self.style.SUCCESS(
                f'Started Kafka Consumer for topic "{settings.KAFKA_LOCATION_TOPIC}" on {settings.KAFKA_BOOTSTRAP_SERVERS}...'
            )
        )

        try:
            while self.running:
                msg = consumer.poll(timeout=1.0)
                if msg is None:
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        self.stdout.write(self.style.ERROR(f'Kafka error: {msg.error()}'))
                        continue

                try:
                    payload = json.loads(msg.value().decode('utf-8'))
                    self.process_location_ping(payload)
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    self.stdout.write(self.style.ERROR(f'Failed to decode message: {e}'))

        finally:
            consumer.close()
            self.stdout.write(self.style.SUCCESS('Kafka Consumer closed cleanly.'))

    def process_location_ping(self, payload: dict):
        # Base ingestion handler: logs received ping
        driver_id = payload.get('driver_id')
        lat = payload.get('latitude')
        lon = payload.get('longitude')
        ts = payload.get('timestamp')
        self.stdout.write(f'[PING INGESTED] Driver {driver_id} at ({lat}, {lon}) @ {ts}')