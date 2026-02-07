# jadnet-dns-proxy

A high-performance DNS-over-HTTPS (DoH) proxy with caching and connection pooling.

## CI/CD Workflows

This project uses GitHub Actions for automated releases and Docker image builds:

- **Release on Main**: When code is pushed to the `main` branch, a workflow automatically extracts the version from `pyproject.toml` and creates a new GitHub release with the corresponding tag (e.g., `v0.1.0`). After creating the release, it automatically triggers the Docker build workflow.
- **Docker Build & Push**: Builds and pushes the Docker image to GitHub Container Registry with the `latest` tag and version-specific semantic versioning tags. This workflow is triggered:
  - Automatically when the release workflow completes (via workflow_dispatch)
  - When pushing to `dev` or `development` branches (creates a `dev` tag)
  - Manually via the Actions tab in GitHub

To trigger a new release, simply update the version in `pyproject.toml` and merge to the `main` branch. The Docker images will be built and published automatically.

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
- `BOOTSTRAP_DNS` - DNS server IP for bootstrapping DoH hostname resolution (default: 8.8.8.8)
- `WORKER_COUNT` - Number of worker tasks (default: 10)
- `QUEUE_SIZE` - Request queue size (default: 1000)
- `CACHE_ENABLED` - Enable DNS caching (default: true)
- `LOG_LEVEL` - Logging level (default: INFO)

### Bootstrap DNS Resolution

When the DNS proxy container is the only DNS resolver in an isolated network, it may encounter a chicken-and-egg problem: it needs to resolve the DoH provider's hostname (e.g., `cloudflare-dns.com`) using DNS, but it is itself the DNS resolver.

To solve this, the proxy implements a **bootstrap mechanism** that performs a one-shot raw UDP query to a fallback DNS server (configured via `BOOTSTRAP_DNS`) at startup. This bootstrap query resolves the DoH hostname to an IP address, bypassing the system resolver entirely.

**Key features:**
- If the `DOH_UPSTREAM` is already an IP address, no bootstrap is performed
- The bootstrap query is sent directly to `BOOTSTRAP_DNS` via raw UDP (port 53)
- The resolved IP is used to replace the hostname in the DoH URL
- On bootstrap failure, the proxy falls back to the original URL (system resolver)
- Default bootstrap DNS is Google Public DNS (8.8.8.8)

**Example:** If `DOH_UPSTREAM=https://cloudflare-dns.com/dns-query`, the proxy will:
1. Query `BOOTSTRAP_DNS` (8.8.8.8) for `cloudflare-dns.com`
2. Replace the hostname with the resolved IP (e.g., `https://104.16.248.249/dns-query`)
3. Use the IP-based URL for all DoH requests

This ensures the proxy can function correctly even when it's the sole DNS resolver in the network.