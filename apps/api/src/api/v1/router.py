"""v1 router assembly."""

from fastapi import APIRouter

from src.api.v1 import copilot, databases, engine, health, queries, recommendations

router = APIRouter()
router.include_router(health.router)
router.include_router(engine.router)
router.include_router(databases.router)
router.include_router(queries.router)
router.include_router(recommendations.router)
router.include_router(copilot.router)
