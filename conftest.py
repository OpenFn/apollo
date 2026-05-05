"""Apollo root conftest — shared fixtures + filename-suffix tier markers."""
import pytest

from testing.fixtures import set_unit_test_env

# Run before any service module imports so dummy keys are in place.
set_unit_test_env()

pytest_plugins = ["testing.fixtures"]


def pytest_collection_modifyitems(config, items):
    """Auto-apply tier markers based on filename suffix and folder name."""
    for item in items:
        path = str(item.fspath)
        name = item.fspath.basename
        if name.endswith("_unit.py"):
            item.add_marker(pytest.mark.unit)
        elif name.endswith("_service.py"):
            item.add_marker(pytest.mark.service)
        elif name.endswith("_integration.py"):
            item.add_marker(pytest.mark.integration)
        elif "/acceptance/" in path or "\\acceptance\\" in path:
            item.add_marker(pytest.mark.acceptance)
