"""Entry point for jadnet-dns-proxy."""
import asyncio
from .server import main as server_main

__all__ = ['main']


def main():
    """Main entry point for the jadnet-dns-proxy console script."""
    try:
        asyncio.run(server_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

