"""Durable per-user preferences; updates touch only explicitly supplied keys."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from deerflow.persistence.user.model import UserPreferenceRow


class UserPreferencesRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    async def get(self, user_id: str) -> dict:
        async with self.sessions() as session:
            rows = (await session.execute(select(UserPreferenceRow).where(UserPreferenceRow.user_id == user_id))).scalars()
            return {row.key: row.value for row in rows}

    async def patch(self, user_id: str, values: dict) -> None:
        async with self.sessions() as session, session.begin():
            insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
            # Consistent key order also avoids opposite-order row-lock cycles.
            for key, value in sorted(values.items()):
                statement = insert(UserPreferenceRow).values(user_id=user_id, key=key, value=value)
                await session.execute(statement.on_conflict_do_update(index_elements=["user_id", "key"], set_={"value": statement.excluded.value}))
