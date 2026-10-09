# SOW — Safi API Gateway (Demonstration Service for Service 013)

SOW ID: SOW-013
Service ID: service-013
Branch: main

## 1. Objective

The API Gateway is the single entry point for reservation workflows. It exposes a
documented, versioned HTTP contract and forwards nothing it has not declared in
its `openapi.yaml`.

## 2. In Scope (user-visible contract)

- `GET  /reservations` — list reservations (filters: `limit`, `status`)
- `POST /reservations` — create a reservation
- `GET  /reservations/{reservationId}` — fetch one reservation
- `DELETE /reservations/{reservationId}` — cancel a reservation
- `GET  /health` — gateway liveness

Supported workflows: create a reservation, list reservations, fetch a
reservation, cancel a reservation, check gateway health.

## 3. Out of Scope

- Payment processing
- Authentication / identity management
- Multi-tenant rate limiting
- Any endpoint not present in openapi.yaml

## 4. RBAC Roles for the Service Expert

User, Developer, Tester, RCA, Dispatcher, Fixer.

- User: public API behaviour, how-to information, supported workflows, examples,
  known user-visible limitations.
- Developer: repository architecture, implementation location, Git/SHA history,
  tests, technical decisions (in addition to everything User may see).

## 5. Acceptance Criteria

1. Every response conforms to `openapi.yaml` (status codes and schemas).
2. Contract tests pass: operationIds, paths and methods in the running
   implementation match `openapi.yaml`.
3. Creating, listing, fetching and cancelling a reservation work end to end.
4. A User-role Chat can explain the endpoints, how to call one operation and
   show a valid example request using only user-permitted context.
5. A Developer-role Chat can name the implementation location, the covering
   tests and the exact Git SHA using Developer-permitted context.

## 6. Invariants

- No undocumented endpoints are exposed.
- Reservation ids are unique; duplicate creation is rejected.
- Responses always carry a machine-readable error body on failure.
