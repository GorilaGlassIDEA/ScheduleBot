FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py scheduler.py storage.py ./

# бот не должен работать от рута
RUN useradd --create-home appuser && mkdir -p /app/data && chown -R appuser /app/data
USER appuser

CMD ["python", "bot.py"]
