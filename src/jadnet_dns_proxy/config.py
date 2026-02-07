"""Configuration module for jadnet-dns-proxy."""
import os
import logging

# --- Configuration ---
LISTEN_PORT = int(os.getenv('LISTEN_PORT', 5053))
LISTEN_HOST = os.getenv('LISTEN_HOST', '0.0.0.0')

# DOH_UPSTREAM can be a single URL or comma-separated list of URLs
_doh_upstream_env = os.getenv('DOH_UPSTREAM', 'https://cloudflare-dns.com/dns-query')
DOH_UPSTREAMS = [url.strip() for url in _doh_upstream_env.split(',') if url.strip()]

WORKER_COUNT = int(os.getenv('WORKER_COUNT', 10))
QUEUE_SIZE = int(os.getenv('QUEUE_SIZE', 1000))
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
CACHE_ENABLED = os.getenv('CACHE_ENABLED', 'true').lower() == 'true'

# --- Logging Setup ---
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("async-doh")
