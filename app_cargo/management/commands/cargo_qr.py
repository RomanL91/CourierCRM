import json
import pika
from django.core.management.base import BaseCommand

from app_accounts.models import User
from app_cargo.ScanQR import scan_qr

# --- Настройки RabbitMQ ---
RABBIT_HOST = "185.100.67.246"
RABBIT_PORT = 5672
RABBIT_USER = "guest"
RABBIT_PASSWORD = "guest"
QUEUE_NAME = "work_qr_queue"

# --- Параметры подключения ---
CREDENTIALS = pika.PlainCredentials(RABBIT_USER, RABBIT_PASSWORD)

RABBIT_PARAMS = pika.ConnectionParameters(
    host=RABBIT_HOST,
    port=RABBIT_PORT,
    credentials=CREDENTIALS,
    heartbeat=30,
    blocked_connection_timeout=300,
)


class Command(BaseCommand):
    help = "Запускает потребителя RabbitMQ для обработки QR-сканирований"

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS(f"🟢 Подключение к очереди: {QUEUE_NAME}"))
        try:
            connection = pika.BlockingConnection(RABBIT_PARAMS)
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=self.callback)
            channel.start_consuming()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("🛑 Остановлено вручную"))
        except Exception as e:
            self.stderr.write(f"❌ Ошибка подключения: {str(e)}")

    def callback(self, ch, method, properties, body):
        try:
            raw = body.decode("utf-8")
            data = json.loads(raw)

            if data.get("operation") != "work":
                self.stdout.write(
                    self.style.WARNING("⛔ Пропущено: неизвестная операция")
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            user_id = data.get("userId")
            employee = User.objects.get(chat_id=user_id)

            qr_data = data.get("qrData")  # ✅ Уже dict

            scan_qr(employee, qr_data)

            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ Обработан QR: {qr_data.get('id')} для {employee.username}"
                )
            )
            ch.basic_ack(delivery_tag=method.delivery_tag)

        except User.DoesNotExist:
            self.stderr.write(f"❌ Неизвестный пользователь: {data.get('userId')}")
            ch.basic_ack(delivery_tag=method.delivery_tag)

        except json.JSONDecodeError as e:
            self.stderr.write(f"❌ Неверный формат JSON: {str(e)}")
            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            self.stderr.write(f"❌ Ошибка обработки: {str(e)}")
            ch.basic_ack(delivery_tag=method.delivery_tag)
