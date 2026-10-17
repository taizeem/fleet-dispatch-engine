import json
import logging
import signal
import sys
import time
from datetime import datetime
from confluent_kafka import Consumer, KafkaError
from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.utils import timezone
from dispatch.models import DriverLocation
from dispatch.redis_client import RedisClientService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Consumes driver location pings from Kafka, updates Redis GEO index, and batch inserts to PostGIS.'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = True
        self.redis_service = RedisClientService.get_instance()
        self.location_buffer = []
        self.last_flush_time = time.time()
        self.flush_interval = settings.BATCH_FLUSH_INTERVAL_SECONDS
        self.batch_size = settings.BATCH_FLUSH_SIZE

    def handle_shutdown(self, signum, frame):
        self.stdout.write(self.style.WARNING('\nShutdown signal received. Flushing pending records to database...'))
        self.running = False

    def handle(self, *args, **options):
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
                f'Started Kafka Consumer for topic "{settings.KAFKA_LOCATION_TOPIC}" with Redis GEO update & PostGIS batching (Interval: {self.flush_interval}s, Size: {self.batch_size})...'
            )
        )

        try:
            while self.running:
                msg = consumer.poll(timeout=1.0)

                # Check if periodic flush time interval reached even when idle
                self.check_periodic_flush()

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
            self.flush_buffer()
            consumer.close()
            self.stdout.write(self.style.SUCCESS('Consumer stopped and all buffers flushed cleanly.'))

    def process_location_ping(self, payload: dict):
        driver_id = payload.get('driver_id')
        lat = float(payload.get('latitude'))
        lon = float(payload.get('longitude'))
        ts_str = payload.get('timestamp')

        # 1. Real-Time State: Sub-millisecond write to Redis Geospatial Index
        self.redis_service.update_driver_location(
            driver_id=driver_id,
            longitude=lon,
            latitude=lat,
            timestamp_iso=ts_str,
        )

        # Parse timestamp or default to now
        recorded_at = timezone.now()
        if ts_str:
            try:
                recorded_at = datetime.fromisoformat(ts_str)
                if timezone.is_naive(recorded_at):
                    recorded_at = timezone.make_aware(recorded_at)
            except ValueError:
                recorded_at = timezone.now()

        # 2. Append to batch buffer for PostGIS
        location_obj = DriverLocation(
            driver_id=driver_id,
            location=Point(lon, lat, srid=4326),
            recorded_at=recorded_at,
        )
        self.location_buffer.append(location_obj)

        self.stdout.write(
            f'[PING PROCESSED] Driver {driver_id} updated in Redis GEO. Buffer size: {len(self.location_buffer)}/{self.batch_size}'
        )

        # Flush if batch size limit reached
        if len(self.location_buffer) >= self.batch_size:
            self.flush_buffer()

    def check_periodic_flush(self):
        current_time = time.time()
        if (current_time - self.last_flush_time) >= self.flush_interval and self.location_buffer:
            self.flush_buffer()

    def flush_buffer(self):
        if not self.location_buffer:
            return

        records_to_flush = self.location_buffer
        self.location_buffer = []
        self.last_flush_time = time.time()

        try:
            created_objects = DriverLocation.objects.bulk_create(
                records_to_flush,
                batch_size=500,
                ignore_conflicts=True,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully batch-inserted {len(created_objects)} location records into PostGIS table.'
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to batch insert records to PostGIS: {e}')
            )