import json
import re
from pathlib import Path

import yaml

from safi import config, gitinfo
from safi.chat import assemble_context, generate_answer
from safi.gitinfo import GitError
from safi.llm import LLMClient
from safi.models import InstantiateRequest
from safi.rbac import (
    INGEST_CATEGORIES,
    STANDARD_ROLES,
    VERIFICATION_STATUSES,
    default_roles_for_category,
    resolve_roles,
)
from safi.storage import Store, new_id, utcnow
from safi.template import apply_overrides, field_description, load_templates, validate_manifest

HTTP_METHODS = ("get", "post", "put", "delete", "patch")
INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
SOW_MAX_CHARS = 20000


class ServiceError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def _resolve_ref(spec, ref):
    node = spec
    for part in ref.lstrip("#/").split("/"):
        node = node.get(part, {})
    return node


def _example_from_schema(spec, schema, depth=0):
    if not isinstance(schema, dict) or depth > 5:
        return None
    if "example" in schema:
        return schema["example"]
    if "$ref" in schema:
        return _example_from_schema(spec, _resolve_ref(spec, schema["$ref"]), depth + 1)
    kind = schema.get("type")
    if kind == "object" or schema.get("properties"):
        props = schema.get("properties") or {}
        return {name: _example_from_schema(spec, sub, depth + 1) for name, sub in props.items()}
    if kind == "array":
        return [_example_from_schema(spec, schema.get("items") or {}, depth + 1)]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if kind == "string":
        fmt = schema.get("format")
        if fmt == "date":
            return "2026-10-12"
        if fmt == "date-time":
            return "2026-10-12T15:00:00Z"
        return schema.get("default") or "string"
    if kind in ("integer", "number"):
        return schema.get("default", 1)
    if kind == "boolean":
        return True
    return None


def summarize_openapi(spec, service_name, sha, out_of_scope=None):
    """Derive role-split OpenAPI context: user Help summary + developer detail."""
    out_of_scope = out_of_scope or []
    paths = spec.get("paths") or {}
    user_lines = [
        f"Available API endpoints for {service_name} (derived from openapi.yaml, "
        f"authoritative Service contract, observed at SHA {sha}). Only documented "
        f"endpoints are supported; undocumented endpoints must not be used."
    ]
    dev_lines = [
        f"OpenAPI contract detail for {service_name} (authoritative, observed at SHA {sha})."
    ]
    examples = []
    for path, ops in paths.items():
        for method, op in ops.items():
            if method not in HTTP_METHODS or not isinstance(op, dict):
                continue
            opid = op.get("operationId") or ""
            summary = op.get("summary") or ""
            params = [
                f"{p.get('name')}({p.get('in')}{', required' if p.get('required') else ''})"
                for p in op.get("parameters") or []
            ]
            user_lines.append(
                f"{method.upper()} {path} — {summary or opid} (operationId: {opid})"
                + (f" parameters: {', '.join(params)}" if params else "")
            )
            responses = ", ".join(sorted((op.get("responses") or {}).keys()))
            required_headers = [
                p.get("name") for p in op.get("parameters") or []
                if p.get("in") == "header" and p.get("required")
            ]
            dev_lines.append(
                f"{method.upper()} {path} operationId={opid} responses=[{responses}]"
                + (f" required headers={required_headers}" if required_headers else "")
            )
            body = (op.get("requestBody") or {}).get("content") or {}
            for ct, media in body.items():
                if "json" not in ct:
                    continue
                example = media.get("example")
                if example is None:
                    ex_list = media.get("examples") or {}
                    if ex_list:
                        first = next(iter(ex_list.values()))
                        example = (first or {}).get("value") if isinstance(first, dict) else None
                if example is None:
                    example = _example_from_schema(spec, media.get("schema") or {})
                if example is not None:
                    examples.append((opid, method, path, example))
    if examples:
        user_lines.append("Valid example request(s) straight from the contract:")
        for opid, method, path, example in examples:
            user_lines.append(
                f"Example for {opid}:\n{method.upper()} {path}\n"
                + json.dumps(example, indent=2)
            )
    if out_of_scope:
        user_lines.append(
            "Known user-visible limitations / out of scope: "
            + "; ".join(str(x) for x in out_of_scope)
        )
    schemas = list(((spec.get("components") or {}).get("schemas") or {}).keys())
    if schemas:
        dev_lines.append(f"Component schemas: {', '.join(schemas)}")
    user_lines.append(
        "Usage rule: ask through this Chat for help; never rely on undocumented endpoints."
    )
    return "\n".join(user_lines), "\n".join(dev_lines)


class RootServiceExpert:
    def __init__(self, db_path=None, root_dir=None, templates_dir=None, llm=None):
        self.root_dir = Path(root_dir or config.ROOT_DIR)
        self.templates_dir = Path(templates_dir or config.TEMPLATES_DIR)
        self.db_path = Path(db_path or config.DEFAULT_DB_PATH)
        self.store = Store(self.db_path)
        self.llm = llm or LLMClient()
        self.templates = load_templates(self.templates_dir)
        for tid, template in self.templates.items():
            self.store.upsert_template(
                tid, template.get("version", ""), template.get("_source_path", ""), template
            )
        self._seed_root_knowledge()

    # ------------------------------------------------------------------
    def live_git(self, manifest):
        repo = ((manifest.get("git") or {}).get("repo")) or ""
        path = self.resolve_path(repo)
        try:
            return gitinfo.git_state(path)
        except (GitError, OSError):
            return None

    def resolve_path(self, value):
        if not value:
            return Path(value)
        p = Path(value)
        if p.is_absolute():
            return p
        return (self.root_dir / p).resolve()

    def resolve_material_path(self, value, repo_path):
        """Resolve SOW/openapi/test paths: absolute, relative to repo, or
        relative to the Service 013 root."""
        if not value:
            return None
        p = Path(value)
        if p.is_absolute():
            return p if p.exists() else None
        for base in (repo_path, self.root_dir):
            candidate = (base / p)
            if candidate.exists():
                return candidate
        return None

    # ------------------------------------------------------------------
    def _seed_root_knowledge(self):
        """Root knowledge: reusable Safi-wide rules + the loaded templates."""
        items = []
        root_repo = root_branch = root_sha = None
        try:
            state = gitinfo.git_state(self.root_dir)
            root_repo, root_branch, root_sha = state["repo"], state["branch"], state["sha"]
        except (GitError, OSError):
            pass

        kf = Path(config.ROOT_KNOWLEDGE_FILE)
        if kf.exists() and kf != self.root_dir / "nonexistent":
            try:
                data = yaml.safe_load(kf.read_text(encoding="utf-8")) or {}
                for entry in data.get("items", []):
                    items.append({
                        "knowledge_id": entry.get("id") or new_id("kn"),
                        "service_expert_id": config.ROOT_EXPERT_ID,
                        "repo": root_repo,
                        "branch": root_branch,
                        "observed_at_sha": root_sha,
                        "category": entry.get("category", "root rule"),
                        "content": entry.get("content", ""),
                        "source": entry.get("source", str(kf)),
                        "verification_status": entry.get("verification_status", "AUTHORITATIVE"),
                        "allowed_roles": list(entry.get("allowed_roles") or STANDARD_ROLES),
                    })
            except Exception:
                pass

        for tid, template in self.templates.items():
            items.append({
                "knowledge_id": f"root-template-{tid}",
                "service_expert_id": config.ROOT_EXPERT_ID,
                "repo": root_repo,
                "branch": root_branch,
                "observed_at_sha": root_sha,
                "category": "root rule",
                "content": (
                    f"Root Service Expert Template '{tid}' v{template.get('version')} "
                    f"(machine-readable, {self.templates_dir / (tid + '.yaml')}). "
                    f"Required fields: "
                    + ", ".join(f["key"] for f in template["sections"]["required"])
                    + ". Conditional fields: "
                    + ", ".join(f["key"] for f in template["sections"]["conditional"])
                    + ". Growing fields: "
                    + ", ".join(f["key"] for f in template["sections"]["growing"])
                    + ". Standard role vocabulary: " + ", ".join(STANDARD_ROLES)
                    + "."
                ),
                "source": template.get("_source_path", ""),
                "verification_status": "AUTHORITATIVE",
                "allowed_roles": list(STANDARD_ROLES),
            })

        for item in items:
            if item["knowledge_id"] and self.store.get_knowledge(item["knowledge_id"]):
                continue
            item.setdefault("created_at", utcnow())
            self.store.insert_knowledge(item)

    # ------------------------------------------------------------------
    def instantiate(self, payload):
        req = InstantiateRequest(**payload)
        template = self.templates.get(req.template)
        if template is None:
            raise ServiceError(400, {
                "error": "unknown_template",
                "template": req.template,
                "supported": sorted(self.templates.keys()),
            })

        manifest = apply_overrides(req.manifest or {}, req.model_dump())
        report = validate_manifest(template, manifest)
        if report["missing"] or report["invalid"]:
            missing_messages = [
                f"{key} — {field_description(template, key)}" for key in report["missing"]
            ]
            raise ServiceError(422, {
                "error": "manifest_failed_template_validation",
                "template": req.template,
                "missing": report["missing"],
                "missing_messages": missing_messages,
                "invalid": report["invalid"],
            })

        instance_id = req.instance_id or f"{manifest['service']['id']}-expert"
        if not INSTANCE_ID_RE.match(instance_id):
            raise ServiceError(422, {
                "error": "invalid_instance_id",
                "instance_id": instance_id,
                "pattern": INSTANCE_ID_RE.pattern,
            })
        if self.store.instance_exists(instance_id):
            raise ServiceError(409, {
                "error": "instance_already_exists",
                "instance_id": instance_id,
            })

        manifest_sha = (manifest.get("git") or {}).get("current_sha") or ""
        repo_path = self.resolve_path((manifest.get("git") or {}).get("repo") or "")
        try:
            git = gitinfo.git_state(repo_path)
        except GitError as exc:
            raise ServiceError(422, {
                "error": "invalid_repo",
                "repo": str(manifest.get("git", {}).get("repo")),
                "message": str(exc),
            })

        items = self._materialize(instance_id, manifest, git)

        self.store.create_instance(instance_id, req.template, manifest, git)
        for item in items:
            self.store.insert_knowledge(item)

        merged_git = self._merged_git(manifest, git, manifest_sha)
        return {
            "instance_id": instance_id,
            "template": req.template,
            "service": manifest.get("service") or {},
            "git": merged_git,
            "manifest": manifest,
            "seeded_knowledge": len(items),
            "created_at": utcnow(),
        }

    def _merged_git(self, manifest, git, manifest_sha):
        return {
            "repo": git.get("repo", ""),
            "branch": git.get("branch") or (manifest.get("git") or {}).get("branch") or "",
            "sha": git.get("sha", ""),
            "manifest_sha": manifest_sha or None,
            "sha_matches_manifest": (manifest_sha == git.get("sha")) if manifest_sha else None,
            "dirty": bool(git.get("dirty")),
            "commits": git.get("commits", []),
            "files": git.get("files", []),
        }

    # ------------------------------------------------------------------
    def _materialize(self, instance_id, manifest, git):
        """Build the initial knowledge set from authoritative material:
        SOW, openapi.yaml, acceptance tests and repository training."""
        items = []
        now = utcnow()
        repo_path = Path(git["repo"])
        sha, branch = git["sha"], git["branch"]
        service = manifest.get("service") or {}
        source_root = str(self.root_dir)

        def add(category, content, source, status, roles):
            if not content:
                return
            items.append({
                "knowledge_id": new_id("kn"),
                "service_expert_id": instance_id,
                "repo": str(repo_path),
                "branch": branch,
                "observed_at_sha": sha,
                "category": category,
                "content": content[:SOW_MAX_CHARS] if category == "SOW" else content,
                "source": source,
                "verification_status": status,
                "allowed_roles": roles,
                "created_at": now,
            })

        # 1. SOW
        sow = manifest.get("sow") or {}
        sow_loc = sow.get("location") or ""
        sow_path = self.resolve_material_path(sow_loc, repo_path)
        if sow_path is None:
            raise ServiceError(400, {
                "error": "material_not_readable",
                "kind": "sow",
                "location": sow_loc,
                "message": "SOW location could not be resolved relative to the repo or the Service 013 root",
            })
        sow_text = sow_path.read_text(encoding="utf-8", errors="replace")
        add(
            "SOW",
            f"SOW {sow.get('id', '')} (source file {sow_loc}):\n{sow_text}",
            str(sow_path),
            "AUTHORITATIVE",
            default_roles_for_category("SOW"),
        )

        # 2. openapi.yaml
        oa_loc = manifest.get("api", {}).get("openapi") or ""
        oa_path = self.resolve_material_path(oa_loc, repo_path)
        if oa_path is None:
            raise ServiceError(400, {
                "error": "material_not_readable",
                "kind": "openapi",
                "location": oa_loc,
                "message": "openapi.yaml location could not be resolved relative to the repo or the Service 013 root",
            })
        try:
            spec = yaml.safe_load(oa_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ServiceError(400, {
                "error": "openapi_unparseable", "location": oa_loc, "message": str(exc)})
        if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
            raise ServiceError(400, {
                "error": "openapi_invalid", "location": oa_loc,
                "message": "openapi.yaml must be a mapping with a 'paths' mapping"})
        user_summary, dev_summary = summarize_openapi(
            spec, service.get("name", "service"), sha, manifest.get("out_of_scope")
        )
        add("OpenAPI", user_summary, str(oa_path), "AUTHORITATIVE",
            default_roles_for_category("OpenAPI"))
        add("OpenAPI", dev_summary, str(oa_path), "AUTHORITATIVE",
            ["Developer", "Tester", "RCA", "Fixer", "Dispatcher"])

        # 3. acceptance tests
        tests = manifest.get("acceptance_tests") or []
        add(
            "acceptance test result",
            "Acceptance/contract test references (authoritative Service contract):\n"
            + "\n".join(f"- {t}" for t in tests),
            "; ".join(str(t) for t in tests),
            "AUTHORITATIVE",
            default_roles_for_category("acceptance test result"),
        )

        # 4. repository training
        impl = manifest.get("api", {}).get("implementation") or ""
        operations = manifest.get("api", {}).get("operations") or []
        commits = "\n".join(
            f"- {c['sha'][:12]} {c['subject']}" for c in git.get("commits", [])
        )
        files = "\n".join(f"- {f}" for f in git.get("files", []))
        training = (
            f"Repository training for {service.get('name', 'service')} "
            f"(learned from Git at SHA {sha}, branch {branch}):\n"
            f"Implementation entrypoint: {impl}\n"
            f"Declared operations: {', '.join(map(str, operations))}\n"
            f"Recent commits:\n{commits}\n"
            f"Tracked files:\n{files}"
        )
        add("repo training", training, f"git:{repo_path}@{sha}", "VERIFIED",
            default_roles_for_category("repo training"))
        return items

    # ------------------------------------------------------------------
    def ingest(self, expert_id, payload, user_id, requested_roles):
        instance = self._instance_or_404(expert_id)
        effective = self._authorize(instance, user_id, requested_roles, require_identity=True)

        category = payload.get("category")
        if category not in INGEST_CATEGORIES:
            raise ServiceError(422, {
                "error": "unsupported_category",
                "category": category,
                "supported": list(INGEST_CATEGORIES),
            })
        status = payload.get("verification_status")
        if status not in VERIFICATION_STATUSES:
            raise ServiceError(422, {
                "error": "unsupported_verification_status",
                "verification_status": status,
                "supported": list(VERIFICATION_STATUSES),
            })
        content = (payload.get("content") or "").strip()
        source = (payload.get("source") or "").strip()
        if not content or not source:
            raise ServiceError(422, {
                "error": "content_and_source_required",
                "message": "ingest requires non-empty content and source (provenance)",
            })

        roles = payload.get("allowed_roles")
        if roles is None:
            roles = default_roles_for_category(category)
        bad = [r for r in roles if r not in STANDARD_ROLES]
        if bad or not roles:
            raise ServiceError(422, {
                "error": "unsupported_role",
                "invalid_roles": bad or roles,
                "standard_roles": list(STANDARD_ROLES),
                "message": "Root Expert does not create person-specific roles",
            })

        manifest = instance["manifest"]
        repo = payload.get("repo") or (manifest.get("git") or {}).get("repo") or ""
        branch = payload.get("branch") or (manifest.get("git") or {}).get("branch") or ""
        observed = payload.get("observed_at_sha")
        if not observed:
            live = self.live_git(manifest)
            observed = (live or {}).get("sha") or (manifest.get("git") or {}).get("current_sha")
        if not repo or not branch or not observed:
            raise ServiceError(422, {
                "error": "provenance_required",
                "message": "ingest requires repo, branch and observed_at_sha "
                           "(explicitly or resolvable from the bound repository)",
            })

        item = {
            "knowledge_id": new_id("kn"),
            "service_expert_id": expert_id,
            "repo": repo,
            "branch": branch,
            "observed_at_sha": observed,
            "category": category,
            "content": content,
            "source": source,
            "verification_status": status,
            "allowed_roles": list(roles),
            "created_at": utcnow(),
        }
        self.store.insert_knowledge(item)
        return item

    # ------------------------------------------------------------------
    def chat(self, expert_id, message, user_id, requested_roles):
        instance = self._instance_or_404(expert_id)
        effective = self._authorize(instance, user_id, requested_roles, require_identity=True)

        session_id = new_id("sess")
        ctx = assemble_context(self, instance, effective, message)
        answer, mode = generate_answer(
            self, message, ctx, instance, effective, user_id, session_id
        )
        created = utcnow()
        self.store.insert_session({
            "session_id": session_id,
            "service_expert_id": expert_id,
            "user_id": user_id,
            "roles": effective,
            "question": message,
            "answer": answer,
            "context_knowledge_ids": [i["knowledge_id"] for i in ctx["items"]],
            "llm_mode": mode,
            "created_at": created,
        })
        return {
            "session_id": session_id,
            "instance_id": expert_id,
            "question": message,
            "answer": answer,
            "roles": effective,
            "permitted_categories": ctx["permitted_categories"],
            "context_items": [
                {
                    "knowledge_id": i["knowledge_id"],
                    "category": i["category"],
                    "verification_status": i["verification_status"],
                    "observed_at_sha": i.get("observed_at_sha"),
                    "sha_status": i.get("sha_status"),
                }
                for i in ctx["items"]
            ],
            "llm_mode": mode,
            "endpoint_configured": self.llm.configured,
            "created_at": created,
        }

    # ------------------------------------------------------------------
    def get(self, expert_id, requested_roles):
        instance = self._instance_or_404(expert_id)
        manifest = instance["manifest"]
        declared = (manifest.get("expert") or {}).get("roles") or []
        effective = []
        if requested_roles:
            effective, rejected = resolve_roles(requested_roles, declared)
            if not effective:
                raise ServiceError(403, {
                    "error": "forbidden",
                    "message": "requested roles are not permitted for this Service Expert",
                    "requested_roles": requested_roles,
                    "declared_roles": declared,
                    "rejected_roles": rejected,
                })
        knowledge = []
        if effective:
            git = instance.get("git_state") or {}
            current = git.get("sha") or ""
            for row in self.store.list_knowledge([expert_id, config.ROOT_EXPERT_ID],
                                                 roles=effective):
                observed = row.get("observed_at_sha") or ""
                if current and observed:
                    row["sha_status"] = "current" if observed == current else "historical"
                else:
                    row["sha_status"] = "unknown"
                knowledge.append(row)
        return {
            "instance_id": instance["id"],
            "template": instance["template_id"],
            "service": manifest.get("service") or {},
            "manifest": manifest,
            "git": self._merged_git(
                manifest, instance.get("git_state") or {},
                (manifest.get("git") or {}).get("current_sha") or "",
            ),
            "roles": declared,
            "knowledge_counts": self.store.knowledge_count(expert_id),
            "knowledge": knowledge,
            "created_at": instance["created_at"],
        }

    def health(self):
        try:
            self.store._query("SELECT 1 AS ok")
            db = "ok"
        except Exception:
            db = "error"
        return {
            "status": "ok" if db == "ok" else "degraded",
            "service": config.SERVICE_NAME,
            "version": config.SERVICE_VERSION,
            "llm_configured": self.llm.configured,
            "db": db,
        }

    # ------------------------------------------------------------------
    def _instance_or_404(self, expert_id):
        instance = self.store.get_instance(expert_id)
        if instance is None:
            raise ServiceError(404, {
                "error": "not_found",
                "service_expert_id": expert_id,
            })
        return instance

    def _authorize(self, instance, user_id, requested_roles, require_identity=True):
        if require_identity and not user_id:
            raise ServiceError(401, {
                "error": "unauthenticated",
                "message": "X-User-Id header is required",
            })
        declared = (instance["manifest"].get("expert") or {}).get("roles") or []
        effective, rejected = resolve_roles(requested_roles, declared)
        if not effective:
            raise ServiceError(403, {
                "error": "forbidden",
                "message": "no permitted roles: pass X-Roles with at least one role "
                           "declared by this Service Expert",
                "requested_roles": requested_roles,
                "declared_roles": declared,
                "rejected_roles": rejected,
            })
        return effective
