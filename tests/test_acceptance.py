import copy
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from safi.app import create_app  # noqa: E402
from safi.demo import ensure_demo_repos, load_demo_manifest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def demo_repos():
    ensure_demo_repos(ROOT)
    return ROOT


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "service013.db"


@pytest.fixture()
def app(db_path):
    return create_app(db_path=db_path, root_dir=ROOT)


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def manifest(demo_repos):
    return load_demo_manifest()


def H(user, roles):
    return {"X-User-Id": user, "X-Roles": roles}


@pytest.fixture()
def gw(client, manifest):
    m = copy.deepcopy(manifest)
    iid = "api-gateway-expert-" + uuid.uuid4().hex[:6]
    resp = client.post(
        "/service-experts",
        json={"template": "openapi-service", "manifest": m, "instance_id": iid},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    data["_headers"] = {}
    return data


def chat(client, iid, message, user="u1", roles="User"):
    return client.post(
        f"/service-experts/{iid}/chat",
        headers=H(user, roles),
        json={"message": message},
    )


def _git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout.strip()


# ---------------------------------------------------------------------------
def test_01_root_template_exists():
    """TEST 1 — OpenAPI Service Template is machine-readable with
    identifiable required/conditional/growing sections."""
    path = ROOT / ".safi" / "templates" / "openapi-service.yaml"
    assert path.exists(), "template file missing"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["template_id"] == "openapi-service"
    sections = data["sections"]
    for name in ("required", "conditional", "growing"):
        assert name in sections and isinstance(sections[name], list), name
    required_keys = [f["key"] for f in sections["required"]]
    for key in ("service.id", "service.name", "sow.id", "git.repo", "git.branch",
                "git.current_sha", "api.openapi", "api.implementation",
                "api.operations", "invariants", "expert.roles",
                "acceptance_tests", "out_of_scope"):
        assert key in required_keys, f"required field missing from template: {key}"
    for field in sections["required"]:
        assert "key" in field and "type" in field and "description" in field


def test_02_missing_required_fields_rejected(client, manifest):
    """TEST 2 — instantiate with missing repo/openapi fields is rejected."""
    m = copy.deepcopy(manifest)
    del m["git"]["repo"]
    del m["api"]["openapi"]
    iid = "incomplete-" + uuid.uuid4().hex[:6]
    resp = client.post(
        "/service-experts",
        json={"template": "openapi-service", "manifest": m, "instance_id": iid},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "manifest_failed_template_validation"
    assert "git.repo" in detail["missing"]
    assert "api.openapi" in detail["missing"]
    assert any("Git repository" in msg for msg in detail["missing_messages"])
    assert client.get(f"/service-experts/{iid}").status_code == 404


def test_03_api_gateway_instance(client, gw):
    """TEST 3 — API Gateway instance holds SOW/OpenAPI/repo/branch/SHA/tests."""
    iid = gw["instance_id"]
    resp = client.get(f"/service-experts/{iid}", headers=H("dev", "Developer"))
    assert resp.status_code == 200
    data = resp.json()
    m = data["manifest"]
    assert m["service"]["name"] == "API Gateway"
    assert m["sow"]["id"] == "SOW-013"
    assert m["sow"]["location"].endswith("SOW.md")
    assert m["api"]["openapi"] == "openapi.yaml"
    assert m["git"]["repo"].endswith("api-gateway")
    assert data["git"]["branch"] == "main"
    assert re.fullmatch(r"[0-9a-f]{40}", data["git"]["sha"])
    assert m["acceptance_tests"], "acceptance test references missing"
    assert m["expert"]["template"] == "openapi-service"
    counts = data["knowledge_counts"]
    for cat in ("SOW", "OpenAPI", "acceptance test result", "repo training"):
        assert counts.get(cat, 0) >= 1, f"missing seeded category: {cat}"


def test_04_user_role_chat(client, gw):
    """TEST 4 / SOW §20 — User Help through the same Chat, OpenAPI-derived."""
    iid = gw["instance_id"]

    r1 = chat(client, iid, "What endpoints are available?", roles="User")
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    ans1 = d1["answer"].lower()
    assert d1["roles"] == ["User"]
    assert d1["instance_id"] == iid
    assert "/reservations" in ans1
    assert "createreservation" in ans1

    r2 = chat(client, iid, "How do I call the createReservation API?", roles="User")
    assert r2.status_code == 200
    ans2 = r2.json()["answer"].lower()
    assert "post /reservations" in ans2

    r3 = chat(client, iid, "Show me a valid example request.", roles="User")
    assert r3.status_code == 200
    ans3 = r3.json()["answer"]
    assert "RES-1001" in ans3
    assert "example" in ans3.lower()

    for ans in (d1["answer"], r2.json()["answer"], r3.json()["answer"]):
        low = ans.lower()
        assert "src/gateway" not in low, "developer-only source context leaked to User"
        assert "gateway.py" not in low, "developer-only source context leaked to User"
        assert "test_contract" not in low, "test internals leaked to User"
        assert "repo training" not in low, "developer-only category leaked to User"


def test_05_developer_role_chat(client, gw):
    """TEST 5 / SOW §21 — Developer technical Chat through the same expert."""
    iid = gw["instance_id"]
    resp = chat(
        client, iid,
        "Where is createReservation implemented and what tests cover it? "
        "What exact SHA are you describing?",
        roles="Developer",
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ans = data["answer"]
    assert "gateway.py" in ans, "implementation location missing"
    assert "createReservation" in ans
    assert "test_contract" in ans, "covering tests missing"
    sha = re.search(r"\b[0-9a-f]{40}\b", ans)
    assert sha, "SHA not identified"
    assert sha.group(0) == gw["git"]["sha"], "wrong SHA reported"
    assert data["roles"] == ["Developer"]


def test_06_same_expert_for_all_roles(client, gw):
    """TEST 6 — one Service Expert instance serves User and Developer."""
    iid = gw["instance_id"]
    r_user = chat(client, iid, "What endpoints are available?", roles="User")
    r_dev = chat(
        client, iid, "Where is createReservation implemented?", roles="Developer"
    )
    assert r_user.status_code == 200 and r_dev.status_code == 200
    assert r_user.json()["instance_id"] == r_dev.json()["instance_id"] == iid
    assert r_user.json()["session_id"] != r_dev.json()["session_id"]


def test_07_provenance_stored(client, gw):
    """TEST 7 — ingest retains source, verification status, branch and SHA."""
    iid = gw["instance_id"]
    resp = client.post(
        f"/service-experts/{iid}/ingest",
        headers=H("rca1", "RCA"),
        json={
            "category": "RCA finding",
            "content": "Reservation cancel raced with duplicate create under load.",
            "source": "RCA-2026-0042",
            "verification_status": "VERIFIED",
        },
    )
    assert resp.status_code == 201, resp.text
    item = resp.json()
    assert item["source"] == "RCA-2026-0042"
    assert item["verification_status"] == "VERIFIED"
    assert item["branch"] == "main"
    assert re.fullmatch(r"[0-9a-f]{40}", item["observed_at_sha"] or "")
    assert item["repo"].endswith("api-gateway")
    assert set(item["allowed_roles"]) <= {"User", "Developer", "Tester", "RCA",
                                          "Dispatcher", "Fixer"}

    got = client.get(f"/service-experts/{iid}", headers=H("dev", "Developer")).json()
    stored = [k for k in got["knowledge"] if k["knowledge_id"] == item["knowledge_id"]]
    assert stored, "ingested knowledge not retrievable"
    assert stored[0]["source"] == "RCA-2026-0042"
    assert stored[0]["observed_at_sha"]


def test_08_fresh_learning_used_in_new_session(client, gw):
    """TEST 8 / SOW §22 — a newly verified fact is learned and used in a
    fresh micro-session without touching prompts or code."""
    iid = gw["instance_id"]
    question = "Which special debug header can I send to get a trace id back?"

    pre = chat(client, iid, question, roles="User")
    assert pre.status_code == 200
    assert "X-Debug-Trace" not in pre.json()["answer"]

    ingest = client.post(
        f"/service-experts/{iid}/ingest",
        headers=H("qa1", "Tester"),
        json={
            "category": "fix result",
            "content": (
                "Verified in test run TR-8891: sending header X-Debug-Trace: strict "
                "with GET /reservations makes the gateway return response header "
                "X-Trace-Id; without it no trace id is returned."
            ),
            "source": "test run TR-8891",
            "verification_status": "VERIFIED",
            "allowed_roles": ["User", "Developer", "Tester", "RCA", "Fixer"],
        },
    )
    assert ingest.status_code == 201, ingest.text

    post = chat(client, iid, question, roles="User")
    assert post.status_code == 200
    assert "X-Debug-Trace" in post.json()["answer"], "fresh fact not retrieved"
    assert post.json()["session_id"] != pre.json()["session_id"]


def test_09_knowledge_isolation(client, gw, demo_repos):
    """TEST 9 / SOW §23 — namespaces are isolated between Service Experts."""
    from safi.gitinfo import resolve_sha

    iid_gw = gw["instance_id"]
    marker = "SECRETGWONLY-" + uuid.uuid4().hex[:8]

    ingest = client.post(
        f"/service-experts/{iid_gw}/ingest",
        headers=H("dev", "Developer"),
        json={
            "category": "human correction",
            "content": f"Internal note unique to the gateway expert: {marker}",
            "source": "developer correction during Service 013 build",
            "verification_status": "AUTHORITATIVE",
            "allowed_roles": ["Developer"],
        },
    )
    assert ingest.status_code == 201, ingest.text

    repo2 = ROOT / "demo" / "second-service"
    iid2 = "inventory-expert-" + uuid.uuid4().hex[:6]
    m2 = {
        "service": {"id": "inventory", "name": "Inventory Service",
                    "purpose": "Stock lookups"},
        "sow": {"id": "SOW-INV-002", "location": "demo/second-service/SOW.md"},
        "git": {"repo": "demo/second-service", "branch": "main",
                "current_sha": resolve_sha(repo2)},
        "api": {"openapi": "openapi.yaml", "implementation": "src/inventory.py",
                "operations": ["listInventory", "healthCheck"]},
        "invariants": ["Responses conform to openapi.yaml"],
        "expert": {"template": "openapi-service",
                   "roles": ["User", "Developer", "Tester", "RCA", "Dispatcher", "Fixer"]},
        "acceptance_tests": ["demo/second-service/tests/test_inventory.py"],
        "out_of_scope": ["Anything not in openapi.yaml"],
    }
    resp = client.post(
        "/service-experts",
        json={"template": "openapi-service", "manifest": m2, "instance_id": iid2},
    )
    assert resp.status_code == 201, resp.text

    leaked = chat(client, iid2, f"Tell me everything about {marker}", roles="Developer")
    assert leaked.status_code == 200
    assert marker not in leaked.json()["answer"], "knowledge leaked across experts"

    got2 = client.get(f"/service-experts/{iid2}", headers=H("dev", "Developer")).json()
    assert all(marker not in (k.get("content") or "") for k in got2["knowledge"])

    own = chat(client, iid_gw, f"What is {marker}?", roles="Developer")
    assert marker in own.json()["answer"], "own expert cannot use its knowledge"


def test_10_sha_awareness(client, tmp_path):
    """TEST 10 — a fact learned at SHA-A is not asserted as current at SHA-B."""
    repo = tmp_path / "sha-demo"
    repo.mkdir()
    (repo / "SOW.md").write_text("# SOW Auth\nScope: token check endpoint.\n", encoding="utf-8")
    (repo / "openapi.yaml").write_text(
        "openapi: 3.0.3\ninfo: {title: Auth, version: '1.0'}\npaths:\n"
        "  /check:\n    get:\n      operationId: checkAuth\n"
        "      responses:\n        '200': {description: ok}\n",
        encoding="utf-8",
    )
    (repo / "auth.py").write_text("def check():\n    return True\n", encoding="utf-8")

    def commit_all(msg):
        _git(["add", "-A"], repo)
        _git(["-c", "user.email=t@t", "-c", "user.name=T", "commit", "-m", msg], repo)

    _git(["init", "-b", "main"], repo)
    commit_all("initial auth")
    sha_a = _git(["rev-parse", "HEAD"], repo)

    iid = "sha-expert-" + uuid.uuid4().hex[:6]
    m = {
        "service": {"id": "auth", "name": "Auth Service", "purpose": "Token checks"},
        "sow": {"id": "SOW-AUTH", "location": "SOW.md"},
        "git": {"repo": str(repo), "branch": "main", "current_sha": sha_a},
        "api": {"openapi": "openapi.yaml", "implementation": "auth.py",
                "operations": ["checkAuth"]},
        "invariants": ["Responses conform to openapi.yaml"],
        "expert": {"template": "openapi-service",
                   "roles": ["User", "Developer", "Tester", "RCA", "Dispatcher", "Fixer"]},
        "acceptance_tests": ["tests/test_auth.py"],
        "out_of_scope": ["Refresh tokens"],
    }
    resp = client.post(
        "/service-experts",
        json={"template": "openapi-service", "manifest": m, "instance_id": iid},
    )
    assert resp.status_code == 201, resp.text

    ingest = client.post(
        f"/service-experts/{iid}/ingest",
        headers=H("dev", "Developer"),
        json={
            "category": "repo training",
            "content": "check() rejects expired tokens with HTTP 401.",
            "source": "RCA-2026-0909",
            "verification_status": "VERIFIED",
            "observed_at_sha": sha_a,
            "allowed_roles": ["Developer", "RCA"],
        },
    )
    assert ingest.status_code == 201, ingest.text

    (repo / "auth.py").write_text(
        "def check(token=None):\n    if token and token.expired:\n"
        "        raise PermissionError('expired')\n    return True\n",
        encoding="utf-8",
    )
    commit_all("handle expired tokens")
    sha_b = _git(["rev-parse", "HEAD"], repo)
    assert sha_b != sha_a

    resp = chat(client, iid, "Does check() handle expired tokens and is that fact current?",
                roles="Developer")
    assert resp.status_code == 200
    ans = resp.json()["answer"]
    assert sha_a in ans, "observed SHA missing"
    assert sha_b in ans, "current Git SHA missing"
    assert "historical" in ans, "stale fact not marked historical"


def test_11_root_openapi_contract(client, manifest):
    """TEST 11 — Service 013's own openapi.yaml validates and the running
    implementation conforms to every mandatory operation."""
    spec = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    try:
        from openapi_spec_validator import validate as validate_spec
    except ImportError:
        from openapi_spec_validator import validate_v3 as validate_spec
    validate_spec(spec)

    mandatory = {
        ("post", "/service-experts"),
        ("post", "/service-experts/{id}/ingest"),
        ("post", "/service-experts/{id}/chat"),
        ("get", "/service-experts/{id}"),
        ("get", "/health"),
    }
    declared = {
        (m, p)
        for p, methods in spec["paths"].items()
        for m in methods
        if m in ("get", "post", "put", "delete", "patch")
    }
    assert mandatory <= declared

    served = client.get("/openapi.json").json()
    for (method, path) in declared:
        assert path in served["paths"], f"path not implemented: {path}"
        assert method in served["paths"][path], f"method not implemented: {method} {path}"

    def check_keys(body, schema_name):
        props = set(spec["components"]["schemas"][schema_name]["properties"])
        assert set(body) == props, f"{schema_name}: {set(body)} != {props}"

    # GET /health
    r = client.get("/health")
    assert str(r.status_code) in spec["paths"]["/health"]["get"]["responses"]
    assert r.status_code == 200
    check_keys(r.json(), "HealthResponse")

    # POST /service-experts
    m = copy.deepcopy(manifest)
    iid = "contract-" + uuid.uuid4().hex[:6]
    r = client.post("/service-experts",
                    json={"template": "openapi-service", "manifest": m,
                          "instance_id": iid})
    assert str(r.status_code) in spec["paths"]["/service-experts"]["post"]["responses"]
    assert r.status_code == 201
    check_keys(r.json(), "InstantiateResponse")
    git_props = set(spec["components"]["schemas"]["GitState"]["properties"])
    assert set(r.json()["git"]) == git_props

    # POST /service-experts/{id}/ingest
    r = client.post(f"/service-experts/{iid}/ingest", headers=H("qa", "Tester"),
                    json={"category": "release result",
                          "content": "Release 1.2.0 passed contract tests.",
                          "source": "release pipeline",
                          "verification_status": "VERIFIED"})
    assert str(r.status_code) in spec["paths"]["/service-experts/{id}/ingest"]["post"]["responses"]
    assert r.status_code == 201
    check_keys(r.json(), "KnowledgeItem")

    # POST /service-experts/{id}/chat
    r = chat(client, iid, "What endpoints are available?", roles="Tester")
    assert str(r.status_code) in spec["paths"]["/service-experts/{id}/chat"]["post"]["responses"]
    assert r.status_code == 200
    check_keys(r.json(), "ChatResponse")

    # GET /service-experts/{id} (+declared 404 and 403)
    r = client.get(f"/service-experts/{iid}", headers=H("qa", "Tester"))
    assert str(r.status_code) in spec["paths"]["/service-experts/{id}"]["get"]["responses"]
    assert r.status_code == 200
    check_keys(r.json(), "InstanceResponse")
    r404 = client.get("/service-experts/no-such-id", headers=H("qa", "Tester"))
    assert r404.status_code == 404
    assert "404" in spec["paths"]["/service-experts/{id}"]["get"]["responses"]
    assert set(r404.json()) == {"detail"}
    r403 = client.get(f"/service-experts/{iid}", headers=H("qa", "Nope"))
    assert r403.status_code == 403
    assert "403" in spec["paths"]["/service-experts/{id}"]["get"]["responses"]

    # chat identity enforcement (declared 401)
    r401 = client.post(f"/service-experts/{iid}/chat", headers={"X-Roles": "User"},
                       json={"message": "hello"})
    assert r401.status_code == 401
    assert "401" in spec["paths"]["/service-experts/{id}/chat"]["post"]["responses"]

    # missing-field rejection (declared 422)
    bad = copy.deepcopy(manifest)
    del bad["git"]["branch"]
    r422 = client.post("/service-experts",
                       json={"template": "openapi-service", "manifest": bad,
                             "instance_id": "bad-" + uuid.uuid4().hex[:6]})
    assert r422.status_code == 422
    assert "422" in spec["paths"]["/service-experts"]["post"]["responses"]


def test_12_restart_persistence(db_path, manifest):
    """TEST 12 — templates, instances and verified knowledge survive restart."""
    app1 = create_app(db_path=db_path, root_dir=ROOT)
    c1 = TestClient(app1)
    iid = "persist-" + uuid.uuid4().hex[:6]
    r = c1.post("/service-experts",
                json={"template": "openapi-service",
                      "manifest": copy.deepcopy(manifest), "instance_id": iid})
    assert r.status_code == 201, r.text
    r = c1.post(f"/service-experts/{iid}/ingest", headers=H("dev", "Developer"),
                json={"category": "fix result",
                      "content": "Fixed reservation id trimming before uniqueness check.",
                      "source": "PR-4412", "verification_status": "VERIFIED"})
    assert r.status_code == 201
    del c1, app1

    app2 = create_app(db_path=db_path, root_dir=ROOT)
    c2 = TestClient(app2)
    r = c2.get(f"/service-experts/{iid}", headers=H("dev", "Developer"))
    assert r.status_code == 200, "instance lost after restart"
    data = r.json()
    assert any("PR-4412" in k["source"] for k in data["knowledge"]), \
        "verified knowledge lost after restart"
    root2 = app2.state.root
    assert root2.store.get_template("openapi-service") is not None, \
        "template lost after restart"


# ---------------------------------------------------------------------------
def test_rbac_identity_and_roles_enforced(client, gw):
    iid = gw["instance_id"]
    assert client.post(f"/service-experts/{iid}/chat",
                       json={"message": "hi"}).status_code == 401
    assert client.post(f"/service-experts/{iid}/chat", headers=H("u", "Nope"),
                       json={"message": "hi"}).status_code == 403
    assert client.post(f"/service-experts/{iid}/chat", headers=H("u", ""),
                       json={"message": "hi"}).status_code == 403


def test_ingest_validation(client, gw):
    iid = gw["instance_id"]
    base = {"category": "RCA finding", "content": "x", "source": "y",
            "verification_status": "VERIFIED"}
    r = client.post(f"/service-experts/{iid}/ingest", headers=H("d", "Developer"),
                    json={**base, "category": "made up"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "unsupported_category"
    r = client.post(f"/service-experts/{iid}/ingest", headers=H("d", "Developer"),
                    json={**base, "allowed_roles": ["Aqib"]})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "unsupported_role"
    r = client.post(f"/service-experts/{iid}/ingest", headers=H("d", "Developer"),
                    json={**base, "verification_status": "MAYBE"})
    assert r.status_code == 422


def test_unverified_experience_is_labelled(client, gw):
    iid = gw["instance_id"]
    r = client.post(f"/service-experts/{iid}/ingest", headers=H("u", "User"),
                    json={"category": "Help correction",
                          "content": "Hypothesis: the gateway might accept PUT /reservations someday.",
                          "source": "user suggestion box",
                          "verification_status": "UNVERIFIED"})
    assert r.status_code == 201
    ans = chat(client, iid, "Does the gateway accept PUT /reservations?",
               roles="User").json()["answer"]
    assert "UNVERIFIED" in ans
    assert "does not silently override" in ans or "Unverified" in ans
