from fastapi import APIRouter

from app.api.endpoints import auth, chat, conversations, health, user, user_agent

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(user.router)
api_v1_router.include_router(user_agent.router)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/api")
api_router.include_router(chat.router, prefix="/api")
api_router.include_router(conversations.router, prefix="/api")
api_router.include_router(user_agent.current_user_router, prefix="/api")
api_router.include_router(api_v1_router)

__all__ = ["api_router"]
