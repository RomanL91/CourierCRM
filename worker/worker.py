import pika
import asyncio
import datetime
from typing import Optional

import json
import requests
from fastapi import FastAPI, Query

import uvicorn


# ------------------------------------------------------------------------------------
# 1) Глобальное хранилище для сессии
# ------------------------------------------------------------------------------------
class SessionStorage:
    def __init__(self):
        self.session: Optional[requests.Session] = None
        self.last_auth_time: Optional[datetime.datetime] = None
        self.mc_sid: Optional[str] = None  # mc-sid

    def is_session_valid(self, valid_for_seconds: int = 7200) -> bool:
        """
        Простейшая проверка актуальности сессии (по умолчанию 2 часа = 7200 секунд).
        Можно заменить или расширить логику по своему усмотрению.
        """
        if not self.last_auth_time:
            return False
        delta = datetime.datetime.now() - self.last_auth_time
        return delta.total_seconds() < valid_for_seconds


global_session_storage = SessionStorage()


# ------------------------------------------------------------------------------------
# 2) Функция, выполняющая авторизацию в Kaspi (все шаги)
# ------------------------------------------------------------------------------------
def do_authorization() -> Optional[requests.Session]:
    """
    Делает все шаги авторизации:
      1) POST на /api/p/login
      2) GET /?continue
      3) GET /oauth2/authorization/1
    + Проверочный запрос: заходит на страницу kaspi.kz/mc
      и проверяет, нет ли редиректа на логин.
    Возвращает готовый объект requests.Session или None при неудаче.
    """
    print("== Попытка авторизации в Kaspi ==")
    session = requests.Session()

    common_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/132.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;"
            "q=0.8,application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
    }

    # (1) Логин
    login_url = "https://idmc.shop.kaspi.kz/api/p/login"
    login_payload = {
        "_u": "program@sck-1.kz",  # Ваш логин
        "_p": "oyB9beYr4O",  # Ваш пароль
    }
    login_headers = {
        **common_headers,
        "Content-Type": "application/json",
        "Referer": "https://idmc.shop.kaspi.kz/login",
        "Origin": "https://idmc.shop.kaspi.kz",
    }

    resp_login = session.post(
        login_url, json=login_payload, headers=login_headers, allow_redirects=False
    )
    if resp_login.status_code != 200:
        print("Не удалось залогиниться (ожидали 200), код:", resp_login.status_code)
        return None

    # (2) GET /?continue
    step2_url = "https://idmc.shop.kaspi.kz/?continue"
    step2_headers = {**common_headers, "Referer": "https://idmc.shop.kaspi.kz/login"}
    resp_continue = session.get(step2_url, headers=step2_headers, allow_redirects=True)
    # Можно проверить resp_continue.status_code, но там часто идёт редирект

    # (3) OAuth
    oauth_url = "https://mc.shop.kaspi.kz/oauth2/authorization/1"
    oauth_headers = {
        **common_headers,
        "Referer": "https://kaspi.kz/",
    }
    resp_oauth = session.get(oauth_url, headers=oauth_headers, allow_redirects=True)

    # Проверяем наличие mc-sid
    mc_cookies = session.cookies.get_dict(domain="mc.shop.kaspi.kz")
    if "mc-sid" not in mc_cookies:
        print("mc-sid не обнаружен. Авторизация не завершена.")
        return None

    print(
        "Авторизация на mc.shop.kaspi.kz потенциально успешна. mc-sid=",
        mc_cookies["mc-sid"],
    )

    # (4) Тестовый запрос – проверяем, что мы действительно «внутри»:
    # Вместо mc.shop.kaspi.kz/ используем https://kaspi.kz/mc/ (основная страница кабинета)
    test_url = "https://kaspi.kz/mc/"
    test_resp = session.get(test_url, headers=common_headers, allow_redirects=True)

    if test_resp.status_code == 200:
        final_url = test_resp.url
        # Если нас «выкинуло» на логин, скорее всего увидим url типа idmc.shop.kaspi.kz/login
        if "idmc.shop.kaspi.kz/login" in final_url:
            print("Похоже, при заходе в личный кабинет нас перекинуло на логин.")
            return None
        else:
            print(f"Тестовый GET вернулся 200, конечный URL = {final_url}")
            print("Все проверки пройдены. Мы авторизованы.")
    else:
        print(f"Тестовый GET на {test_url} вернул статус {test_resp.status_code}.")
        return None

    return session


# ------------------------------------------------------------------------------------
# 3) Фоновые задачи (авторизация / периодический сбор заказов)
# ------------------------------------------------------------------------------------
async def auth_loop_background():
    """
    Бесконечный цикл авторизации (раз в 2 часа).
    Если авторизация падает, пытаемся снова через 1 минуту.
    """
    while True:
        session = do_authorization()
        if session is not None:
            global_session_storage.session = session
            global_session_storage.mc_sid = session.cookies.get_dict(
                domain="mc.shop.kaspi.kz"
            ).get("mc-sid")
            global_session_storage.last_auth_time = datetime.datetime.now()
            print("Сессия успешно обновлена в:", global_session_storage.last_auth_time)
            # Спим 2 часа
            await asyncio.sleep(2 * 60 * 60)
        else:
            # Повторяем попытку авторизации через 1 минуту
            print("Авторизация не удалась. Повторим через 1 минуту...")
            await asyncio.sleep(60)


async def fetch_orders_background():
    """
    (Необязательная) фоновая задача: каждые 2 минуты
    выгружает заказы с небольшим окном (2 минуты).
    """
    start_ts = int(datetime.datetime.now().timestamp() * 1000) - 2 * 60 * 60 * 1000
    step_ms = 2 * 60 * 1000  # шаг в 2 минуты

    while True:
        if not global_session_storage.is_session_valid():
            print("Сессия не готова или устарела, ждём 10 секунд...")
            await asyncio.sleep(10)
            continue

        end_ts = start_ts + step_ms
        print(f"Запрашиваем промежуток {start_ts} – {end_ts}")

        url = (
            "https://mc.shop.kaspi.kz/mc/api/orderTabs/archive"
            f"?start=0&count=100&fromDate={start_ts}&toDate={end_ts}"
            "&statuses=COMPLETED"
            "&_m=BUGA"
        )

        session = global_session_storage.session
        resp = session.get(url)

        if resp.status_code == 200:
            data = resp.json()
            orders = data.get("data", [])
            print(f"Получили {len(orders)} заказов в промежутке {start_ts} – {end_ts}")
            # Здесь можно сохранить заказы в БД
            process_orders_data(data, global_session_storage.session)

        else:
            print(f"Ошибка при получении заказов: {resp.status_code}, {resp.text}")

        start_ts = end_ts
        await asyncio.sleep(2 * 60)  # cпим 2 минуты, повторяем


# ------------------------------------------------------------------------------------
# 4) Жизненный цикл приложения (lifespan) вместо on_event("startup") / on_event("shutdown")
# ------------------------------------------------------------------------------------
async def lifespan(app: FastAPI):
    """
    - до yield: код, выполняющийся "при старте" приложения
    - после yield: код, выполняющийся "при завершении" приложения
    """
    # Запускаем авторизацию (обязательная задача)
    auth_task = asyncio.create_task(auth_loop_background())

    # Если нужно – запускаем и фоновый парсинг заказов раз в 2 минуты
    # fetch_task = asyncio.create_task(fetch_orders_background())

    # Выходим в "рабочее" состояние
    yield

    # Когда приложение останавливается, завершаем задачи
    auth_task.cancel()
    # fetch_task.cancel()


# ------------------------------------------------------------------------------------
# 5) Инициализация приложения FastAPI с помощью lifespan
# ------------------------------------------------------------------------------------
app = FastAPI(lifespan=lifespan)


# ------------------------------------------------------------------------------------
# Утилиты
# ------------------------------------------------------------------------------------
def publish_to_rabbitmq(
    message_body: dict,
    queue_name: str = "orders_queue",
    host: str = "185.100.67.246",
    port: int = 5672,
    username: str = "guest",
    password: str = "guest",
):
    """
    Подключаемся к RabbitMQ, создаём/объявляем очередь (если нужно),
    и отправляем туда сообщение (message_body).

    В реальном проекте лучше держать connection/channel открытыми
    или использовать пул соединений, а не открывать/закрывать
    при каждом сообщении.
    """
    credentials = pika.PlainCredentials(username, password)
    connection_params = pika.ConnectionParameters(
        host=host, port=port, credentials=credentials
    )

    # Открываем соединение
    connection = pika.BlockingConnection(connection_params)
    channel = connection.channel()

    # Объявляем очередь (idempotent)
    channel.queue_declare(queue=queue_name, durable=True)

    # Публикуем сообщение:
    body_str = json.dumps(message_body, ensure_ascii=False)
    channel.basic_publish(
        exchange="",  # Используем default exchange
        routing_key=queue_name,  # В какой queue шлём
        body=body_str,
        properties=pika.BasicProperties(
            delivery_mode=2  # Сохранение сообщения на диске (persistent)
        ),
    )

    # Закрываем соединение
    connection.close()


def fetch_order_details(order_code: str, session: requests.Session) -> dict:
    """
    Делаем дополнительный запрос, чтобы получить детальную информацию
    для заказа с кодом order_code.
    """
    detail_url = f"https://mc.shop.kaspi.kz/mc/api/order/{order_code}?_m=BUGA"

    # При желании, можно добавить те же заголовки, что и при работе с archive:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/132.0.0.0 Safari/537.36"
        ),
        "Referer": "https://kaspi.kz/mc/",
        "Accept": "application/json",
    }

    resp = session.get(detail_url, headers=headers)
    if resp.status_code == 200:
        details = resp.json()
        # Отправляем в RabbitMQ (указываем очередь, хост, порт, если нужно):
        publish_to_rabbitmq(message_body=details)
        return details
    else:
        print(
            f"[!] Ошибка при получении деталей заказа {order_code}: {resp.status_code}"
        )
        return {}


def process_orders_data(orders_data: dict, session: requests.Session):
    """
    Принимает результат основного запроса (dict с полями "total" и "orders"),
    и для каждого заказа делает запрос fetch_order_details(...).
    Результаты выводит в консоль.
    """
    orders_list = orders_data.get("orders", [])
    print(f"Всего заказов в ответе: {len(orders_list)}")

    for order in orders_list:
        order_code = order.get("orderCode")
        if not order_code:
            continue  # вдруг нет кода?

        print(f"--- Получаем детали для заказа {order_code} ---")
        details = fetch_order_details(order_code, session)
        print(f"Детали заказа {order_code}:")
        print(details)
        print("-----\n")


# ------------------------------------------------------------------------------------
# 6) Пример эндпоинта /orders для ручного запроса архива
# ------------------------------------------------------------------------------------
@app.get("/orders")
def get_archived_orders(
    from_date: int = Query(..., description="fromDate (timestamp в мс)"),
    to_date: int = Query(..., description="toDate (timestamp в мс)"),
    count: int = 100,
):
    """
    Эндпоинт для ручного запроса архивных заказов в заданном интервале (в мс).

    Пример запроса:
    GET /orders?fromDate=1741719600000&toDate=1741781941722
    """
    if not global_session_storage.session:
        return {
            "error": "Сессия ещё не готова. Подождите авторизации или проверьте логи."
        }

    url = (
        "https://mc.shop.kaspi.kz/mc/api/orderTabs/archive"
        f"?start=0&count={count}"
        f"&fromDate={from_date}"
        f"&toDate={to_date}"
        "&statuses=COMPLETED"
        "&_m=BUGA"
    )

    # Расширенный набор заголовков, взятый из DevTools (и немного подчищенный)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/134.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;"
            "q=0.8,application/signed-exchange;v=b3;q=0.7"
        ),
        # "Accept-Encoding": "gzip, deflate, br, zstd",
        # "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        # "Cache-Control": "max-age=0",
        # "Upgrade-Insecure-Requests": "1",
        # "Sec-Fetch-Dest": "document",
        # "Sec-Fetch-Mode": "navigate",
        # "Sec-Fetch-Site": "none",
        # "Sec-Fetch-User": "?1",
        # # Эти заголовки, если хотите, тоже можно добавить –
        # # но важно учесть синтаксис кавычек
        # "Sec-CH-UA": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
        # "Sec-CH-UA-Mobile": "?0",
        # "Sec-CH-UA-Platform": '"Windows"',
        # В "Referer" обычно указывается https://kaspi.kz/mc/
        # или https://mc.shop.kaspi.kz/
        "Referer": "https://kaspi.kz/mc/",
    }

    resp = global_session_storage.session.get(url, headers=headers)
    if resp.status_code == 200:
        data = resp.json()
        # Вызовим нашу функцию, чтобы для каждого "order" сделать запрос деталей
        process_orders_data(data, global_session_storage.session)
        return data
    else:
        return {
            "error": f"Не удалось получить архивные заказы: {resp.status_code}",
            "text": resp.text,
        }


# ------------------------------------------------------------------------------------
# 7) Точка входа
# ------------------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
