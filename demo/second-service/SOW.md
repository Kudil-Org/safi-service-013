# SOW — Inventory Service (second Service Expert for isolation proof)

SOW ID: SOW-INV-002

## Objective

Small inventory lookup service used to prove that Service Expert namespaces are
isolated: knowledge taught to one Service Expert must not leak into another.

## In Scope

- `GET /inventory` — list stock items
- `GET /health` — liveness

## RBAC Roles

User, Developer, Tester, RCA, Dispatcher, Fixer.

## Acceptance Criteria

1. Responses conform to `openapi.yaml`.
2. A fact ingested into a different Service Expert never appears here.
