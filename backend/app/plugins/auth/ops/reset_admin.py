"""CLI tool to reset an admin password."""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys

from sqlalchemy import select

from app.plugins.auth.domain.password import hash_password
from app.plugins.auth.ops.credential_file import write_initial_credentials
from app.plugins.auth.storage import DbUserRepository
from app.plugins.auth.storage.models import User as UserModel


async def _run(email: str | None) -> int:
    from store.persistence import create_persistence

    app_persistence = await create_persistence()
    await app_persistence.setup()
    try:
        if email:
            async with app_persistence.session_factory() as session:
                repo = DbUserRepository(session)
                user = await repo.get_user_by_email(email)
        else:
            async with app_persistence.session_factory() as session:
                stmt = select(UserModel).where(UserModel.system_role == "admin").limit(1)
                row = (await session.execute(stmt)).scalar_one_or_none()
                if row is None:
                    user = None
                else:
                    repo = DbUserRepository(session)
                    user = await repo.get_user_by_id(row.id)

        if user is None:
            print(f"Error: user '{email}' not found." if email else "Error: no admin user found.", file=sys.stderr)
            return 1

        new_password = secrets.token_urlsafe(16)
        updated_user = user.model_copy(
            update={
                "password_hash": hash_password(new_password),
                "token_version": user.token_version + 1,
                "needs_setup": True,
            }
        )
        async with app_persistence.session_factory() as session:
            repo = DbUserRepository(session)
            await repo.update_user(updated_user)
            await session.commit()

        cred_path = write_initial_credentials(user.email, new_password, label="reset")
        print(f"Password reset for: {user.email}")
        print(f"Credentials written to: {cred_path} (mode 0600)")
        print("Next login will require setup (new email + password).")
        return 0
    finally:
        await app_persistence.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset admin password")
    parser.add_argument("--email", help="Admin email (default: first admin found)")
    args = parser.parse_args()

    exit_code = asyncio.run(_run(args.email))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
