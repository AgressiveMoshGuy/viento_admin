FROM python:3.14-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/django_admin_api

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

EXPOSE 8001

CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8001"]
