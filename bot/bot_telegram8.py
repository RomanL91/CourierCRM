import sys
import os
import django

# Настройка Django: файл настроек находится в core/settings.py
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

import asyncio
import aiohttp
import json
import logging

import pika
import aio_pika
from asgiref.sync import sync_to_async, async_to_sync

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,     # ### ИЗМЕНЕНО ДЛЯ INLINE-КНОПОК ###
    InlineKeyboardButton,     # ### ИЗМЕНЕНО ДЛЯ INLINE-КНОПОК ###
    CallbackQuery,            # ### ИЗМЕНЕНО ДЛЯ INLINE-КНОПОК ###
)
from aiogram.client.bot import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from app_orders.models import Order
from app_accounts.models import User, TelegramGroup

# ============================================================
# Конфигурация и инициализация
# ============================================================
API_TOKEN = "8118146507:AAEPYUDWh9S-aX6XQtVHvnIVaQ8Rc2FSnUs"
RABBIT_HOST = "185.100.67.246"
# RABBIT_HOST = "localhost"
RABBIT_PORT = 5672
RABBIT_USER = "guest"
RABBIT_PASSWORD = "guest"
RABBIT_QUEUE = "telegram_queue"
RABBIT_QUEUE_FEEDBACK = "feedback_queue"
# DJANGO_HOST = "185.100.67.246"
DJANGO_HOST = "localhost"
ENDPOINT_API_VIDEO = "http://localhost:8889/v1/api/upload_video/"

logging.basicConfig(level=logging.INFO)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)
bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)


# ============================================================
# FSM-состояния для обратной связи доставки (используются для шагов, но не для хранения orderData)
# ============================================================
class DeliveryFeedbackStates(StatesGroup):
    begin_waiting_state = State()
    waiting_for_feedback_details = State()  # если оценка "Не отлично"
    waiting_for_video = State()            # для видео отчета (общий шаг)


async def get_current_state(chat_id: int):
    state = FSMContext(dp.storage, key=f"{chat_id}:{chat_id}")
    current_state = await state.get_state()
    data = await state.get_data()

    return current_state, data


# ============================================================
# Для загрузки видео
# ============================================================
async def download_video(file_id: str) -> bytes:
    # Получаем file_path через API Telegram
    file = await bot.get_file(file_id)
    file_path = file.file_path
    download_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{file_path}"
    async with aiohttp.ClientSession() as session:
        async with session.get(download_url) as resp:
            if resp.status == 200:
                return await resp.read()
            else:
                raise Exception(f"Не удалось скачать видео: {resp.status}")


async def send_video_to_django(
    video_bytes: bytes, filename: str, order_code: str, courier_id: int
):
    data = aiohttp.FormData()
    data.add_field("video", video_bytes, filename=filename, content_type="video/mp4")
    data.add_field("order_code", order_code)
    data.add_field("courier_id", str(courier_id))
    async with aiohttp.ClientSession() as session:
        async with session.post(ENDPOINT_API_VIDEO, data=data) as resp:
            if resp.status == 200:
                logging.info("Видео успешно передано на Django")
            else:
                logging.error(f"Ошибка передачи видео: {resp.status}")


# ============================================================
# Функция для отправки данных обратной связи в RabbitMQ
# ============================================================
def publish_feedback_to_rabbitmq(
    feedback_data: dict,
    queue_name: str = RABBIT_QUEUE_FEEDBACK,
    host: str = RABBIT_HOST,
    port: int = RABBIT_PORT,
    username: str = RABBIT_USER,
    password: str = RABBIT_PASSWORD,
):
    credentials = pika.PlainCredentials(username, password)
    connection_params = pika.ConnectionParameters(
        host=host, port=port, credentials=credentials
    )
    connection = pika.BlockingConnection(connection_params)
    channel = connection.channel()
    channel.queue_declare(queue=queue_name, durable=True)
    body_str = json.dumps(feedback_data, ensure_ascii=False)
    channel.basic_publish(
        exchange="",
        routing_key=queue_name,
        body=body_str,
        properties=pika.BasicProperties(delivery_mode=2),
    )
    connection.close()


# ============================================================
# Функция для завершения обратной связи (отправка итогового сообщения)
# ============================================================
async def complete_feedback(message: Message, state: FSMContext):
    data = await state.get_data()
    order_code = data.get("orderCode", "Не указан")
    rating = data.get("rating", "Отлично")
    comment = data.get("feedback_details", "") if rating == "Не отлично" else ""
    courier_chat_id = message.from_user.id

    feedback_payload = {
        "orderCode": order_code,
        "rating": rating,
        "courierChatId": courier_chat_id,
        "comment": comment,
    }
    await sync_to_async(publish_feedback_to_rabbitmq)(feedback_payload)
    logging.info(f"Feedback отправлен: {feedback_payload}")
    await state.clear()


# ============================================================
# Функция для отправки сообщения с клавиатурой для обратной связи
# ============================================================
async def send_feedback_keyboard(
    chat_id: int,
    order_data: dict,
    state: FSMContext,
):
    """
    Замена ReplyKeyboardMarkup на InlineKeyboardMarkup,
    при этом логика (ждём «Отлично»/«Не отлично» текстом) остаётся той же.
    """
    order_code = order_data.get("orderCode", "Не указан")
    client = order_data.get("customerName", "Не указан")
    client_phone = order_data.get("phone_number", "Не указан")
    client_adress = (
        order_data.get("delivery_info", {})
        .get("address", {})
        .get("formattedAddress", "Не указан")
    )
    client_entries = order_data.get("entries", [])
    data_entries = "\n".join(
        [
            f"{el['name']} - {el['totalPrice']} т * {el['quantity']} ед.изм."
            for el in client_entries
        ]
    )

    msg = (
        f"Вы только что доставили заказ 🚚 № {order_code}!\n\n"
        f"Клиент:\n {client}, 📞тел: {client_phone}!\n\n"
        f"Адрес:\n {client_adress}!\n\n"
        f"Заказ:\n {data_entries}!\n\n"
        "ℹ️Сообщите Информаию Настроения Покупателя (ИНП).\n"
        "⚠️Оцените Настроения Покупателя:"
    )

    # ### ИЗМЕНЕНО ДЛЯ INLINE-КНОПОК ###
    # Вместо обычной ReplyKeyboardMarkup используем InlineKeyboardMarkup
    # с callback_data = "Отлично" / "Не отлично".
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Отлично", callback_data="Отлично"),
                InlineKeyboardButton(text="Не отлично", callback_data="Не отлично"),
            ]
        ]
    )

    await bot.send_message(chat_id, msg, reply_markup=inline_kb)


# ============================================================
# Обработчики команд и сообщений
# ============================================================
async def set_group_handler(message: Message):
    group_chat_id = message.chat.id
    group_title = message.chat.title or "Без названия"
    parts = message.text.split(maxsplit=1)
    group_type = parts[1].strip() if len(parts) > 1 else ""
    await sync_to_async(TelegramGroup.objects.update_or_create)(
        chat_id=group_chat_id,
        defaults={"title": group_title, "group_type": group_type},
    )
    await message.answer(
        f'Группа "{group_title}" (тип: {group_type}) сохранена (chat_id={group_chat_id}).'
    )


# ============================================================
# Обработчик текстовой оценки («Отлично» / «Не отлично»)
# ============================================================
async def feedback_rating_handler(message: Message, state: FSMContext):
    current_state, data = await get_current_state(message.chat.id)
    order_code = data.get("orderCode", "Не указан")
    rating = message.text.strip()

    if rating not in ["Отлично", "Не отлично"]:
        await message.answer(
            "Пожалуйста, выберите один из вариантов: Отлично или Не отлично."
        )
        return

    await message.answer(f"✅ Спасибо за оценку ИНП: {rating} для заказа {order_code}.")
    logging.info(f"📊 User {message.from_user.id} оценил: {rating} для заказа ")

    # Сохраняем рейтинг в состояние
    await state.update_data(rating=rating)

    if rating == "Не отлично":
        await state.set_state(DeliveryFeedbackStates.waiting_for_feedback_details)
        await message.answer(
            "Пожалуйста, опишите, что именно не устроило клиента в доставке:"
        )
        # Оповещаем группы
        operator_groups = await sync_to_async(list)(TelegramGroup.objects.all())
        client_adress = (
            data.get("delivery_info", {})
            .get("address", {})
            .get("formattedAddress", "Не указан")
        )
        client_entries = data.get("entries", [])
        data_entries = "\n".join(
            [
                f"{el['name']} - {el['totalPrice']} т * {el['quantity']} ед.изм."
                for el in client_entries
            ]
        )

        # order = await sync_to_async(Order.objects.filter)(chat_id=chat_id)
        order = await Order.objects.filter(order_code=order_code).afirst()
        for group in operator_groups:
            alert_msg = (
                f"⚠️⚠️⚠️ Внимание!⚠️⚠️⚠️\n"
                f"Клиент недоволен доставкой заказа {order_code}.\n"
                f"Курьер:\n{data.get('courierName', 'Неизвестно')}\n"
                f"Адрес:\n{client_adress}\n"
                f"Заказ:\n{data_entries}\n"
                f"Клиент:\n{data.get('customerName', 'Неизвестно')}\n"
                f"📞 Телефон клиента:\n{data.get('phone_number', 'Не указан')}\n\n"
                "Подробнее тут (ссылка на админку):\n"
                f"http://185.100.67.246:8889/admin/app_orders/order/{order.pk}/change/"
            )
            await bot.send_message(group.chat_id, alert_msg)
    else:
        await state.set_state(DeliveryFeedbackStates.waiting_for_video)
        await message.answer(
            "Пожалуйста, отправьте видео отчет подтверждения доставки, либо введите /skip для пропуска."
        )


# ============================================================
# Добавляем ОБРАБОТЧИК CallbackQuery, который
# «подменяет» нажатие на инлайн-кнопку как ввод текста
# ============================================================
@dp.callback_query.register(
    feedback_rating_handler, 
    F.data.in_(["Отлично", "Не отлично"])
)
async def feedback_rating_handler(call: CallbackQuery, state: FSMContext):
    """
    Пользователь нажал на инлайн-кнопку «Отлично» или «Не отлично».
    Хотим, чтобы это работало так же, как если бы пользователь ввёл текст.
    """
    # "Подменяем" message.text, чтобы переиспользовать feedback_rating_handler
    fake_message = call.message
    fake_message.from_user = call.from_user
    fake_message.chat = call.message.chat
    fake_message.text = call.data

    # Вызываем тот же самый обработчик
    await feedback_rating_handler(fake_message, state)
    await call.answer()  # убираем "часики" у кнопки


# ============================================================
# Обработчики обратной связи (дальнейшие шаги)
# ============================================================
async def feedback_details_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != DeliveryFeedbackStates.waiting_for_feedback_details:
        return

    details = message.text.strip()
    if not details:
        await message.answer(
            "Комментарий не может быть пустым. Пожалуйста, опишите, что именно не устроило."
        )
        return

    await message.answer(f"Спасибо за ваш отзыв: {details}.")
    logging.info(f"User {message.from_user.id} оставил отзыв: {details}")
    await state.update_data(feedback_details=details)
    await state.set_state(DeliveryFeedbackStates.waiting_for_video)
    await message.answer(
        "Пожалуйста, отправьте видео отчет подтверждения доставки, либо введите /skip для пропуска."
    )


async def video_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != DeliveryFeedbackStates.waiting_for_video:
        return
    if message.video:
        video_file_id = message.video.file_id
        await message.answer(f"Видео получено! (File ID: {video_file_id})")
        logging.info(f"User {message.from_user.id} отправил видео: {video_file_id}")
        try:
            video_bytes = await download_video(video_file_id)
            data = await state.get_data()
            order_code = data.get("orderCode", "Не указан")
            courier_id = data.get("courier_id") or message.from_user.id
            await send_video_to_django(
                video_bytes, f"{video_file_id}.mp4", order_code, courier_id
            )
        except Exception as e:
            logging.error(f"Ошибка при скачивании/передаче видео: {e}")
    else:
        await message.answer("Видео не получено, но отзыв принят.")
    await complete_feedback(message, state)


async def skip_video_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state not in [
        DeliveryFeedbackStates.waiting_for_video,
        DeliveryFeedbackStates.waiting_for_feedback_details,
    ]:
        return
    await message.answer("Видео отчет пропущен. Спасибо!")
    logging.info(f"User {message.from_user.id} пропустил видео отчет.")
    await complete_feedback(message, state)


# ============================================================
# RabbitMQ Consumer
# ============================================================
async def rabbit_consumer():
    connection = await aio_pika.connect_robust(
        host=RABBIT_HOST, port=RABBIT_PORT, login=RABBIT_USER, password=RABBIT_PASSWORD
    )
    channel = await connection.channel()
    queue = await channel.declare_queue(RABBIT_QUEUE, durable=True)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                try:
                    body = message.body.decode("utf-8")
                    data = json.loads(body)
                    logging.info(f"Получили из RabbitMQ: {data}")

                    chat_id = data.get("chat_id")

                    if chat_id is None:
                        continue

                    state = FSMContext(dp.storage, key=f"{chat_id}:{chat_id}")
                    await state.update_data(**data)
                    await state.set_state(DeliveryFeedbackStates.begin_waiting_state)

                    await send_feedback_keyboard(
                        chat_id,
                        data,
                        state,
                    )
                    logging.info(f"Сообщение отправлено на chat_id={chat_id}")

                except Exception as e:
                    logging.exception(f"Ошибка при обработке сообщения: {e}")


# ============================================================
# Регистрация обработчиков и запуск бота
# ============================================================
async def my_orders_handler(message: Message):
    chat_id = message.chat.id
    await message.answer(f"📋 Этот функционал в разработке!")


async def help_handler(message: Message):
    help_text = (
        "ℹ️ <b>Доступные команды:</b>\n"
        "📦 <b>Мои заказы</b> — посмотреть список ваших заказов.\n"
        "ℹ️ <b>Помощь</b> — получить информацию о боте.\n"
        "/start — перезапустить бота.\n"
        "Если у вас возникли вопросы, напишите в поддержку. 📩"
    )
    await message.answer(help_text, parse_mode="HTML")


async def start_handler(message: Message):
    chat_id = message.chat.id
    first_name = message.from_user.first_name

    user = await sync_to_async(User.objects.filter)(chat_id=chat_id)
    if not await sync_to_async(user.exists)():
        welcome_text = f"👋 Привет, {first_name}!\n\n📌 Пожалуйста, поделитесь вашим номером телефона:"
    else:
        welcome_text = f"👋 С возвращением, {first_name}!"

    # Клавиатура с кнопкой "Поделиться номером"
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📞 Поделиться номером", request_contact=True),
            ],
            [KeyboardButton(text="📦 Мои заказы"), KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
    )

    await message.answer(
        welcome_text,
        reply_markup=keyboard,
    )


async def contact_handler(message: Message):
    if not message.contact:
        await message.answer(
            "❌ Ошибка: пожалуйста, используйте кнопку для отправки номера."
        )
        return

    phone_number = message.contact.phone_number[1:]
    chat_id = message.from_user.id
    first_name = message.from_user.first_name

    user = await sync_to_async(User.objects.filter)(phone_number=phone_number)
    if await sync_to_async(user.exists)():
        user_obj = await sync_to_async(user.first)()
        user_obj.chat_id = chat_id
        await sync_to_async(user_obj.save)()
        await message.answer(
            f"✅ Ваш номер {phone_number} успешно привязан к системе!",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await message.answer(
            f"❌ Пользователь с номером {phone_number} не найден в базе данных.",
            reply_markup=ReplyKeyboardRemove(),
        )


def register_handlers(dp: Dispatcher):
    dp.message.register(set_group_handler, Command(commands=["setgroup"]))
    dp.message.register(start_handler, Command("start"))
    dp.message.register(my_orders_handler, F.text == "📦 Мои заказы")
    dp.message.register(help_handler, F.text == "ℹ️ Помощь")
    dp.message.register(contact_handler, F.contact)

    # Оценка текстом
    dp.message.register(feedback_rating_handler, lambda m: m.text in ["Отлично", "Не отлично"])

    # Детали "Не отлично"
    dp.message.register(feedback_details_handler)
    # Видео и skip
    dp.message.register(video_handler, F.video)
    dp.message.register(skip_video_handler, lambda m: m.text and m.text.lower().startswith("/skip"))


async def main():
    logging.info("Запускаем бота и rabbit_consumer...")
    register_handlers(dp)
    # ВАЖНО: callback_query-хэндлер мы регистрируем декоратором выше
    asyncio.create_task(rabbit_consumer())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
