FROM python:3.11-slim

WORKDIR /app

# Optimize python env
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proxy.py .

# Healthcheck to ensure the port is open
HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('127.0.0.1', 5053)); s.send(b'');" || exit 1

EXPOSE 5053/udp

CMD ["python", "proxy.py"]
