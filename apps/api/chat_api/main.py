import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from chat_api.api.v1.endpoints import health
from chat_api.api.v1.router import router
from chat_api.core.config import Settings
from chat_api.services.agentcore import close_client

logging.basicConfig(level=logging.INFO)

# Browser origins allowed to call the API. CORS_ALLOW_ORIGINS is a comma-separated exact
# list; the regex additionally clears Vercel preview URLs. Local dev needs neither.
_cors_origins = [
    o.strip()
    for o in os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = Settings.from_env()
    yield
    await close_client()


app = FastAPI(title="Doc Pipeline API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://[a-z0-9-]+\.vercel\.app",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(health.router)
app.include_router(router)
