"""Instantiate and seed the API Gateway demonstration Service Expert.

Idempotent: re-running replaces the demo instance and its knowledge.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from safi import config  # noqa: E402
from safi.demo import ensure_demo_repos, load_demo_manifest  # noqa: E402
from safi.gitinfo import git_state  # noqa: E402
from safi.service import RootServiceExpert, ServiceError  # noqa: E402

ALL_ROLES = ["User", "Developer", "Tester", "RCA", "Dispatcher", "Fixer"]


def main():
    ensure_demo_repos(ROOT)
    manifest = load_demo_manifest()
    root = RootServiceExpert()
    instance_id = manifest.get("expert", {}).get("instance_id") or "api-gateway-expert"

    if root.store.instance_exists(instance_id):
        root.store.delete_knowledge_for(instance_id)
        root.store._execute("DELETE FROM instances WHERE id = ?", (instance_id,))
        print(f"reset existing instance: {instance_id}")

    result = root.instantiate({
        "template": "openapi-service",
        "manifest": manifest,
        "instance_id": instance_id,
    })
    print(f"created {result['instance_id']} at sha {result['git']['sha']} "
          f"(seeded {result['seeded_knowledge']} knowledge items)")

    git = git_state(ROOT / "demo" / "api-gateway")
    sha = git["sha"]

    root.ingest(instance_id, {
        "category": "repo training",
        "content": (
            "API Gateway architecture training (verified against the repository at "
            f"SHA {sha}): createReservation is implemented by createReservation() in "
            "src/gateway.py; listReservations, getReservation and cancelReservation "
            "are implemented alongside it in src/gateway.py. The contract/acceptance "
            "tests live in tests/test_contract.py and bind the implementation to "
            "openapi.yaml (paths, methods, operationIds, status codes). Run them with "
            "pytest tests/test_contract.py from the repository root. In-memory "
            "reservation state is module-local."
        ),
        "source": f"repository training @ {sha}",
        "verification_status": "VERIFIED",
        "allowed_roles": ["Developer", "Tester", "RCA", "Fixer"],
    }, user_id="seed-script", requested_roles=["Developer"])
    print("ingested: repository training")

    root.ingest(instance_id, {
        "category": "RCA finding",
        "content": (
            "RCA-2026-1014: POST /reservations (operationId createReservation) rejects "
            "requests that do not carry the X-Request-Id header with HTTP 400 and body "
            '{"detail": "missing required header X-Request-Id"}. Cause: the request-id '
            "middleware in the gateway implementation enforces the tracing header "
            "before routing. openapi.yaml documents X-Request-Id as optional, so this "
            "behaviour was learned from acceptance tests, not from the original SOW."
        ),
        "source": "demo/api-gateway/tests/test_contract.py::test_create_reservation_without_request_id_rejected",
        "verification_status": "VERIFIED",
        "observed_at_sha": sha,
        "allowed_roles": ALL_ROLES,
    }, user_id="seed-script", requested_roles=["Developer"])
    print("ingested: verified RCA finding (X-Request-Id)")

    counts = root.store.knowledge_count(instance_id)
    print("knowledge counts:", counts)
    print(f"instance '{instance_id}' ready — ask Chat as User or Developer.")


if __name__ == "__main__":
    try:
        main()
    except ServiceError as exc:
        print("ERROR:", exc.status_code, exc.detail)
        sys.exit(1)
