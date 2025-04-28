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
from asgiref.sync import sync_to_async

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.bot import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from app_accounts.models import User, TelegramGroup

# ============================================================
# Конфигурация и инициализация
# ============================================================
API_TOKEN = "8118146507:AAEPYUDWh9S-aX6XQtVHvnIVaQ8Rc2FSnUs"
RABBIT_HOST = "185.100.67.246"
RABBIT_PORT = 5672
RABBIT_USER = "guest"
RABBIT_PASSWORD = "guest"
RABBIT_QUEUE = "telegram_queue"
RABBIT_QUEUE_FEEDBACK = "feedback_queue"
ENDPOINT_API_VIDEO = "http://127.0.0.1:8000/v1/api/upload_video/"

logging.basicConfig(level=logging.INFO)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)
bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

# Глобальный кэш для хранения данных заказа по chat_id
feedback_cache = {}


# ============================================================
# FSM-состояния для обратной связи доставки (используются для шагов, но не для хранения orderData)
# ============================================================
class DeliveryFeedbackStates(StatesGroup):
    waiting_for_feedback_details = State()  # если оценка "Не отлично"
    waiting_for_video = State()  # для видео отчета (общий шаг)


async def merge_state_data(state: FSMContext, new_data: dict):
    current_data = await state.get_data()
    current_data.update(new_data)
    await state.set_data(current_data)


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
    data.add_field(
        "courier_id", str(courier_id)
    )  # преобразуем в строку, если требуется
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
    # Извлекаем orderCode из глобального кэша
    order_data = feedback_cache.get(message.from_user.id, {})
    order_code = order_data.get("orderCode", "Не указан")
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
    # Удаляем данные из кэша
    feedback_cache.pop(message.from_user.id, None)


# ============================================================
# Функция для отправки сообщения с клавиатурой для обратной связи
# ============================================================
async def send_feedback_keyboard(chat_id: int, order_data: dict, state: FSMContext):
    print(f"------------------ order_data --------------->>> {order_data}")

    # Сохраняем все данные заказа в глобальном кэше для данного чата
    feedback_cache[chat_id] = order_data
    # Сохраняем объединённый словарь в состояние
    await merge_state_data(state, order_data)
    order_code = order_data.get("orderCode", "Не указан")
    msg = (
        f"Доставка заказа {order_code} завершена!\n\n"
        "Оцените Индекс Настроения Потрибителя (ИНП):"
    )
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отлично"), KeyboardButton(text="Не отлично")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await bot.send_message(chat_id, msg, reply_markup=keyboard)


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


async def link_phone_handler(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат команды:\n/link_phone <номер>")
        return
    phone_str = parts[1].strip()
    try:
        user_obj = await sync_to_async(User.objects.get)(phone_number=phone_str)
    except User.DoesNotExist:
        await message.answer(f"Пользователь с номером {phone_str} не найден в БД.")
        return
    user_obj.chat_id = message.from_user.id
    await sync_to_async(user_obj.save)()
    await message.answer(
        f"Найден пользователь с номером {phone_str}. ChatID={message.from_user.id} привязан!"
    )


async def any_text_handler(message: Message):
    await message.answer(
        "Я пока не умею на это отвечать. Попробуйте /setgroup или /link_phone."
    )


# ============================================================
# Обработчики обратной связи
# ============================================================
async def feedback_rating_handler(message: Message, state: FSMContext):
    print(f"------------------ MSG --------------->>> {message}")
    rating = message.text.strip()
    if rating not in ["Отлично", "Не отлично"]:
        await message.answer(
            "Пожалуйста, выберите один из вариантов: Отлично или Не отлично."
        )
        return

    await message.answer(f"Спасибо за оценку ИНП: {rating}.")
    logging.info(f"User {message.from_user.id} оценил: {rating}")
    # await state.update_data(rating=rating)
    await merge_state_data(state, {"rating": rating})
    # await state.set_data(existing)

    if rating == "Не отлично":
        await state.set_state(DeliveryFeedbackStates.waiting_for_feedback_details)
        await message.answer(
            "Пожалуйста, опишите, что именно не устроило клиента в доставке:"
        )
    else:
        await state.set_state(DeliveryFeedbackStates.waiting_for_video)
        await message.answer(
            "Пожалуйста, отправьте видео отчет подтверждения доставки, либо введите /skip для пропуска."
        )


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
            # Получаем данные из состояния
            data = await state.get_data()
            print(f"---- data ----- >>>> {data}")
            order_code = data.get("orderCode", "Не указан")
            # Если courier_id не сохранён в состоянии, можно использовать message.from_user.id, если они совпадают
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
                    if not chat_id:
                        groups = await sync_to_async(list)(TelegramGroup.objects.all())
                        if not groups:
                            logging.warning("Нет групп для отправки сообщения.")
                            continue
                        for group in groups:
                            await send_feedback_keyboard(
                                group.chat_id,
                                data,
                                FSMContext(
                                    dp.storage, f"{group.chat_id}:{group.chat_id}"
                                ),
                            )
                            logging.info(
                                f"Сообщение отправлено в группу {group.title} (chat_id={group.chat_id})"
                            )
                        continue
                    await send_feedback_keyboard(
                        chat_id, data, FSMContext(dp.storage, f"{chat_id}:{chat_id}")
                    )
                    logging.info(f"Сообщение отправлено на chat_id={chat_id}")

                except Exception as e:
                    logging.exception(f"Ошибка при обработке сообщения: {e}")


# ============================================================
# Регистрация обработчиков и запуск бота
# ============================================================
def register_handlers(dp: Dispatcher):
    dp.message.register(
        feedback_rating_handler, lambda m: m.text in ["Отлично", "Не отлично"]
    )
    dp.message.register(
        feedback_details_handler,
        lambda m: m.text
        and m.text.lower() not in ["/skip", "пропустить", "отлично", "не отлично"],
    )
    dp.message.register(video_handler, F.video)
    dp.message.register(
        skip_video_handler,
        lambda m: m.text
        and (m.text.lower().startswith("/skip") or "пропустить" in m.text.lower()),
    )
    dp.message.register(set_group_handler, Command(commands=["setgroup"]))
    dp.message.register(link_phone_handler, Command(commands=["link_phone"]))
    dp.message.register(any_text_handler, F.text)


async def main():
    logging.info("Запускаем бота и rabbit_consumer...")
    register_handlers(dp)
    asyncio.create_task(rabbit_consumer())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
