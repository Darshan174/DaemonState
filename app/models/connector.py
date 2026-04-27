from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship as orm_relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.source import ConnectorType, enum_values

if TYPE_CHECKING:
    from app.models.user import Workspace


class ConnectorStatus(str, enum.Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class Connector(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "connectors"
    __table_args__ = (UniqueConstraint("workspace_id", "connector_type"),)

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connector_type: Mapped[ConnectorType] = mapped_column(
        Enum(
            ConnectorType,
            name="connector_type_enum",
            values_callable=enum_values,
        ),
        nullable=False,
    )
    status: Mapped[ConnectorStatus] = mapped_column(
        Enum(
            ConnectorStatus,
            name="connector_status_enum",
            values_callable=enum_values,
        ),
        nullable=False,
        default=ConnectorStatus.DISCONNECTED,
        server_default=text("'disconnected'"),
    )
    oauth_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    workspace: Mapped["Workspace"] = orm_relationship(back_populates="connectors")
    sync_state: Mapped["SyncState | None"] = orm_relationship(
        back_populates="connector",
        cascade="all, delete-orphan",
        uselist=False,
    )


class SyncState(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sync_states"
    __table_args__ = (UniqueConstraint("connector_id"),)

    connector_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("connectors.id", ondelete="CASCADE"),
        nullable=False,
    )
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_item_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    connector: Mapped["Connector"] = orm_relationship(back_populates="sync_state")


class ConnectorAppConfig(TimestampMixin, Base):
    __tablename__ = "connector_app_configs"
    __table_args__ = (UniqueConstraint("connector_type"),)

    connector_type: Mapped[ConnectorType] = mapped_column(
        Enum(
            ConnectorType,
            name="connector_type_enum",
            values_callable=enum_values,
        ),
        primary_key=True,
    )
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
