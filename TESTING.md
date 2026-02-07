# Testing Documentation

This document describes the testing infrastructure and coverage for the jadnet-dns-proxy project.

## Test Framework

The project uses [pytest](https://docs.pytest.org/) as its testing framework, with the following plugins:
- **pytest-asyncio**: For testing async/await code
- **pytest-cov**: For measuring code coverage
- **pytest-mock**: For enhanced mocking capabilities

## Running Tests

### Install Test Dependencies

```bash
pip install -e ".[test]"
```

### Run All Tests

```bash
pytest tests/
```

### Run Tests with Coverage Report

```bash
pytest tests/ --cov=jadnet_dns_proxy --cov-report=term-missing
```

### Run Tests with HTML Coverage Report

```bash
pytest tests/ --cov=jadnet_dns_proxy --cov-report=html
# Open htmlcov/index.html in your browser
```

### Run Specific Test Files

```bash
pytest tests/test_cache.py -v
pytest tests/test_resolver.py -v
```

### Run Specific Test Functions

```bash
pytest tests/test_cache.py::TestDNSCache::test_cache_initialization -v
```

## Test Structure

Tests are organized in the `tests/` directory with the following structure:

```
tests/
├── __init__.py
├── test_bootstrap.py         # Tests for bootstrap DNS resolution
├── test_cache.py             # Tests for DNS cache functionality
├── test_config.py            # Tests for configuration loading
├── test_protocol.py          # Tests for UDP protocol handler
├── test_resolver.py          # Tests for DoH resolver
├── test_server.py            # Tests for server and worker functions
└── test_upstream_manager.py  # Tests for upstream server management
```

## Test Coverage

Current test coverage by module:

| Module | Coverage | Notes |
|--------|----------|-------|
| `bootstrap.py` | 100% | Full coverage of bootstrap DNS resolution |
| `cache.py` | 100% | Full coverage of DNS cache functionality |
| `config.py` | 100% | Full coverage of configuration loading |
| `protocol.py` | 100% | Full coverage of UDP protocol handler |
| `resolver.py` | 96% | Full coverage of DoH resolution with upstream manager |
| `upstream_manager.py` | 99% | Full coverage of multi-upstream management, load balancing, and health tracking |
| `server.py` | ~62% | Core worker functions covered; main entry point not tested |
| `__init__.py` | 100% | Package initialization |
| `__main__.py` | 0% | Entry point - not covered by automated tests (invoked when running `python -m jadnet_dns_proxy`) |

**Overall Coverage: ~84%**

### Coverage Exclusions

The following lines are excluded from coverage requirements:
- Pragma comments (`# pragma: no cover`)
- String representation methods (`__repr__`)
- Debug assertion failures
- Unimplemented methods
- Main entry points (`if __name__ == '__main__'`)

## Test Categories

### Unit Tests

Each module has comprehensive unit tests covering:

#### bootstrap.py
- IP address detection (returns unchanged)
- Successful hostname resolution via UDP
- No answer handling (returns original URL)
- Socket timeout handling
- Socket error handling
- Invalid DNS response handling
- Custom bootstrap DNS server usage
- Multiple A record handling

#### cache.py
- Cache initialization
- Setting and getting entries
- TTL expiration and clamping
- Cache enabled/disabled behavior
- Pruning expired entries
- Multiple key handling

#### config.py
- Default configuration values
- Environment variable overrides
- Multiple upstream parsing (comma-separated)
- Boolean parsing (CACHE_ENABLED)
- Logger initialization

#### protocol.py
- Protocol initialization
- Connection establishment
- Datagram reception
- Queue full handling
- Multiple datagram handling

#### resolver.py
- Successful DoH resolution
- Multiple answer handling (min TTL)
- No answer handling (default TTL)
- HTTP error handling
- Timeout handling
- HTTP status error handling
- Upstream manager integration
- No upstream available handling

#### server.py
- Worker cache hit handling
- Worker cache miss handling
- Worker error handling
- Invalid DNS packet handling
- Cleaner task functionality
- Stats task functionality
- Queue task_done tracking

#### upstream_manager.py
- Upstream server initialization
- Success and failure tracking
- Response time tracking
- Health status management (marking servers up/down)
- Success rate calculation
- Server recovery after failures
- Round-robin load balancing
- Skipping down servers
- Failover to best available server
- Statistics collection and logging

## Continuous Integration

Tests are automatically run via GitHub Actions on:
- Pushes to the `main`, `dev`, and `develop` branches
- Pull requests targeting the `main`, `dev`, and `develop` branches

See `.github/workflows/test.yml` for the CI configuration.

## Mock Strategy

Tests use mocking extensively to isolate units under test:
- **HTTP requests**: Mocked using `AsyncMock` for httpx client
- **DNS records**: Created using dnslib for realistic test data
- **Asyncio components**: Mocked using asyncio test utilities
- **Time**: Mocked where necessary to test TTL behavior
- **Configuration**: Patched using `unittest.mock.patch`

## Adding New Tests

When adding new features or modifying existing code:

1. **Write tests first** (TDD approach recommended)
2. **Ensure existing tests pass**
3. **Aim for high coverage** (>80% for new code)
4. **Use descriptive test names** that explain what is being tested
5. **Follow the AAA pattern**: Arrange, Act, Assert
6. **Mock external dependencies** (network, filesystem, time)
7. **Test edge cases** (empty data, errors, timeouts, etc.)

### Example Test Structure

```python
@pytest.mark.asyncio
async def test_descriptive_name():
    """Clear docstring explaining what this tests."""
    # Arrange: Set up test data and mocks
    mock_client = AsyncMock()
    test_data = b"test"
    
    # Act: Execute the code under test
    result = await function_under_test(mock_client, test_data)
    
    # Assert: Verify the results
    assert result == expected_value
    mock_client.method.assert_called_once()
```

## Future Improvements

Potential areas for enhanced testing:
- Integration tests for the full server lifecycle
- Performance/load testing
- End-to-end tests with real DNS queries
- Tests for the main() entry point
- Stress testing of the worker pool
- Testing with different DoH providers
