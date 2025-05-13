import json
import logging

from django.core.management.base import BaseCommand
from django.db import transaction

import pika

from app_orders.models import Order, ConsumerSentiment
from app_accounts.models import CourierScore
from django.contrib.auth import get_user_model

User = get_user_model()

# Настройки RabbitMQ
RABBIT_HOST = "185.100.67.246"
# RABBIT_HOST = "0.0.0.0"
RABBIT_PORT = 5672
RABBIT_USER = "guest"
RABBIT_PASSWORD = "guest"
RABBIT_QUEUE_FEEDBACK = "feedback_queue"

# Логирование
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class Command(BaseCommand):
    help = "Слушает очередь feedback_queue и сохраняет ConsumerSentiment для заказов."

    def handle(self, *args, **options):
        credentials = pika.PlainCredentials(RABBIT_USER, RABBIT_PASSWORD)
        parameters = pika.ConnectionParameters(
            host=RABBIT_HOST, port=RABBIT_PORT, credentials=credentials
        )
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.queue_declare(queue=RABBIT_QUEUE_FEEDBACK, durable=True)

        self.stdout.write(
            "Ожидаем сообщений из feedback_queue. Нажмите CTRL+C для остановки."
        )

        def callback(ch, method, properties, body):
            try:
                data = json.loads(body.decode("utf-8"))
                logger.info(f"Получено сообщение: {data}")

                # Извлекаем данные
                order_code = data.get("orderCode")
                rating_str = data.get("rating")
                courier_chat_id = data.get("courierChatId")
                comment = data.get("comment", "")

                # Преобразуем текстовую оценку в значение, которое хранится в модели.
                # Предположим, что в модели мы используем:
                # 'excellent' для "Отлично" и 'not_excellent' для "Не отлично"
                if rating_str == "Отлично":
                    sentiment_value = "excellent"
                elif rating_str == "Не отлично":
                    sentiment_value = "not_excellent"
                else:
                    sentiment_value = rating_str  # или можно обработать иначе

                if not order_code:
                    raise ValueError("Не указан orderCode в сообщении.")

                # Получаем заказ по order_code
                order = Order.objects.get(order_code=order_code)
                # Получаем курьера по chat_id
                courier = User.objects.get(chat_id=courier_chat_id)

                # Создаем или обновляем ConsumerSentiment (OneToOneField: один отзыв на заказ)
                with transaction.atomic():
                    obj, created = ConsumerSentiment.objects.update_or_create(
                        order=order,
                        defaults={
                            "courier": courier,
                            "sentiment": sentiment_value,
                            "comment": comment,
                        },
                    )
                    CourierScore.objects.create(
                        user=courier,
                        order=order,
                        points=1,
                    )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"ИНП для заказа {order_code} {'создан' if created else 'обновлён'}."
                    )
                )
            except Exception as e:
                self.stderr.write(f"Ошибка обработки сообщения: {e}")
                logger.exception("Ошибка при обработке сообщения")
            finally:
                ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=RABBIT_QUEUE_FEEDBACK, on_message_callback=callback)

        try:
            channel.start_consuming()
        except KeyboardInterrupt:
            self.stdout.write("Остановка потребителя...")
            channel.stop_consuming()
        connection.close()
