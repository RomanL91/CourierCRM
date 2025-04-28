#!/bin/sh
python manage.py makemigrations
python manage.py migrate
python manage.py collectstatic --no-input

python manage.py consume_orders --host=185.100.67.246 &
python manage.py consume_feedback &
python manage.py consume_qr_events &
python /app/bot/bot_telegram7.py &


# gunicorn --bind 0.0.0.0:8000 core.asgi -w 4 -k uvicorn.workers.UvicornWorker # с возможностью указания количества воркеров
uvicorn core.asgi:application --host 0.0.0.0 --port 8889