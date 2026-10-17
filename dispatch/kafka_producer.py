import json
import logging
from confluent_kafka import Producer
from django.conf import settings

logger = logging.getLogger(__name__)


class KafkaProducerService:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        conf = {
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'client.id': 'dispatch-driver-ping-producer',
            'queue.buffering.max.messages': 100000,
            'queue.buffering.max.ms': 10,
            'linger.ms': 10,
            'acks': 1,
        }
        self.producer = Producer(conf)

    def delivery_report(self, err, msg):
        if err is not None:
            logger.error('Kafka message delivery failed: %s', err)
        else:
            logger.debug(
                'Kafka message delivered to %s [%s] @ offset %s',
                msg.topic(),
                msg.partition(),
                msg.offset(),
            )

    def publish_ping(self, driver_id: str, payload: dict) -> None:
        serialized_payload = json.dumps(payload).encode('utf-8')
        self.producer.produce(
            topic=settings.KAFKA_LOCATION_TOPIC,
            key=str(driver_id).encode('utf-8'),
            value=serialized_payload,
            callback=self.delivery_report,
        )
        # Non-blocking poll to serve delivery callbacks
        self.producer.poll(0)

    def flush(self, timeout: float = 5.0) -> int:
        return self.producer.flush(timeout)