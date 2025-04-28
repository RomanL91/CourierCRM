FROM python:3.11.9-alpine

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# EXPOSE 8000

COPY ./requirements.txt .

RUN apk update && apk add --no-cache postgresql-dev gcc python3-dev musl-dev
RUN pip install --no-cache -r requirements.txt

COPY . .

RUN chmod +x /app/entrypoint.sh
