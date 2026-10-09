"""Smoke-run the Root Service Expert over a real uvicorn server:

  health -> User chat -> Developer chat -> ingest verified fact -> fresh chat

Run: python scripts/smoke_demo.py
"""

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import os  # noqa: E402

os.environ.setdefault("SAFI_LLM_ENDPOINT", "")  # deterministic extractive mode

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from safi.main import app  # noqa: E402

BASE = "http://127.0.0.1:8013"


def main():
    config = uvicorn.Config(app, host="127.0.0.1", port=8013, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)

    with httpx.Client(base_url=BASE, timeout=10) as c:
        h = c.get("/health")
        print("HEALTH", h.status_code, h.json())

        iid = "api-gateway-expert"
        u = c.post(f"/service-experts/{iid}/chat",
                   headers={"X-User-Id": "amina", "X-Roles": "User"},
                   json={"message": "What endpoints are available?"})
        print("\nUSER CHAT", u.status_code)
        print(u.json()["answer"][:700])

        d = c.post(f"/service-experts/{iid}/chat",
                   headers={"X-User-Id": "dev1", "X-Roles": "Developer"},
                   json={"message": "Where is createReservation implemented, what "
                                    "tests cover it, and what SHA are you describing?"})
        print("\nDEVELOPER CHAT", d.status_code)
        print(d.json()["answer"][:900])

        ing = c.post(f"/service-experts/{iid}/ingest",
                     headers={"X-User-Id": "rca1", "X-Roles": "RCA"},
                     json={"category": "RCA finding",
                           "content": "Verified: cancelReservation marks status "
                                      "CANCELLED but keeps the record; listing with "
                                      "status=CANCELLED still returns it.",
                           "source": "RCA-2026-1102",
                           "verification_status": "VERIFIED",
                           "allowed_roles": ["User", "Developer", "Tester",
                                             "RCA", "Dispatcher", "Fixer"]})
        print("\nINGEST", ing.status_code, ing.json().get("knowledge_id"))

        f = c.post(f"/service-experts/{iid}/chat",
                   headers={"X-User-Id": "amina", "X-Roles": "User"},
                   json={"message": "After I cancel a reservation, does it still "
                                    "show up when I filter by CANCELLED?"})
        print("\nFRESH LEARNING CHAT", f.status_code)
        print(f.json()["answer"][:700])

        g = c.get(f"/service-experts/{iid}",
                  headers={"X-User-Id": "dev1", "X-Roles": "Developer"})
        print("\nGET INSTANCE", g.status_code,
              "knowledge items:", len(g.json()["knowledge"]),
              "sha:", g.json()["git"]["sha"])

        assert h.status_code == 200
        assert u.status_code == d.status_code == f.status_code == g.status_code == 200
        assert ing.status_code == 201
        assert "/reservations" in u.json()["answer"].lower()
        assert "gateway.py" in d.json()["answer"]
        assert "keeps the record" in f.json()["answer"], "fresh fact not in answer"
        print("\nSMOKE OK")

    server.should_exit = True
    thread.join(timeout=10)


if __name__ == "__main__":
    main()
