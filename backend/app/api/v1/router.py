from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    articles,
    auth,
    exports,
    health,
    sources,
    tasks,
    wechat,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(wechat.router, prefix="/wechat", tags=["wechat"])
api_router.include_router(sources.router, prefix="/sources", tags=["sources"])
api_router.include_router(articles.router, prefix="/articles", tags=["articles"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(exports.router, prefix="/exports", tags=["exports"])
