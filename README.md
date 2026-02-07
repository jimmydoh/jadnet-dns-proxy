# jadnet-dns-proxy

A high-performance DNS-over-HTTPS (DoH) proxy with caching and connection pooling.

## Project Structure

The project is organized as a proper Python module:

```
.
├── src/
│   └── jadnet_dns_proxy/
│       ├── __init__.py       # Package initialization
│       ├── __main__.py       # Entry point for CLI execution
│       ├── cache.py          # DNS cache implementation with TTL
│       ├── config.py         # Configuration and logging setup
│       ├── protocol.py       # UDP DNS protocol handler
│       ├── resolver.py       # DoH resolver implementation
│       └── server.py         # Main server and worker pool
├── pyproject.toml            # Python project configuration
├── Dockerfile                # Container build configuration
└── compose.yaml              # Docker Compose configuration
```

## Running the Proxy

### Using Docker Compose (Recommended)

```bash
docker compose up
```

### Using Docker

```bash
docker build -t jadnet-dns-proxy .
docker run -p 5053:5053/udp jadnet-dns-proxy
```

### Using Python

```bash
pip install .
python -m jadnet_dns_proxy
```

## Configuration

Configure via environment variables:

- `LISTEN_PORT` - UDP port to listen on (default: 5053)
- `LISTEN_HOST` - Host address to bind to (default: 0.0.0.0)
- `DOH_UPSTREAM` - DoH server URL (default: https://cloudflare-dns.com/dns-query)
- `WORKER_COUNT` - Number of worker tasks (default: 10)
- `QUEUE_SIZE` - Request queue size (default: 1000)
- `CACHE_ENABLED` - Enable DNS caching (default: true)
- `LOG_LEVEL` - Logging level (default: INFO)