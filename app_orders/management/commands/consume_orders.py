import json
import pika

from decimal import Decimal

from django.core.management.base import BaseCommand
from datetime import datetime
from app_orders.models import Order, OrderEntry, OrderHistory, OrderPreparation
from app_accounts.models import CourierScore
from django.contrib.auth import get_user_model


User = get_user_model()


def ms_to_datetime(ms_val):
    return datetime.utcfromtimestamp(ms_val / 1000.0)


def give_out_points(order_code, order_obj):
    preparation_type_list = ("shipment", "packing")

    for preparation_type in preparation_type_list:
        pre_orders = OrderPreparation.objects.filter(
            order_code=order_code, preparation_type=preparation_type
        )

        pre_orders_count = pre_orders.count()

        if pre_orders_count == 0:
            continue

        points = Decimal("1") / Decimal(pre_orders_count)

        for pre_order in pre_orders:
            if pre_order.executor:

                CourierScore.objects.create(
                    user=pre_order.executor,
                    order=order_obj,
                    points=points,
                )


def link_merchant_user(hist_data: dict):
    """
    Пытается найти Django-пользователя по телефону или email,
    если не находит — при желании можно создать,
    либо вернуть None, если не хотим создавать автоматически.
    """
    user_type = hist_data.get("userType")
    if user_type != "MERCHANT_USER":
        return None

    phone = hist_data.get("userPhone", "")
    email = hist_data.get("userEmail", "")
    username = hist_data.get("userName", "unknown_user")

    # Пробуем поискать по email
    if email:
        qs = User.objects.filter(email=email)
        if qs.exists():
            return qs.first()

    # Если не нашли по email, пробуем по телефону (если модель хранит phone_number)
    if phone:
        qs = User.objects.filter(phone_number=phone)
        if qs.exists():
            return qs.first()

    # Если тут вы хотите автоматически создавать пользователя:
    # (иначе просто return None)
    new_user = User.objects.create_user(
        username=username.replace(" ", "_")[:30],  # ограничиваем длину
        email=email,
        password="some_default_password",  # обязательно указать или сгенерировать
        phone_number=phone,
    )
    return new_user


def publish_message_to_rabbitmq(
    message_body: dict,
    queue_name: str = "telegram_queue",
    host: str = "185.100.67.246",
    # host: str = "0.0.0.0",
    port: int = 5672,
    username: str = "guest",
    password: str = "guest",
):
    """
    Подключаемся к RabbitMQ, объявляем очередь, отправляем туда сообщение.
    В реальном проекте обычно переиспользуют connection/channel
    вместо открытия/закрытия на каждое сообщение.
    """
    credentials = pika.PlainCredentials(username, password)
    connection_params = pika.ConnectionParameters(
        host=host, port=port, credentials=credentials
    )
    connection = pika.BlockingConnection(connection_params)
    channel = connection.channel()

    channel.queue_declare(queue=queue_name, durable=True)

    body_str = json.dumps(message_body, ensure_ascii=False)
    channel.basic_publish(
        exchange="",
        routing_key=queue_name,
        body=body_str,
        properties=pika.BasicProperties(delivery_mode=2),  # persistent
    )
    connection.close()


class Command(BaseCommand):
    help = "Consume order messages from RabbitMQ and save them to DB."

    def add_arguments(self, parser):
        parser.add_argument(
            "--queue",
            type=str,
            default="orders_queue",
            help="RabbitMQ queue name to consume from (default: orders_queue)",
        )
        parser.add_argument(
            "--host",
            type=str,
            default="localhost",
            help="RabbitMQ host (default: localhost)",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=5672,
            help="RabbitMQ port (default: 5672)",
        )
        parser.add_argument(
            "--username",
            type=str,
            default="guest",
            help="RabbitMQ username (default: guest)",
        )
        parser.add_argument(
            "--password",
            type=str,
            default="guest",
            help="RabbitMQ password (default: guest)",
        )

    def handle(self, *args, **options):
        queue_name = options["queue"]
        host = options["host"]
        port = options["port"]
        username = options["username"]
        password = options["password"]

        self.stdout.write(
            self.style.SUCCESS(
                f" [*] Connecting to RabbitMQ at {host}:{port}, queue={queue_name}"
            )
        )
        credentials = pika.PlainCredentials(username, password)
        connection_params = pika.ConnectionParameters(
            host=host, port=port, credentials=credentials
        )

        # Создаем соединение и канал
        connection = pika.BlockingConnection(connection_params)
        channel = connection.channel()

        # Объявляем очередь на всякий случай (idempotent)
        channel.queue_declare(queue=queue_name, durable=True)

        self.stdout.write(
            self.style.SUCCESS(f" [*] Waiting for messages. Press CTRL+C to exit.")
        )

        # Определяем колбэк на получение сообщений
        def callback(ch, method, properties, body):
            try:
                message_data = json.loads(body)
                self.stdout.write(f" [x] Received message: {message_data}")

                # Сохраняем в БД
                self.save_order_to_db(message_data)

                # Подтверждаем получение
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                self.stderr.write(f" [!] Error processing message: {e}")
                # Не делаем ack => сообщение вернется в очередь

        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=queue_name, on_message_callback=callback)

        try:
            channel.start_consuming()
        except KeyboardInterrupt:
            channel.stop_consuming()
        connection.close()

    def save_order_to_db(self, message_data: dict):
        # --- Сохраняем сам Order и OrderEntry (пример как раньше)
        order_code = message_data.get("orderCode")
        if not order_code:
            self.stdout.write(" [!] orderCode отсутствует, пропускаем.")
            return

        customer_info = message_data.get("customer", {})
        delivery_info = message_data.get("delivery", {})
        firstname = customer_info.get("firstname", "")
        lastname = customer_info.get("lastname", "")
        phone_number = customer_info.get("phoneNumber", "")

        total_price = message_data.get("totalPrice", 0)
        order_status = message_data.get("orderStatus", "")

        order_obj, created = Order.objects.get_or_create(
            order_code=order_code,
            defaults={
                "customer_firstname": firstname,
                "customer_lastname": lastname,
                "phone_number": phone_number,
                "total_price": total_price,
                "order_status": order_status,
                "raw_json": message_data,
            },
        )
        if not created:
            # если уже есть
            order_obj.customer_firstname = firstname
            order_obj.customer_lastname = lastname
            order_obj.phone_number = phone_number
            order_obj.total_price = total_price
            order_obj.order_status = order_status
            order_obj.raw_json = message_data
            order_obj.save()

        # --- Сохраняем entries
        entries = message_data.get("entries", [])
        for entry_data in entries:
            entry_id = entry_data.get("entryId", None)  # может быть int или None

            # Собираем данные
            defaults = {
                "name": entry_data.get("name", ""),
                "quantity": entry_data.get("quantity", 1),
                "weight": entry_data.get("weight", 0.0),
                "base_price": entry_data.get("basePrice", 0),
                "total_price": entry_data.get("totalPrice", 0),
                "master_product_code": entry_data.get("masterProductCode", ""),
                "master_product_url": entry_data.get("masterProductUrl", ""),
                "master_product_name": entry_data.get("masterProductName", ""),
                "merchant_product_sku": entry_data.get("merchantProductSKU", ""),
                "merchant_product_name": entry_data.get("merchantProductName", ""),
                "raw_entry": entry_data,
            }

            # Если есть images
            if "images" in entry_data:
                defaults["images"] = entry_data["images"]

            # Если есть unit
            unit_data = entry_data.get("unit", {})
            defaults["unit_code"] = unit_data.get("code", "")
            defaults["unit_display_name"] = unit_data.get("displayName", "")
            defaults["unit_type"] = unit_data.get("type", "")

            # Создаём или обновляем
            oe, oe_created = OrderEntry.objects.get_or_create(
                order=order_obj, entry_id=entry_id, defaults=defaults
            )
            if not oe_created:
                # Обновим поля, если что-то изменилось
                for field_name, field_value in defaults.items():
                    setattr(oe, field_name, field_value)
                oe.save()

        # --- теперь history
        history_list = message_data.get("historyEntries", [])
        for hist_data in history_list:
            action = hist_data.get("action", "")
            user_type = hist_data.get("userType", "")
            create_ms = hist_data.get("createDate")
            if create_ms is None:
                continue
            create_dt = ms_to_datetime(create_ms)

            oh, oh_created = OrderHistory.objects.get_or_create(
                order=order_obj,
                create_date=create_dt,
                action=action,
                defaults={
                    "user_type": user_type,
                    "user_name": hist_data.get("userName", ""),
                    "user_email": hist_data.get("userEmail", ""),
                    "user_phone": hist_data.get("userPhone", ""),
                    "description": hist_data.get("description", ""),
                    "raw_data": hist_data,
                },
            )
            if not oh_created:
                # обновим
                oh.user_type = user_type
                oh.user_name = hist_data.get("userName", "")
                oh.user_email = hist_data.get("userEmail", "")
                oh.user_phone = hist_data.get("userPhone", "")
                oh.description = hist_data.get("description", "")
                oh.raw_data = hist_data

            # Привяжем к Django-пользователю, если MERCHANT_USER
            user_obj = link_merchant_user(hist_data)
            if user_obj:
                oh.processed_by = user_obj
            oh.save()

            # === Начисляем баллы, если нужно (action='COMPLETED', MERCHANT_USER, есть processed_by)
            if (
                action == "COMPLETED"
                and user_type == "MERCHANT_USER"
                and oh.processed_by
            ):
                # проверим, нет ли уже score
                already_exists = CourierScore.objects.filter(
                    user=oh.processed_by, order=oh.order
                ).exists()
                if not already_exists:
                    CourierScore.objects.create(
                        user=oh.processed_by,
                        order=oh.order,
                        points=1,
                    )
                    self.stdout.write(
                        f" [+] CourierScore создан для user={oh.processed_by} order={oh.order.order_code}"
                    )

                    # --- Теперь отправим сообщение в другую очередь (telegram_queue)

                    # Сформируем тело сообщения
                    # Пример: может пригодиться часть данных из message_data, а часть – из oh.order
                    # Вы берёте поля, которые ваш телеграм-бот в будущем будет использовать.

                    telegram_payload = {
                        # "status": "COMPLETED",
                        "orderCode": oh.order.order_code,
                        "orderPK": oh.order.pk,
                        "courierName": oh.user_name,  # имя от Kaspi (MERCHANT_USER)
                        "courierEmail": oh.user_email,
                        "courierPK": user_obj.pk,
                        "chat_id": user_obj.chat_id,
                        "courierPhone": oh.user_phone,
                        "customerName": f"{oh.order.customer_firstname} {oh.order.customer_lastname}",
                        "deliveryAddress": "...",
                        "firstname": firstname,
                        "lastname": lastname,
                        "phone_number": phone_number,
                        "entries": entries,
                        "delivery_info": delivery_info,
                    }
                    # отправляем
                    publish_message_to_rabbitmq(
                        message_body=telegram_payload,
                    )
                    self.stdout.write(
                        " [+] Отправили сообщение в очередь telegram_queue"
                    )

                    give_out_points(oh.order.order_code, oh.order)

                    self.stdout.write(" [+] Цепочке подготовки заказа начислены баллы")

        self.stdout.write(
            f" [√] History entries: {len(history_list)} для заказа {order_code}"
        )
