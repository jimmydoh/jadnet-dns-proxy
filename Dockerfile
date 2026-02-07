FROM python:3.11-slim

WORKDIR /app

# Optimize python env
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy pyproject.toml first for better layer caching
COPY pyproject.toml .

# Install dependencies first (cached unless pyproject.toml changes)
RUN pip install --no-cache-dir dnslib==0.9.23 "httpx[http2]==0.24.1"

# Now copy source code
COPY src/ ./src/

# Install the actual package
RUN pip install --no-cache-dir .

# Healthcheck to ensure the port is open
HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('127.0.0.1', 5053)); s.send(b'');" || exit 1

EXPOSE 5053/udp

CMD ["python", "-m", "jadnet_dns_proxy"]
