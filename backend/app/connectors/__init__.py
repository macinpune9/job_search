from .base import Connector, ConnectorError, ConnectorUnavailable, FetchResult, RawListing  # noqa: F401
from .boards import AshbyConnector, GreenhouseConnector, LeverConnector

# Source registry. Add connectors here (see docs/integrations.md).
REGISTRY: dict[str, type[Connector]] = {c.name: c for c in (GreenhouseConnector, LeverConnector, AshbyConnector)}

# Overridable in tests to inject mocked HTTP transports.
_factory = None


def set_factory(factory) -> None:
    global _factory
    _factory = factory


def make_connector(name: str) -> Connector:
    if name not in REGISTRY:
        raise ConnectorUnavailable(f"unknown source '{name}'")
    if _factory:
        return _factory(name)
    return REGISTRY[name]()
