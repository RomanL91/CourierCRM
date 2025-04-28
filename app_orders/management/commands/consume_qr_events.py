import json
import logging

import pika
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.contrib.auth import get_user_model

from app_orders.models import OrderPreparation

log = logging.getLogger(__name__)


# Настройки RabbitMQ
RABBIT_HOST = "185.100.67.246"
# RABBIT_HOST = "0.0.0.0"
RABBIT_PORT = 5672
RABBIT_USER = "guest"
RABBIT_PASSWORD = "guest"
RABBIT_QR_EVENTS = "qr_events"

CREDENTIALS = pika.PlainCredentials(
    RABBIT_USER,
    RABBIT_PASSWORD,
)


RABBIT_PARAMS = pika.ConnectionParameters(
    host=RABBIT_HOST,
    port=RABBIT_PORT,
    credentials=CREDENTIALS,
)

User = get_user_model()


def link_merchant_user(chat_id):
    if chat_id:
        qs = User.objects.filter(chat_id=chat_id)
        if qs.exists():
            return qs.first()
        return None


class Command(BaseCommand):
    help = "Consume qr_events queue and persist OrderPreparation records"

    def handle(self, *args, **options):
        connection = pika.BlockingConnection(RABBIT_PARAMS)
        channel = connection.channel()
        channel.queue_declare(queue=RABBIT_QR_EVENTS, durable=True)

        # ограничиваем количество «неподтверждённых» сообщений на воркере
        channel.basic_qos(prefetch_count=10)

        def callback(ch, method, properties, body):
            # 1. Пытаемся распарсить JSON
            try:
                payload = json.loads(body)
                op = payload["operation"]
                user_id = payload["userId"]
                code = payload["qrData"]
            except (ValueError, KeyError) as exc:
                log.warning("Bad message %s – %s", body, exc)
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            # 2. Пишем в базу
            try:
                with transaction.atomic():
                    executor = link_merchant_user(user_id)
                    _, created = OrderPreparation.objects.get_or_create(
                        order_code=code,
                        preparation_type=op,
                        telegram_chat_id=user_id,
                        executor=executor,
                    )
                if created:
                    log.info("Saved %s / %s / %s", code, op, user_id)
                else:
                    log.debug("Duplicate ignored: %s", payload)
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except IntegrityError:
                # ещё один «страховочный» сценарий на случай гонок
                log.debug("IntegrityError – duplicate?")
                ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_consume(queue=RABBIT_QR_EVENTS, on_message_callback=callback)

        self.stdout.write(self.style.SUCCESS(" [*] Waiting for qr_events …"))
        try:
            channel.start_consuming()  # блокирующий цикл :contentReference[oaicite:0]{index=0}
        except KeyboardInterrupt:
            channel.stop_consuming()
        finally:
            connection.close()
