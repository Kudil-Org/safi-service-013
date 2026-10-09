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

    @app.get("/app", include_in_schema=False)
    def ui_app():
        return HTMLResponse((WEB_DIR / "app.html").read_text(encoding="utf-8"))

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

    @app.get("/ui/overview", include_in_schema=False)
    def ui_overview():
        from safi.llm import LLMClient

        llm = LLMClient()
        rows = root.store.list_instances()

        def _total(expert_id):
            return sum((root.store.knowledge_count(expert_id) or {}).values())

        total_knowledge = sum(_total(r["id"]) for r in rows)
        return {
            "service_version": config.SERVICE_VERSION,
            "llm_mode": "endpoint" if llm.configured else "extractive",
            "llm_model": llm.model if llm.configured else None,
            "endpoint_configured": llm.configured,
            "templates": len(root.templates),
            "instances": len(rows),
            "knowledge_total": total_knowledge,
        }

    @app.get("/ui/templates", include_in_schema=False)
    def ui_templates():
        out = []
        for template_id, template in root.templates.items():
            sections = template.get("sections") or {}
            out.append({
                "template_id": template_id,
                "version": template.get("version", ""),
                "source_path": template.get("_source_path", ""),
                "name": template.get("name", template_id),
                "sections": {
                    "required": sections.get("required", []),
                    "conditional": sections.get("conditional", []),
                    "growing": sections.get("growing", []),
                },
            })
        return {"templates": out}

    @app.get("/ui/manifest/demo", include_in_schema=False)
    def ui_manifest_demo():
        from safi.demo import load_demo_manifest

        return {"manifest": load_demo_manifest()}

    @app.get("/ui/experts", include_in_schema=False)
    def ui_experts():
        out = []
        def _total(expert_id):
            return sum((root.store.knowledge_count(expert_id) or {}).values())
        for row in root.store.list_instances():
            instance = root.store.get_instance(row["id"]) or {}
            manifest = instance.get("manifest") or {}
            git_state = instance.get("git_state") or {}
            manifest_sha = (manifest.get("git") or {}).get("current_sha") or ""
            live_sha = git_state.get("sha") or ""
            out.append({
                "instance_id": row["id"],
                "template": row["template_id"],
                "created_at": row["created_at"],
                "service_name": (manifest.get("service") or {}).get("name") or row["id"],
                "service_purpose": (manifest.get("service") or {}).get("purpose") or "",
                "git": {
                    "branch": git_state.get("branch") or "",
                    "sha": live_sha,
                    "manifest_sha": manifest_sha,
                    "sha_matches_manifest": bool(live_sha) and live_sha == manifest_sha,
                    "dirty": git_state.get("dirty", False),
                },
                "knowledge_count": _total(row["id"]),
            })
        return {"experts": out}

    return app
