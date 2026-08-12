"""Bonfire-TDS 后端入口。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import (
    appimages,
    catalog,
    cluster,
    connectors,
    contract_templates,
    contracts,
    health,
    identity,
    jobs,
    kuscia_logs,
    products,
    projects,
    usage,
    audit,
    kuscia_masters,
)

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(cluster.router, prefix=settings.api_prefix)
app.include_router(identity.router, prefix=settings.api_prefix)
app.include_router(connectors.router, prefix=settings.api_prefix)
app.include_router(catalog.router, prefix=settings.api_prefix)
app.include_router(products.router, prefix=settings.api_prefix)
app.include_router(projects.router, prefix=settings.api_prefix)
app.include_router(appimages.router, prefix=settings.api_prefix)
app.include_router(contracts.router, prefix=settings.api_prefix)
app.include_router(contract_templates.router, prefix=settings.api_prefix)
app.include_router(jobs.router, prefix=settings.api_prefix)
app.include_router(usage.router, prefix=settings.api_prefix)
app.include_router(audit.router, prefix=settings.api_prefix)
app.include_router(kuscia_masters.router, prefix=settings.api_prefix)
app.include_router(kuscia_logs.router, prefix=settings.api_prefix)


@app.get("/")
def root() -> dict:
    return {"code": 0, "message": "ok", "data": {"service": settings.app_name}}
