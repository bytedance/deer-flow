"""Shared, durable opt-out policy for proactive IM notices."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, String, delete, select, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base
from deerflow.persistence.notification_deliveries.model import NotificationDeliveryRow

IM_NOTIFICATION_PROVIDERS = ("feishu", "wecom", "wechat", "qq")
IM_RUNTIME_NOTIFICATION_EVENTS = ("run_completed", "run_failed", "human_input_requested")
IM_NOTIFICATION_PREFERENCE_KEYS = (*IM_NOTIFICATION_PROVIDERS, *IM_RUNTIME_NOTIFICATION_EVENTS)
RUNTIME_NOTIFICATION_SOURCE_KINDS = ("run", "human_input_request")
DISABLED_BY_OWNER = "disabled_by_owner"


class ImNotificationPreferenceRow(Base):
    """Owner IDs also include auth-disabled local identities, like IM bindings."""

    __tablename__ = "im_notification_preferences"
    owner_user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())


class ImNotificationPreferencesRepository:
    """Independent preference rows; disabling also permanently closes the backlog.

    Missing values preserve the existing connected-channel default for providers
    (True) while runtime task/goal notification events remain opt-in (False).
    Browser notifications use a different preference and remain unchanged.
    """

    def __init__(self, sessions):
        self.sessions = sessions

    @staticmethod
    async def get_in_session(
        session,
        user_id: str,
        *,
        lock_owner: bool = False,
        include_events: bool = False,
    ) -> dict[str, bool]:
        # Serialize enqueue with opt-out on Postgres and SQLite. Materializing
        # provider defaults acquires SQLite's writer lock (or row locks on
        # Postgres) in deterministic key order before reading preferences.
        statement = select(ImNotificationPreferenceRow.provider, ImNotificationPreferenceRow.enabled).where(
            ImNotificationPreferenceRow.owner_user_id == user_id,
            ImNotificationPreferenceRow.provider.in_(IM_NOTIFICATION_PREFERENCE_KEYS),
        )
        if lock_owner:
            dialect = session.get_bind().dialect.name
            if dialect in ("postgresql", "sqlite"):
                insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert
                for key in sorted(IM_NOTIFICATION_PROVIDERS):
                    await session.execute(insert_fn(ImNotificationPreferenceRow).values(owner_user_id=user_id, provider=key, enabled=True).on_conflict_do_nothing())
                if dialect == "postgresql":
                    statement = statement.order_by(ImNotificationPreferenceRow.provider).with_for_update()
        rows = await session.execute(statement)
        stored = dict(rows.all())
        result = {provider: stored.get(provider, True) is True for provider in IM_NOTIFICATION_PROVIDERS}
        for event in IM_RUNTIME_NOTIFICATION_EVENTS:
            if include_events or event in stored:
                result[event] = stored.get(event, False) is True
        return result

    async def get(self, user_id: str, *, include_events: bool = False) -> dict[str, bool]:
        async with self.sessions() as session:
            return await self.get_in_session(session, user_id, include_events=include_events)

    async def get_event_preferences(self, user_id: str) -> dict[str, bool]:
        prefs = await self.get(user_id, include_events=True)
        return {event: prefs.get(event, False) is True for event in IM_RUNTIME_NOTIFICATION_EVENTS}

    async def patch(self, user_id: str, values: dict[str, bool | None]) -> dict[str, bool]:
        if any(key not in IM_NOTIFICATION_PREFERENCE_KEYS or (value is not None and type(value) is not bool) for key, value in values.items()):
            raise ValueError("Invalid IM notification preference")
        async with self.sessions() as session, session.begin():
            dialect = session.get_bind().dialect.name
            if dialect in ("postgresql", "sqlite"):
                await self.get_in_session(session, user_id, lock_owner=True)
            insert = pg_insert if dialect == "postgresql" else sqlite_insert
            for key, value in sorted(values.items()):
                if key in IM_RUNTIME_NOTIFICATION_EVENTS and value is None:
                    await session.execute(
                        delete(ImNotificationPreferenceRow).where(
                            ImNotificationPreferenceRow.owner_user_id == user_id,
                            ImNotificationPreferenceRow.provider == key,
                        )
                    )
                    continue
                enabled = (value is not False) if key in IM_NOTIFICATION_PROVIDERS else (value is True)
                statement = insert(ImNotificationPreferenceRow).values(owner_user_id=user_id, provider=key, enabled=enabled)
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["owner_user_id", "provider"],
                        set_={"enabled": statement.excluded.enabled},
                    )
                )
            now = datetime.now(UTC)
            disabled_providers = [key for key, value in values.items() if key in IM_NOTIFICATION_PROVIDERS and value is False]
            if disabled_providers:
                # Do not merely defer: reopening must never release old notices.
                # Clear tokens so a late worker cannot overwrite the opt-out.
                await session.execute(
                    update(NotificationDeliveryRow)
                    .where(
                        NotificationDeliveryRow.owner_user_id == user_id,
                        NotificationDeliveryRow.provider.in_(disabled_providers),
                        NotificationDeliveryRow.status.in_(("pending", "sending")),
                    )
                    .values(status="failed", last_error=DISABLED_BY_OWNER, claim_token=None, updated_at=now)
                )
            disabled_events = [key for key, value in values.items() if key in IM_RUNTIME_NOTIFICATION_EVENTS and value is not True]
            if disabled_events:
                await session.execute(
                    update(NotificationDeliveryRow)
                    .where(
                        NotificationDeliveryRow.owner_user_id == user_id,
                        NotificationDeliveryRow.source_kind.in_(RUNTIME_NOTIFICATION_SOURCE_KINDS),
                        NotificationDeliveryRow.event.in_(disabled_events),
                        NotificationDeliveryRow.status.in_(("pending", "sending")),
                    )
                    .values(status="failed", last_error=DISABLED_BY_OWNER, claim_token=None, updated_at=now)
                )
            return await self.get_in_session(session, user_id)
