"""Inventory Service — running implementation conforming to openapi.yaml."""

from fastapi import FastAPI

app = FastAPI(title="Inventory Service", version="0.2.0")

_STOCK = [
    {"sku": "SKU-1", "name": "Towel", "qty": 40},
    {"sku": "SKU-2", "name": "Robe", "qty": 12},
]


@app.get("/inventory", operation_id="listInventory")
def listInventory():
    return _STOCK


@app.get("/health", operation_id="healthCheck")
def healthCheck():
    return {"status": "up"}
