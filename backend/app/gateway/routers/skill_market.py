import asyncio
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.gateway.deps import get_config, get_current_user_from_request, require_admin_user
from app.gateway.routers.skills import _scan_static_skill_markdown_or_raise
from deerflow.agents.lead_agent.prompt import refresh_user_skills_system_prompt_cache_async
from deerflow.config.app_config import AppConfig
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.safety.service import ContentSafetyService
from deerflow.persistence.skill_market.model import MarketSkillInstallRow, MarketSkillRow
from deerflow.skills.storage import get_or_new_user_skill_storage

router = APIRouter(prefix="/api", tags=["skill-market"])


class MarketSkillRequest(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    description: str = Field(min_length=1, max_length=10_000)
    version: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1)
    published: bool = True


class MarketSkillInstallRequest(BaseModel):
    """An already-installed skill is changed only after explicit confirmation."""

    update: bool = False


def serialize(row: MarketSkillRow, installed_version: str | None = None) -> dict:
    return {"id": row.id, "name": row.name, "description": row.description, "version": row.version, "content": row.content, "published": row.published, "installed_version": installed_version}


async def _list_installations(session, user_id: str) -> dict[str, str]:
    installs = await session.scalars(select(MarketSkillInstallRow).where(MarketSkillInstallRow.user_id == user_id))
    return {item.market_skill_id: item.installed_version for item in installs.all()}


@router.get("/skill-market")
async def list_market_skills(request: Request) -> list[dict]:
    user = await get_current_user_from_request(request)
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(503, "Skill market requires SQL database")
    async with sf() as session:
        rows = (await session.scalars(select(MarketSkillRow).where(MarketSkillRow.published.is_(True)))).all()
        installed = await _list_installations(session, str(user.id))
    return [serialize(row, installed.get(row.id)) for row in rows]


@router.get("/admin/skill-market")
async def list_admin_market_skills(request: Request) -> list[dict]:
    await require_admin_user(request, detail="Administrator access required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(503, "Skill market requires SQL database")
    async with sf() as session:
        rows = (await session.scalars(select(MarketSkillRow))).all()
    return [serialize(row) for row in rows]


@router.post("/skill-market/{skill_id}/install")
async def install_market_skill(
    skill_id: str,
    body: MarketSkillInstallRequest,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> dict:
    user = await get_current_user_from_request(request)
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(503, "Skill market requires SQL database")
    async with sf() as session:
        row = await session.get(MarketSkillRow, skill_id)
        if row is None or not row.published:
            raise HTTPException(404, "Published skill not found")
        install = await session.scalar(select(MarketSkillInstallRow).where(MarketSkillInstallRow.user_id == str(user.id), MarketSkillInstallRow.market_skill_id == skill_id))
        if install is not None and install.installed_version == row.version:
            return serialize(row, install.installed_version)
        if install is not None and not body.update:
            # Never overwrite a tenant's locally customised copy implicitly.
            return serialize(row, install.installed_version)
        await _scan_static_skill_markdown_or_raise(row.name, row.content, app_config=config)
        if install is None:
            install = MarketSkillInstallRow(id=uuid4().hex, user_id=str(user.id), market_skill_id=skill_id, installed_version=row.version)
            session.add(install)
        else:
            install.installed_version = row.version
        skill_name = row.name
        skill_content = row.content
        response = serialize(row, row.version)
        # Persist the tenant's file before recording a successful installation.
        # If filesystem storage rejects the write, no installed-version record
        # is committed and a later retry remains possible.
        storage = get_or_new_user_skill_storage(str(user.id), app_config=config)
        await asyncio.to_thread(storage.write_custom_skill, skill_name, "SKILL.md", skill_content)
        await session.commit()
    await refresh_user_skills_system_prompt_cache_async(str(user.id))
    return response


@router.delete("/skill-market/{skill_id}/install")
async def uninstall_market_skill(
    skill_id: str,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> dict[str, bool]:
    """Remove only the caller's installed copy of a market skill."""
    user = await get_current_user_from_request(request)
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(503, "Skill market requires SQL database")
    async with sf() as session:
        install = await session.scalar(
            select(MarketSkillInstallRow).where(
                MarketSkillInstallRow.user_id == str(user.id),
                MarketSkillInstallRow.market_skill_id == skill_id,
            )
        )
        if install is None:
            raise HTTPException(404, "Installed market skill not found")
        row = await session.get(MarketSkillRow, skill_id)
        if row is None:
            raise HTTPException(404, "Market skill not found")
        skill_name = row.name
        storage = get_or_new_user_skill_storage(str(user.id), app_config=config)
        try:
            await asyncio.to_thread(storage.delete_custom_skill, skill_name)
        except FileNotFoundError:
            # The user may already have removed the local copy through another
            # explicit flow.  Still clear this user's stale install record.
            pass
        await session.delete(install)
        await session.commit()
    await refresh_user_skills_system_prompt_cache_async(str(user.id))
    return {"success": True}


@router.post("/admin/skill-market")
async def publish_market_skill(
    body: MarketSkillRequest,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> dict:
    await require_admin_user(request, detail="Administrator access required")
    user = await get_current_user_from_request(request)
    await _scan_static_skill_markdown_or_raise(body.name, body.content, app_config=config)
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(503, "Skill market requires SQL database")
    async with sf() as session:
        row = await session.scalar(select(MarketSkillRow).where(MarketSkillRow.name == body.name))
        if row is None:
            row = MarketSkillRow(id=uuid4().hex, created_by=str(user.id), **body.model_dump())
            session.add(row)
        else:
            for key, value in body.model_dump().items():
                setattr(row, key, value)
        await session.commit()
        response = serialize(row)
    await ContentSafetyService(sf).record_admin_action(
        action="skill_market.published",
        target_type="market_skill",
        target_id=response["id"],
        actor_user_id=str(user.id),
        after_summary={"name": response["name"], "version": response["version"], "published": response["published"]},
    )
    return response
