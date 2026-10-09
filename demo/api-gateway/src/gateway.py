"""Safi API Gateway — running implementation conforming to openapi.yaml."""

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Safi API Gateway", version="1.0.0")

_RESERVATIONS = {}


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    if request.url.path == "/reservations" and request.method == "POST":
        if not request.headers.get("X-Request-Id"):
            return JSONResponse(
                status_code=400,
                content={"detail": "missing required header X-Request-Id"},
            )
    return await call_next(request)


@app.get("/reservations", operation_id="listReservations")
def listReservations(limit: int = 50, status: str | None = None):
    items = list(_RESERVATIONS.values())
    if status:
        items = [r for r in items if r["status"] == status]
    return items[:limit]


@app.post("/reservations", status_code=201, operation_id="createReservation")
def createReservation(body: dict, x_request_id: str | None = Header(default=None)):
    for field in ("reservationId", "guestName", "roomType", "checkIn", "checkOut"):
        if field not in body:
            raise HTTPException(status_code=400, detail=f"missing field: {field}")
    rid = body["reservationId"]
    if rid in _RESERVATIONS:
        raise HTTPException(status_code=409, detail=f"reservation already exists: {rid}")
    reservation = {
        "reservationId": rid,
        "guestName": body["guestName"],
        "roomType": body["roomType"],
        "checkIn": body["checkIn"],
        "checkOut": body["checkOut"],
        "status": "CONFIRMED",
    }
    _RESERVATIONS[rid] = reservation
    return reservation


@app.get("/reservations/{reservationId}", operation_id="getReservation")
def getReservation(reservationId: str):
    if reservationId not in _RESERVATIONS:
        raise HTTPException(status_code=404, detail=f"reservation not found: {reservationId}")
    return _RESERVATIONS[reservationId]


@app.delete("/reservations/{reservationId}", status_code=204, operation_id="cancelReservation")
def cancelReservation(reservationId: str):
    if reservationId not in _RESERVATIONS:
        raise HTTPException(status_code=404, detail=f"reservation not found: {reservationId}")
    _RESERVATIONS[reservationId]["status"] = "CANCELLED"
    return None


@app.get("/health", operation_id="healthCheck")
def healthCheck():
    return {"status": "up", "service": "api-gateway"}
