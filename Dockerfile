FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./main.py
COPY audit_board.py ./audit_board.py

EXPOSE 10000

CMD ["sh", "-c", "uvicorn audit_board:app --host 0.0.0.0 --port ${PORT:-10000}"]
