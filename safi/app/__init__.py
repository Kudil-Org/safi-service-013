from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

from safi import config
from safi.models import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    IngestRequest,
    InstantiateRequest,
    InstantiateResponse,
    InstanceResponse,
    KnowledgeItem,
)
from safi.rbac import parse_roles
from safi.service import RootServiceExpert, ServiceError


def create_app(db_path=None, root_dir=None, templates_dir=None, llm=None):
    app = FastAPI(
        title="SAFI Root Service Expert API",
        version=config.SERVICE_VERSION,
        description=(
            "Service 013 — Root Service Expert. Instantiates scoped Service Expert "
            "instances from Root templates, ingests provenance-tagged knowledge, and "
            "serves RBAC-sensitive Chat over a single interface."
        ),
    )
    root = RootServiceExpert(
        db_path=db_path, root_dir=root_dir, templates_dir=templates_dir, llm=llm
    )
    app.state.root = root

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    def _identity(request: Request):
        user_id = (request.headers.get("X-User-Id") or "").strip()
        roles = parse_roles(request.headers.get("X-Roles"))
        return user_id, roles

    @app.get("/health", response_model=HealthResponse)
    def health():
        return root.health()

    @app.post("/service-experts", status_code=201, response_model=InstantiateResponse)
    def instantiate(request: Request, payload: InstantiateRequest):
        return root.instantiate(payload.model_dump())

    @app.post("/service-experts/{id}/ingest", status_code=201, response_model=KnowledgeItem)
    def ingest(request: Request, id: str, payload: IngestRequest):
        user_id, roles = _identity(request)
        return root.ingest(id, payload.model_dump(), user_id, roles)

    @app.post("/service-experts/{id}/chat", response_model=ChatResponse)
    def chat(request: Request, id: str, payload: ChatRequest):
        user_id, roles = _identity(request)
        return root.chat(id, payload.message, user_id, roles)

    @app.get("/service-experts/{id}", response_model=InstanceResponse)
    def get_service_expert(request: Request, id: str):
        _, roles = _identity(request)
        return root.get(id, roles)

    @app.get("/openapi.yaml", include_in_schema=False)
    def openapi_contract():
        from fastapi.responses import Response

        text = config.OPENAPI_FILE.read_text(encoding="utf-8")
        return Response(content=text, media_type="application/yaml")

    @app.get("/", include_in_schema=False)
    def ui_root():
        return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))

    @app.get("/demo", include_in_schema=False)
    def ui_demo():
        return HTMLResponse((WEB_DIR / "tester.html").read_text(encoding="utf-8"))

    @app.get("/ui/instances", include_in_schema=False)
    def ui_instances():
        return {"instances": [row["id"] for row in root.store.list_instances()]}

    @app.get("/ui/status", include_in_schema=False)
    def ui_status():
        from safi.llm import LLMClient

        llm = LLMClient()
        return {
            "llm_mode": "endpoint" if llm.configured else "extractive",
            "llm_model": llm.model if llm.configured else None,
            "endpoint_configured": llm.configured,
            "service_version": config.SERVICE_VERSION,
            "instances": len(root.store.list_instances()),
        }

    return app
