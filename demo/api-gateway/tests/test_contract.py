"""Acceptance/contract tests for the Safi API Gateway.

These tests bind the running implementation to openapi.yaml: paths, methods,
operationIds and status codes must match the contract.
"""

import json
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from src.gateway import app, _RESERVATIONS

SPEC = yaml.safe_load((Path(__file__).resolve().parents[1] / "openapi.yaml").read_text(encoding="utf-8"))
client = TestClient(app)


def _contract_operations():
    ops = set()
    for path, methods in SPEC["paths"].items():
        for method, op in methods.items():
            if method in ("get", "post", "put", "delete", "patch"):
                ops.add((method, path, op.get("operationId")))
    return ops


def test_contract_matches_implementation():
    impl = client.get("/openapi.json").json()
    impl_ops = set()
    for path, methods in impl["paths"].items():
        for method, op in methods.items():
            if method in ("get", "post", "put", "delete", "patch"):
                impl_ops.add((method, path, op.get("operationId")))
    assert _contract_operations() == impl_ops


def test_health_check():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "up"


def test_create_reservation_conforms_to_contract():
    _RESERVATIONS.clear()
    payload = {
        "reservationId": "RES-2001",
        "guestName": "B. Gopinath",
        "roomType": "SUITE",
        "checkIn": "2026-12-01",
        "checkOut": "2026-12-04",
    }
    resp = client.post("/reservations", json=payload, headers={"X-Request-Id": "t-1"})
    assert resp.status_code == 201
    body = resp.json()
    schema_props = set(SPEC["components"]["schemas"]["Reservation"]["properties"])
    assert set(body) == schema_props
    assert body["status"] == "CONFIRMED"


def test_create_reservation_without_request_id_rejected():
    _RESERVATIONS.clear()
    payload = {
        "reservationId": "RES-2002",
        "guestName": "C. Dev",
        "roomType": "STANDARD",
        "checkIn": "2026-12-01",
        "checkOut": "2026-12-02",
    }
    resp = client.post("/reservations", json=payload)
    assert resp.status_code == 400
    assert "X-Request-Id" in resp.json()["detail"]


def test_duplicate_reservation_rejected():
    _RESERVATIONS.clear()
    payload = {
        "reservationId": "RES-3001",
        "guestName": "D. Tester",
        "roomType": "STANDARD",
        "checkIn": "2026-12-01",
        "checkOut": "2026-12-02",
    }
    assert client.post("/reservations", json=payload, headers={"X-Request-Id": "t-2"}).status_code == 201
    assert client.post("/reservations", json=payload, headers={"X-Request-Id": "t-3"}).status_code == 409


def test_list_get_cancel_flow():
    _RESERVATIONS.clear()
    payload = {
        "reservationId": "RES-4001",
        "guestName": "E. Rca",
        "roomType": "DELUXE",
        "checkIn": "2026-12-05",
        "checkOut": "2026-12-07",
    }
    client.post("/reservations", json=payload, headers={"X-Request-Id": "t-4"})
    assert client.get("/reservations").status_code == 200
    got = client.get("/reservations/RES-4001")
    assert got.status_code == 200
    assert got.json()["guestName"] == "E. Rca"
    assert client.get("/reservations/NOPE").status_code == 404
    assert client.delete("/reservations/RES-4001").status_code == 204
    assert client.get("/reservations/RES-4001").json()["status"] == "CANCELLED"
    assert client.delete("/reservations/NOPE").status_code == 404


def test_example_request_from_contract_is_valid():
    example = SPEC["paths"]["/reservations"]["post"]["requestBody"]["content"]["application/json"]["example"]
    resp = client.post("/reservations", json=example, headers={"X-Request-Id": "t-5"})
    assert resp.status_code == 201
    assert json.dumps(resp.json()).startswith("{")
