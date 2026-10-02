from .base import Connector, ConnectorError, ConnectorUnavailable, FetchResult, RawListing  # noqa: F401
from .boards import AshbyConnector, GreenhouseConnector, LeverConnector
from .more import AdzunaConnector, PersonioConnector, RecruiteeConnector, SmartRecruitersConnector, WorkableConnector

# Source registry. Add connectors here (see docs/integrations.md).
REGISTRY: dict[str, type[Connector]] = {c.name: c for c in (
    GreenhouseConnector, LeverConnector, AshbyConnector,                    # global ATS boards
    PersonioConnector, SmartRecruitersConnector, WorkableConnector, RecruiteeConnector,  # popular with Swiss/DACH employers
    AdzunaConnector)}                                                        # search aggregator (needs a free key)

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
