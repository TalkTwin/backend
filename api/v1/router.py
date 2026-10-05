from fastapi import APIRouter

from api.v1 import account, admin, auth, avatars, consents, infra, jobs, voices

api_router = APIRouter(prefix="/v1")
# docs order: user -> account -> admin -> consents -> voices -> avatars -> jobs -> infra
api_router.include_router(auth.router)
api_router.include_router(account.router)
api_router.include_router(admin.router)
api_router.include_router(consents.router)
api_router.include_router(voices.router)
api_router.include_router(avatars.router)
api_router.include_router(jobs.router)
api_router.include_router(infra.router)
