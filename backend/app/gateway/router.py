from fastapi import APIRouter

from app.plugins.auth.api.router import router as auth_router

from .routers import artifacts, channels, mcp, models, skills, uploads
from .routers.agents import router as agents_router
from .routers.langgraph import feedback_router, runs_router, suggestion_router, threads_router

router = APIRouter()

router.include_router(auth_router)
router.include_router(threads_router, prefix="/api/threads")
router.include_router(runs_router, prefix="/api/threads")
router.include_router(feedback_router, prefix="/api/threads")
router.include_router(suggestion_router)
router.include_router(agents_router)
router.include_router(channels.router)
router.include_router(artifacts.router)
router.include_router(mcp.router)
router.include_router(models.router)
router.include_router(skills.router)
router.include_router(uploads.router)
