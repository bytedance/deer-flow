"""Identity API router — department / user / agent management and config inspection."""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config.paths import get_paths
from deerflow.identity.agent_identity import AgentIdentity, _SAFE_ID_RE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/identity", tags=["identity"])


# ── Shared validation helpers ──────────────────────────────────────────────────


def _validate_id_param(value: str, field_name: str) -> str:
    """Raise HTTP 422 if the ID does not match the safe-ID pattern."""
    if not _SAFE_ID_RE.match(value):
        raise HTTPException(status_code=422, detail=f"Invalid {field_name} {value!r}: must match [a-zA-Z0-9_.-]{{1,64}}")
    return value


def _require_dept_dir(dept_id: str) -> Path:
    dept_id = _validate_id_param(dept_id, "dept_id")
    path = get_paths().dept_dir(dept_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Department '{dept_id}' not found")
    return path


def _require_user_dir(dept_id: str, user_id: str) -> Path:
    _require_dept_dir(dept_id)
    user_id = _validate_id_param(user_id, "user_id")
    path = get_paths().dept_user_dir(dept_id, user_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found in department '{dept_id}'")
    return path


# ── Response / request models ──────────────────────────────────────────────────


class DeptInfo(BaseModel):
    dept_id: str
    has_config: bool = False
    user_count: int = 0


class UserInfo(BaseModel):
    user_id: str
    dept_id: str
    has_config: bool = False
    agent_count: int = 0


class AgentInfo(BaseModel):
    agent_name: str
    dept_id: str
    user_id: str
    has_config: bool = False
    has_memory: bool = False
    has_workspace: bool = False


class CreateDeptRequest(BaseModel):
    dept_id: str = Field(..., description="Department identifier (alphanumeric, dash, dot, underscore; max 64 chars)")


class CreateUserRequest(BaseModel):
    user_id: str = Field(..., description="User identifier (alphanumeric, dash, dot, underscore; max 64 chars)")


class CreateAgentRequest(BaseModel):
    agent_name: str = Field(..., description="Agent name (alphanumeric, dash, dot, underscore; max 64 chars)")


class PersonaFile(BaseModel):
    name: str = Field(..., description="Persona file name (e.g. SOUL.md)")
    content: str = Field(..., description="File content")
    source: str = Field(default="", description="Which identity layer this came from")


class PersonaResponse(BaseModel):
    files: list[PersonaFile] = Field(default_factory=list)


class PersonaUpdateRequest(BaseModel):
    content: str = Field(..., description="New file content")
    dept_id: str | None = Field(default=None)
    user_id: str | None = Field(default=None)
    agent_name: str | None = Field(default=None)


class SkillStateItem(BaseModel):
    name: str
    enabled: bool
    category: str


class SkillsResponse(BaseModel):
    skills: list[SkillStateItem] = Field(default_factory=list)


# ── Department endpoints ───────────────────────────────────────────────────────


@router.get("/depts", summary="List all departments")
async def list_depts() -> list[DeptInfo]:
    """List all configured departments."""
    depts_dir = get_paths().base_dir / "depts"
    if not depts_dir.exists():
        return []

    result: list[DeptInfo] = []
    for entry in sorted(depts_dir.iterdir()):
        if not entry.is_dir():
            continue
        dept_id = entry.name
        if not _SAFE_ID_RE.match(dept_id):
            continue
        users_dir = entry / "users"
        user_count = sum(1 for u in users_dir.iterdir() if u.is_dir()) if users_dir.exists() else 0
        result.append(DeptInfo(
            dept_id=dept_id,
            has_config=(entry / "config.yaml").exists(),
            user_count=user_count,
        ))
    return result


@router.post("/depts", status_code=201, summary="Create a department")
async def create_dept(body: CreateDeptRequest) -> DeptInfo:
    """Create the directory structure for a new department."""
    dept_id = _validate_id_param(body.dept_id, "dept_id")
    dept_dir = get_paths().dept_dir(dept_id)
    if dept_dir.exists():
        raise HTTPException(status_code=409, detail=f"Department '{dept_id}' already exists")
    try:
        (dept_dir / "users").mkdir(parents=True, exist_ok=True)
        logger.info("Created department directory: %s", dept_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create department: {exc}") from exc
    return DeptInfo(dept_id=dept_id, has_config=False, user_count=0)


# ── User endpoints ─────────────────────────────────────────────────────────────


@router.get("/depts/{dept_id}/users", summary="List users in a department")
async def list_users(dept_id: str) -> list[UserInfo]:
    """List all users registered under a department."""
    dept_dir = _require_dept_dir(dept_id)
    users_dir = dept_dir / "users"
    if not users_dir.exists():
        return []

    result: list[UserInfo] = []
    for entry in sorted(users_dir.iterdir()):
        if not entry.is_dir():
            continue
        uid = entry.name
        if not _SAFE_ID_RE.match(uid):
            continue
        agents_dir = entry / "agents"
        agent_count = sum(1 for a in agents_dir.iterdir() if a.is_dir()) if agents_dir.exists() else 0
        result.append(UserInfo(
            user_id=uid,
            dept_id=dept_id,
            has_config=(entry / "config.yaml").exists(),
            agent_count=agent_count,
        ))
    return result


@router.post("/depts/{dept_id}/users/{user_id}", status_code=201, summary="Create a user")
async def create_user(dept_id: str, user_id: str) -> UserInfo:
    """Create the directory structure for a new user under a department."""
    _require_dept_dir(dept_id)
    user_id = _validate_id_param(user_id, "user_id")
    user_dir = get_paths().dept_user_dir(dept_id, user_id)
    if user_dir.exists():
        raise HTTPException(status_code=409, detail=f"User '{user_id}' already exists in department '{dept_id}'")
    try:
        (user_dir / "agents").mkdir(parents=True, exist_ok=True)
        logger.info("Created user directory: %s", user_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create user: {exc}") from exc
    return UserInfo(user_id=user_id, dept_id=dept_id, has_config=False, agent_count=0)


# ── Agent endpoints ────────────────────────────────────────────────────────────


@router.get("/depts/{dept_id}/users/{user_id}/agents", summary="List agents for a user")
async def list_agents(dept_id: str, user_id: str) -> list[AgentInfo]:
    """List all agents registered under a user."""
    user_dir = _require_user_dir(dept_id, user_id)
    agents_dir = user_dir / "agents"
    if not agents_dir.exists():
        return []

    result: list[AgentInfo] = []
    for entry in sorted(agents_dir.iterdir()):
        if not entry.is_dir():
            continue
        agent_name = entry.name
        if not _SAFE_ID_RE.match(agent_name):
            continue
        result.append(AgentInfo(
            agent_name=agent_name,
            dept_id=dept_id,
            user_id=user_id,
            has_config=(entry / "config.yaml").exists(),
            has_memory=(entry / "memory.json").exists(),
            has_workspace=(entry / "workspace").exists(),
        ))
    return result


@router.post("/depts/{dept_id}/users/{user_id}/agents", status_code=201, summary="Create an agent")
async def create_agent(dept_id: str, user_id: str, body: CreateAgentRequest) -> AgentInfo:
    """Create the directory structure for a new agent under a user."""
    _require_user_dir(dept_id, user_id)
    agent_name = _validate_id_param(body.agent_name, "agent_name")
    identity = AgentIdentity(dept_id=dept_id, user_id=user_id, agent_name=agent_name)
    agent_dir = get_paths().identity_agent_dir(identity)
    if agent_dir is None:
        raise HTTPException(status_code=500, detail="Could not resolve agent directory")
    if agent_dir.exists():
        raise HTTPException(status_code=409, detail=f"Agent '{agent_name}' already exists")
    try:
        (agent_dir / "workspace").mkdir(parents=True, exist_ok=True)
        logger.info("Created agent directory: %s", agent_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {exc}") from exc
    return AgentInfo(agent_name=agent_name, dept_id=dept_id, user_id=user_id, has_config=False, has_memory=False, has_workspace=True)


# ── Effective config endpoint ──────────────────────────────────────────────────


@router.get("/effective-config", summary="Get effective merged config for an identity")
async def get_effective_config(
    dept_id: str | None = None,
    user_id: str | None = None,
    agent_name: str | None = None,
) -> dict[str, Any]:
    """Return the deep-merged config.yaml for the given identity.

    Returns the raw merged dict (before Pydantic validation) so callers can inspect
    which keys are overridden at each layer.
    """
    try:
        # Validate params before constructing identity (raises ValueError on bad input)
        if dept_id:
            dept_id = _validate_id_param(dept_id, "dept_id")
        if user_id:
            user_id = _validate_id_param(user_id, "user_id")
        if agent_name:
            agent_name = _validate_id_param(agent_name, "agent_name")

        identity = AgentIdentity(dept_id=dept_id, user_id=user_id, agent_name=agent_name)
        from deerflow.config.layered_config import load_layered_config_dict

        merged = load_layered_config_dict(identity)
        return {"identity": str(identity), "config": merged}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Persona endpoints ──────────────────────────────────────────────────────────

_PERSONA_FILES = [
    "IDENTITY.md", "SOUL.md", "USER.md", "AGENTS.md",
    "BOOTSTRAP.md", "HEARTBEAT.md", "TOOLS.md", "WORKFLOW_AUTO.md",
    "ERRORS.md", "LESSONS.md",
]


@router.get("/persona", summary="Get persona files for an identity")
async def get_persona(
    dept_id: str | None = None,
    user_id: str | None = None,
    agent_name: str | None = None,
) -> PersonaResponse:
    """Return persona file contents visible to the given identity (all layers)."""
    try:
        if dept_id:
            dept_id = _validate_id_param(dept_id, "dept_id")
        if user_id:
            user_id = _validate_id_param(user_id, "user_id")
        if agent_name:
            agent_name = _validate_id_param(agent_name, "agent_name")

        identity = AgentIdentity(dept_id=dept_id, user_id=user_id, agent_name=agent_name)
        paths = get_paths()
        dirs = paths.identity_persona_dirs(identity)

        files: list[PersonaFile] = []
        for d in dirs:
            source = str(d.relative_to(paths.base_dir)) if d != paths.base_dir else "global"
            for fname in _PERSONA_FILES:
                fpath = d / fname
                if fpath.exists():
                    try:
                        content = fpath.read_text(encoding="utf-8")
                        files.append(PersonaFile(name=fname, content=content, source=source))
                    except Exception:
                        pass
        return PersonaResponse(files=files)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/persona/{file_name}", summary="Write a persona file to an identity layer")
async def update_persona(file_name: str, body: PersonaUpdateRequest) -> dict[str, str]:
    """Write (create or overwrite) a persona file at the specified identity layer.

    The target layer is determined by the most specific non-None field in the request:
    agent > user > dept > global.
    """
    if file_name not in _PERSONA_FILES:
        raise HTTPException(status_code=422, detail=f"Unknown persona file '{file_name}'. Allowed: {_PERSONA_FILES}")

    try:
        dept_id = _validate_id_param(body.dept_id, "dept_id") if body.dept_id else None
        user_id = _validate_id_param(body.user_id, "user_id") if body.user_id else None
        agent_name = _validate_id_param(body.agent_name, "agent_name") if body.agent_name else None
    except HTTPException:
        raise

    paths = get_paths()
    identity = AgentIdentity(dept_id=dept_id, user_id=user_id, agent_name=agent_name)

    # Resolve target directory (most specific layer that's set)
    if agent_name and dept_id and user_id:
        target_dir = paths.identity_agent_dir(identity)
        if target_dir is None:
            raise HTTPException(status_code=400, detail="Cannot resolve agent directory")
    elif dept_id and user_id:
        target_dir = paths.dept_user_dir(dept_id, user_id)
    elif dept_id:
        target_dir = paths.dept_dir(dept_id)
    else:
        target_dir = paths.base_dir

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / file_name
        target_file.write_text(body.content, encoding="utf-8")
        logger.info("Wrote persona file: %s", target_file)
        return {"status": "ok", "path": str(target_file)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write persona file: {exc}") from exc


# ── Skills endpoint ────────────────────────────────────────────────────────────


@router.get("/skills", summary="Get effective skills for an identity")
async def get_identity_skills(
    dept_id: str | None = None,
    user_id: str | None = None,
    agent_name: str | None = None,
) -> SkillsResponse:
    """Return the skills list as seen by the given identity (layered extensions applied)."""
    try:
        if dept_id:
            dept_id = _validate_id_param(dept_id, "dept_id")
        if user_id:
            user_id = _validate_id_param(user_id, "user_id")
        if agent_name:
            agent_name = _validate_id_param(agent_name, "agent_name")

        identity = AgentIdentity(dept_id=dept_id, user_id=user_id, agent_name=agent_name)
        from deerflow.skills import load_skills

        skills = load_skills(identity=identity)
        return SkillsResponse(skills=[SkillStateItem(name=s.name, enabled=s.enabled, category=s.category) for s in skills])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
