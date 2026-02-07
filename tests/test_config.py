"""Unit tests for the configuration module."""
import os
import pytest
from unittest.mock import patch


def test_default_configuration():
    """Test that default configuration values are set correctly."""
    # Import fresh to test defaults
    import importlib
    import jadnet_dns_proxy.config as config_module
    importlib.reload(config_module)
    
    # These should use defaults since no env vars are set in test
    assert isinstance(config_module.LISTEN_PORT, int)
    assert isinstance(config_module.LISTEN_HOST, str)
    assert isinstance(config_module.DOH_UPSTREAM, str)
    assert isinstance(config_module.WORKER_COUNT, int)
    assert isinstance(config_module.QUEUE_SIZE, int)
    assert isinstance(config_module.LOG_LEVEL, str)
    assert isinstance(config_module.CACHE_ENABLED, bool)


@patch.dict(os.environ, {
    'LISTEN_PORT': '8053',
    'LISTEN_HOST': '127.0.0.1',
    'DOH_UPSTREAM': 'https://dns.google/dns-query',
    'WORKER_COUNT': '20',
    'QUEUE_SIZE': '2000',
    'LOG_LEVEL': 'DEBUG',
    'CACHE_ENABLED': 'false'
})
def test_environment_variable_override():
    """Test that environment variables override defaults."""
    import importlib
    import jadnet_dns_proxy.config as config_module
    importlib.reload(config_module)
    
    assert config_module.LISTEN_PORT == 8053
    assert config_module.LISTEN_HOST == '127.0.0.1'
    assert config_module.DOH_UPSTREAM == 'https://dns.google/dns-query'
    assert config_module.WORKER_COUNT == 20
    assert config_module.QUEUE_SIZE == 2000
    assert config_module.LOG_LEVEL == 'DEBUG'
    assert config_module.CACHE_ENABLED is False


@patch.dict(os.environ, {'CACHE_ENABLED': 'true'})
def test_cache_enabled_true():
    """Test that CACHE_ENABLED correctly parses 'true'."""
    import importlib
    import jadnet_dns_proxy.config as config_module
    importlib.reload(config_module)
    
    assert config_module.CACHE_ENABLED is True


@patch.dict(os.environ, {'CACHE_ENABLED': 'false'})
def test_cache_enabled_false():
    """Test that CACHE_ENABLED correctly parses 'false'."""
    import importlib
    import jadnet_dns_proxy.config as config_module
    importlib.reload(config_module)
    
    assert config_module.CACHE_ENABLED is False


@patch.dict(os.environ, {'CACHE_ENABLED': 'TRUE'})
def test_cache_enabled_uppercase():
    """Test that CACHE_ENABLED is case-insensitive."""
    import importlib
    import jadnet_dns_proxy.config as config_module
    importlib.reload(config_module)
    
    assert config_module.CACHE_ENABLED is True


@patch.dict(os.environ, {'CACHE_ENABLED': 'invalid'})
def test_cache_enabled_invalid():
    """Test that invalid CACHE_ENABLED value defaults to false."""
    import importlib
    import jadnet_dns_proxy.config as config_module
    importlib.reload(config_module)
    
    assert config_module.CACHE_ENABLED is False


def test_logger_exists():
    """Test that logger is properly initialized."""
    from jadnet_dns_proxy.config import logger
    
    assert logger is not None
    assert logger.name == "async-doh"
