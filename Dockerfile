FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", \
  "python manage.py collectstatic --no-input --clear && \
   python manage.py migrate && \
   gunicorn wochi.wsgi --bind 0.0.0.0:8000 --workers 2"]
