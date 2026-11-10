FROM python:3.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# El runner y las conexiones WebSocket viven en memoria de proceso; no añadir --workers
# hasta contar con transporte compartido para difundir realtime entre procesos.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
