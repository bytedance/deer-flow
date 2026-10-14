"""Shared, durable opt-out policy for proactive IM notices."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, String, select, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base
from deerflow.persistence.notification_deliveries.model import NotificationDeliveryRow

IM_NOTIFICATION_PROVIDERS = ("feishu", "wecom", "wechat", "qq")
DISABLED_BY_OWNER = "disabled_by_owner"


class ImNotificationPreferenceRow(Base):
    """Owner IDs also include auth-disabled local identities, like IM bindings."""

    __tablename__ = "im_notification_preferences"
    owner_user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())


class ImNotificationPreferencesRepository:
    """Independent preference rows; disabling also permanently closes the backlog.

    Missing values preserve the existing connected-channel default. Browser
    notifications use a different preference and remain unchanged.
    """

    def __init__(self, sessions):
        self.sessions = sessions

    @staticmethod
    async def get_in_session(session, user_id: str, *, lock_owner: bool = False) -> dict[str, bool]:
        # Serialize enqueue with opt-out on Postgres. The scheduler already holds
        # SQLite's writer lock; a patch takes it at its first upsert below.
        statement = select(ImNotificationPreferenceRow.provider, ImNotificationPreferenceRow.enabled).where(ImNotificationPreferenceRow.owner_user_id == user_id, ImNotificationPreferenceRow.provider.in_(IM_NOTIFICATION_PROVIDERS))
        if lock_owner and session.get_bind().dialect.name == "postgresql":
            # Materialize missing defaults so even the first opt-out serializes
            # with enqueue. Locks are always acquired in provider order.
            for provider in sorted(IM_NOTIFICATION_PROVIDERS):
                await session.execute(pg_insert(ImNotificationPreferenceRow).values(owner_user_id=user_id, provider=provider, enabled=True).on_conflict_do_nothing())
            statement = statement.order_by(ImNotificationPreferenceRow.provider).with_for_update()
        rows = await session.execute(statement)
        stored = dict(rows.all())
        return {provider: stored.get(provider, True) is True for provider in IM_NOTIFICATION_PROVIDERS}

    async def get(self, user_id: str) -> dict[str, bool]:
        async with self.sessions() as session:
            return await self.get_in_session(session, user_id)

    async def patch(self, user_id: str, values: dict[str, bool | None]) -> dict[str, bool]:
        if any(provider not in IM_NOTIFICATION_PROVIDERS or (value is not None and type(value) is not bool) for provider, value in values.items()):
            raise ValueError("Invalid IM notification preference")
        async with self.sessions() as session, session.begin():
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                await self.get_in_session(session, user_id, lock_owner=True)
            insert = pg_insert if dialect == "postgresql" else sqlite_insert
            for provider, value in sorted(values.items()):
                statement = insert(ImNotificationPreferenceRow).values(owner_user_id=user_id, provider=provider, enabled=value is not False)
                await session.execute(statement.on_conflict_do_update(index_elements=["owner_user_id", "provider"], set_={"enabled": statement.excluded.enabled}))
            disabled = [provider for provider, value in values.items() if value is False]
            if disabled:
                # Do not merely defer: reopening must never release old notices.
                # Clear tokens so a late worker cannot overwrite the opt-out.
                await session.execute(
                    update(NotificationDeliveryRow)
                    .where(NotificationDeliveryRow.owner_user_id == user_id, NotificationDeliveryRow.provider.in_(disabled), NotificationDeliveryRow.status.in_(("pending", "sending")))
                    .values(status="failed", last_error=DISABLED_BY_OWNER, claim_token=None, updated_at=datetime.now(UTC))
                )
            return await self.get_in_session(session, user_id)
