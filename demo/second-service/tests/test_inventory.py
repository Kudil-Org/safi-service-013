from fastapi.testclient import TestClient

from src.inventory import app

client = TestClient(app)


def test_contract_ops():
    impl = client.get("/openapi.json").json()
    ops = {
        (m, p, op.get("operationId"))
        for p, methods in impl["paths"].items()
        for m, op in methods.items()
        if m in ("get", "post", "put", "delete", "patch")
    }
    assert ("get", "/inventory", "listInventory") in ops
    assert ("get", "/health", "healthCheck") in ops


def test_list_inventory():
    resp = client.get("/inventory")
    assert resp.status_code == 200
    assert all({"sku", "name", "qty"} <= set(item) for item in resp.json())
