"""Connector implementation strategy metadata.

This lets the product encode which integrations should stay native and
which ones should ride an OSS substrate such as dlt or Unstructured.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from app.models.source import ConnectorType


class ConnectorProvider(str, enum.Enum):
    NATIVE = "native"
    DLT = "dlt"
    UNSTRUCTURED = "unstructured"
    OFFICIAL_API = "official_api"


@dataclass(frozen=True, slots=True)
class ConnectorStrategy:
    connector_type: ConnectorType
    provider: ConnectorProvider
    provider_label: str
    note: str


CONNECTOR_STRATEGIES: dict[ConnectorType, ConnectorStrategy] = {
    ConnectorType.LOCAL: ConnectorStrategy(
        connector_type=ConnectorType.LOCAL,
        provider=ConnectorProvider.NATIVE,
        provider_label="Built in",
        note="Generic file import surface used by the local CLI and import API.",
    ),
    ConnectorType.SLACK: ConnectorStrategy(
        connector_type=ConnectorType.SLACK,
        provider=ConnectorProvider.NATIVE,
        provider_label="Built in",
        note="Polling via conversations.history. Webhook event handling is planned but not yet active.",
    ),
    ConnectorType.NOTION: ConnectorStrategy(
        connector_type=ConnectorType.NOTION,
        provider=ConnectorProvider.DLT,
        provider_label="dlt",
        note="Planned to use a dlt verified source instead of hand-building the full Notion sync stack.",
    ),
    ConnectorType.ZOOM: ConnectorStrategy(
        connector_type=ConnectorType.ZOOM,
        provider=ConnectorProvider.OFFICIAL_API,
        provider_label="Official API",
        note="Transcript-first meeting source via the Zoom recordings API. Keeps ingestion focused on high-signal meeting transcripts, not media processing.",
    ),
    ConnectorType.GITHUB: ConnectorStrategy(
        connector_type=ConnectorType.GITHUB,
        provider=ConnectorProvider.OFFICIAL_API,
        provider_label="Official API",
        note=(
            "Polling-first GitHub issue, pull-request, review, and comment ingestion via "
            "the REST API. Keeps scope narrow around high-signal engineering context "
            "instead of broad repository mirroring."
        ),
    ),
    ConnectorType.GDRIVE: ConnectorStrategy(
        connector_type=ConnectorType.GDRIVE,
        provider=ConnectorProvider.UNSTRUCTURED,
        provider_label="Unstructured",
        note="Planned to use Unstructured for Drive ingestion and document extraction.",
    ),
    ConnectorType.GONG: ConnectorStrategy(
        connector_type=ConnectorType.GONG,
        provider=ConnectorProvider.OFFICIAL_API,
        provider_label="Official API",
        note="Likely to stay on the Gong API directly because transcript semantics matter more than generic ETL.",
    ),
}


def get_connector_strategy(connector_type: ConnectorType) -> ConnectorStrategy:
    return CONNECTOR_STRATEGIES[connector_type]
