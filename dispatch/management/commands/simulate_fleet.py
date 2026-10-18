import signal
import sys
import time
import random
from django.core.management.base import BaseCommand
from dispatch.models import Driver, DriverStatus
from dispatch.kafka_producer import KafkaProducerService
from dispatch.services.simulator import SimulatedVehicle

# Default bounding center: Manhattan (Times Square)
DEFAULT_CENTER_LAT = 40.7580
DEFAULT_CENTER_LON = -73.9855


class Command(BaseCommand):
    help = 'Simulates a live fleet of moving drivers publishing GPS pings to Kafka.'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = True

    def add_arguments(self, parser):
        parser.add_argument('--drivers', type=int, default=10, help='Number of simulated drivers to run (default: 10)')
        parser.add_argument('--interval', type=float, default=2.0, help='Ping interval in seconds (default: 2.0)')
        parser.add_argument('--speed', type=float, default=40.0, help='Average driving speed in km/h (default: 40.0)')
        parser.add_argument('--center-lat', type=float, default=DEFAULT_CENTER_LAT, help='City center latitude')
        parser.add_argument('--center-lon', type=float, default=DEFAULT_CENTER_LON, help='City center longitude')

    def handle_shutdown(self, signum, frame):
        self.stdout.write(self.style.WARNING('\nStopping fleet simulator cleanly...'))
        self.running = False

    def handle(self, *args, **options):
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

        num_drivers = options['drivers']
        interval = options['interval']
        avg_speed = options['speed']
        center_lat = options['center_lat']
        center_lon = options['center_lon']

        self.stdout.write(self.style.NOTICE(f'Bootstrapping {num_drivers} simulated drivers...'))
        vehicles = []
        producer = KafkaProducerService.get_instance()

        for i in range(1, num_drivers + 1):
            driver_name = f'Sim Driver {i:02d}'
            driver, _ = Driver.objects.get_or_create(
                name=driver_name,
                defaults={'status': DriverStatus.ONLINE},
            )
            # Ensure driver is online
            if driver.status == DriverStatus.OFFLINE:
                driver.status = DriverStatus.ONLINE
                driver.save(update_fields=['status'])

            # Scatter within ~1.5 km of center
            init_lat = center_lat + random.uniform(-0.012, 0.012)
            init_lon = center_lon + random.uniform(-0.012, 0.012)
            speed = random.uniform(avg_speed * 0.8, avg_speed * 1.2)

            vehicle = SimulatedVehicle(
                driver=driver,
                initial_lat=init_lat,
                initial_lon=init_lon,
                speed_kmh=speed,
            )
            vehicles.append(vehicle)

        self.stdout.write(
            self.style.SUCCESS(
                f'Fleet Simulation active! Streaming GPS pings for {num_drivers} vehicles every {interval}s to Kafka. (Press Ctrl+C to stop)'
            )
        )

        last_step_time = time.time()

        try:
            while self.running:
                now = time.time()
                elapsed = now - last_step_time
                last_step_time = now

                for vehicle in vehicles:
                    ping_data = vehicle.step(delta_seconds=elapsed)
                    producer.publish_ping(
                        driver_id=ping_data['driver_id'],
                        payload=ping_data,
                    )

                self.stdout.write(
                    f'[FLEET PING] Published {len(vehicles)} live vehicle pings to Kafka at {time.strftime("%X")}'
                )
                time.sleep(interval)

        finally:
            producer.flush(timeout=3.0)
            self.stdout.write(self.style.SUCCESS('Fleet simulator stopped.'))