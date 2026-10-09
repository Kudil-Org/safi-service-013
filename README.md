# SAFI Service 013 — Root Service Expert

**Root Service Expert with OpenAPI Service Template and API Gateway Demonstration**
SOW Date: October 6, 2026 · Six Hours or Nothing

Service 013 builds one **Root Service Expert** that instantiates a role-sensitive,
Git-aware expert for a real OpenAPI service, answers both **User** and
**Developer** questions through **one Chat interface**, and becomes measurably
more knowledgeable after verified experience.

```
ROOT SERVICE EXPERT            <- this repository (Service 013)
|
+-- OpenAPI Service Template   <- .safi/templates/openapi-service.yaml (Template 001)
|
+-- instantiate(...)
|
SERVICE EXPERT INSTANCE        <- demo/api-gateway bound expert
|
+-- SOW Git/SHA  Experience
|     SOW        repository      knowledge store (SQLite, provenance)
|     openapi    training        RCA / fixes / corrections
|     invariants acceptance      verified over time
|                tests
|
+-- RBAC  ->  CHAT (one interface, context filtered BEFORE the model)
```

---

## 1. Quick start

```bat
pip install -r requirements.txt
python scripts\init_demo_repos.py     :: only needed after a fresh clone
python scripts\seed_demo.py           :: instantiate + seed the API Gateway expert
python -m uvicorn safi.main:app --host 127.0.0.1 --port 8013
:: or simply: run.bat
```

Then open <http://127.0.0.1:8013/> for a small built-in chat page (pick the
instance, set `X-User-Id` + roles, ask, and inspect the RBAC-filtered context
that was loaded). It is a thin page over the **one** Chat endpoint — not a
separate Help application. Swagger UI remains at `/docs`.

For a **no-technical-knowledge demo**, open <http://127.0.0.1:8013/demo> — a
guided page where the tester picks a persona (End user / Developer / Tester),
clicks a plain-English example, and sees the answer plus which sources the
expert was allowed to look at.

### Live AI (Groq or any OpenAI-compatible endpoint)

Copy `.env.example` to `.env` and fill it in (`.env` is gitignored):

```bat
copy .env.example .env
```

```ini
SAFI_LLM_ENDPOINT=https://api.groq.com/openai/v1
SAFI_LLM_API_KEY=gsk_...
SAFI_LLM_MODEL=openai/gpt-oss-120b
```

When configured, Chat uses the live model over **role-filtered context only**;
`/ui/status` and every response report the mode. Without it, Chat automatically
falls back to the deterministic extractive answerer.

Run all acceptance tests (TEST 1–12 plus RBAC/ingest extras):

```bat
python -m pytest -q
```

End-to-end smoke over a real uvicorn server (health -> User chat -> Developer
chat -> ingest -> fresh learning chat):

```bat
python scripts\smoke_demo.py
```

The LLM endpoint is optional and singular — configure exactly one via a
gitignored `.env` file (auto-loaded) or environment variables:

```bat
set SAFI_LLM_ENDPOINT=https://your-llm/v1/chat/completions
set SAFI_LLM_API_KEY=...
set SAFI_LLM_MODEL=...
```

If no endpoint is configured, Chat falls back to a deterministic **extractive**
answerer that quotes only role-permitted context (never invents endpoints).
Mode is reported per response as `llm_mode` (`endpoint` | `extractive`).

---

## 2. The Root Service Expert API (its own `openapi.yaml`)

Service 013 is itself an OpenAPI Service. Contract: [`openapi.yaml`](openapi.yaml)
(also served at `GET /openapi.yaml`), validated and exercised by TEST 11.

| Operation | Purpose |
|---|---|
| `POST /service-experts` | Instantiate one logical Service Expert instance from a Root template |
| `POST /service-experts/{id}/ingest` | Feed new Service knowledge with provenance + verification status |
| `POST /service-experts/{id}/chat` | RBAC-sensitive Chat — the single interface for all roles |
| `GET /service-experts/{id}` | Inspect an instance (knowledge returned only for permitted roles) |
| `GET /health` | Liveness, DB status, LLM configuration |

Caller identity and roles come from **existing RBAC** passed as headers — no new
identity system is built:

```
X-User-Id: amina          (required for chat/ingest; 401 if missing)
X-Roles: User,Developer   (comma separated; 403 if no declared role matches)
```

---

## 3. Template completion (Template 001)

`.safi/templates/openapi-service.yaml` is machine-readable with three field
classes:

* **required** — must be present and non-empty or instantiation is rejected with
  `422 {error: manifest_failed_template_validation, missing: [...]}`
  (service.id, service.name, service.purpose, sow.id, sow.location, git.repo,
  git.branch, git.current_sha, api.openapi, api.implementation, api.operations,
  invariants, expert.roles, acceptance_tests, out_of_scope)
* **conditional** — type-checked when supplied (data_store, external_dependencies,
  deployment_target, rollback, cost_controls, security_sensitive_resources,
  background_jobs)
* **growing** — optional, appended over time (verified_rca_findings,
  accepted_fixes, failed_approaches, human_corrections, known_traps,
  user_help_knowledge, release_results, verified_examples)

Missing required fields are **never silently accepted** (TEST 2).

---

## 4. Instantiation

```bat
curl -X POST http://127.0.0.1:8013/service-experts -H "Content-Type: application/json" ^
 -d "{\"template\":\"openapi-service\",\"manifest\":{...},\"instance_id\":\"api-gateway-expert\"}"
```

The manifest (`.safi/service-expert.yaml`) carries scope only — SOW identity,
Git repo/branch/SHA, openapi.yaml location, implementation entrypoint,
operations, invariants, RBAC roles, acceptance tests, out-of-scope. The
intelligence lives in the provenance store, not in the manifest.

On instantiation the Root Expert:

1. validates the manifest against the template (422 on missing/invalid fields),
2. resolves the bound Git repository and records **live** branch/SHA
   (live state wins; `sha_matches_manifest` reports any divergence),
3. seeds authoritative knowledge from the SOW and openapi.yaml (user/developer
   summaries derived from the contract), acceptance-test references, and
   repository training — each with provenance.

Each instance is a **logically isolated namespace** (`instances` +
`knowledge.service_expert_id` tables in SQLite). No new process, no new LLM
(TEST 9).

---

## 5. Ingest — the feed interface

```bat
curl -X POST http://127.0.0.1:8013/service-experts/api-gateway-expert/ingest ^
 -H "Content-Type: application/json" -H "X-User-Id: rca1" -H "X-Roles: RCA" ^
 -d "{\"category\":\"RCA finding\",\"content\":\"...\",\"source\":\"RCA-2026-1014\",
      \"verification_status\":\"VERIFIED\",\"observed_at_sha\":\"<sha>\"}"
```

* Categories: `SOW`, `OpenAPI`, `repo training`, `acceptance test result`,
  `RCA finding`, `fix result`, `human correction`, `release result`,
  `Help correction`
* `verification_status`: `AUTHORITATIVE` | `VERIFIED` | `UNVERIFIED`
* Provenance is mandatory: `source`, `repo`, `branch`, `observed_at_sha`
  (explicit or resolved from the bound repository at ingest time), plus
  `created_at` and `knowledge_id` assigned by the store
* `allowed_roles` defaults per category and may only contain the standard
  vocabulary — person-specific roles are rejected (422)
* Every knowledge row keeps the full contract:
  `knowledge_id, service_expert_id, repo, branch, observed_at_sha, category,
  content, source, verification_status, allowed_roles, created_at`

---

## 6. Chat — one interface, RBAC-filtered context

```
Authenticate Caller (X-User-Id)
  -> Resolve Roles (X-Roles ∩ instance-declared roles)
  -> Resolve Service Expert Instance
  -> Load ONLY role-permitted context          <- security filtering happens HERE,
  -> Add current chat message                     before any model context assembly
  -> Start fresh micro-session (no cross-chat memory)
  -> Return answer
```

Standard roles: **User, Developer, Tester, RCA, Dispatcher, Fixer** (no
person-specific roles).

| Role | Context loaded |
|---|---|
| User | public API behaviour, how-to, workflows, examples, user-visible limitations (SOW + OpenAPI user summary + Help knowledge) |
| Developer | everything User gets + repo architecture, implementation location, Git/SHA history, tests, technical decisions |
| Tester | public API + tests, implementation, acceptance criteria |
| RCA | repo structure, logs/failures, verified RCA findings, read-only technical context |
| Dispatcher | public API, how-to, release results, RCA findings |
| Fixer | RCA, source context, accepted fixes, protected tests, write boundaries |

The same Service Expert instance answers both of these (TEST 6):

* **User:** “What endpoints are available?”, “How do I call the
  createReservation API?”, “Show me a valid example request.” — answers derived
  from OpenAPI/SOW context only; no developer-only source or test internals leak
  (TEST 4).
* **Developer:** “Where is createReservation implemented and what tests cover
  it? What exact SHA are you describing?” — implementation file, covering tests
  and the exact SHA (TEST 5).

---

## 7. Knowledge authority and Git/SHA awareness

* **AUTHORITATIVE**: SOW, openapi.yaml, acceptance tests, current Git state
* **VERIFIED EXPERIENCE**: accepted RCA findings, accepted fixes, verified test
  outcomes, approved corrections
* **UNVERIFIED EXPERIENCE**: hypotheses, observations, suggestions — always
  labelled `[UNVERIFIED]` in context and ordered after authoritative material so
  it never silently overrides it

Knowledge is anchored to `repo/branch/observed_at_sha`. At Chat time each item
is annotated `current` or `historical` against the **live** Git state; the
header always states the current branch/SHA, and stale items are marked
historical instead of being asserted as current truth (TEST 10).

---

## 8. Learning — verified facts in fresh sessions

Ingest a verified fact, then start a **new** Chat micro-session: no prompt or
code changes are needed for the expert to retrieve and use it (TEST 8).
Demonstration fact seeded by `scripts/seed_demo.py`:

> RCA-2026-1014 — POST /reservations rejects requests without `X-Request-Id`
> with HTTP 400 … (not present in the original SOW; learned from the acceptance
> test, observed at SHA `93015e4…`, status VERIFIED, visible to all roles).

---

## 9. Demonstration — API Gateway Service Expert

* Repository: `demo/api-gateway/` — a **real** git repository (branch `main`)
  containing `SOW.md`, `openapi.yaml`, the FastAPI implementation
  `src/gateway.py`, and contract/acceptance tests `tests/test_contract.py`
  (7 tests, all passing; they bind paths/methods/operationIds/status codes to
  the contract).
* Manifest: `.safi/service-expert.yaml` (instance `api-gateway-expert`)
* Seeded knowledge: SOW, OpenAPI user + developer summaries, acceptance-test
  references, repository training, verified RCA finding
* A second Service Expert (`demo/second-service/`, Inventory) instantiates from
  the same Root template and proves namespace isolation (TEST 9).

After a fresh clone the nested demo histories are recreated by
`python scripts/init_demo_repos.py`; the manifest keeps the authored SHA while
the live Git state always wins (`sha_matches_manifest: false` until histories
match).

---

## 10. Acceptance tests (SOW §28)

| Test | Name | Where |
|---|---|---|
| 1 | Root template exists, sections identifiable | `test_01_root_template_exists` |
| 2 | Missing required fields rejected | `test_02_missing_required_fields_rejected` |
| 3 | API Gateway instance materialised | `test_03_api_gateway_instance` |
| 4 | User role Chat (§20 questions) | `test_04_user_role_chat` |
| 5 | Developer role Chat (§21 questions) | `test_05_developer_role_chat` |
| 6 | Same expert for both roles | `test_06_same_expert_for_all_roles` |
| 7 | Provenance stored on ingest | `test_07_provenance_stored` |
| 8 | Fresh learning in a new session | `test_08_fresh_learning_used_in_new_session` |
| 9 | Knowledge isolation between experts | `test_09_knowledge_isolation` |
| 10 | SHA awareness (historical vs current) | `test_10_sha_awareness` |
| 11 | Root openapi.yaml validated + exercised | `test_11_root_openapi_contract` |
| 12 | Restart persistence | `test_12_restart_persistence` |
| + | identity/role enforcement, ingest validation, unverified labelling | `test_rbac_*`, `test_ingest_validation`, `test_unverified_*` |
| + | built-in chat page served over the one Chat endpoint | `test_chat_ui_is_served_and_shares_the_one_endpoint` |

```bat
python -m pytest -q        :: 16 passed
```

State (templates, instances, knowledge, sessions) persists in SQLite
(`safi_root.db`, configurable with `SAFI_DB_PATH`) and survives restart (TEST 12).

---

## 11. Repository layout

```
openapi.yaml                        Root Service Expert contract (Service 013)
.safi/templates/openapi-service.yaml  Template 001 (required/conditional/growing)
.safi/service-expert.yaml           API Gateway demo manifest (scope only)
.safi/root-knowledge.yaml           Reusable Safi-wide rules (seeded to __root__)
safi/
  main.py          uvicorn entrypoint (safi.main:app)
  app/__init__.py  create_app + the five operations + error mapping
  service.py       instantiate / ingest / chat / get / health core
  template.py      template loading + manifest validation
  rbac.py          standard roles, role->context map, category defaults
  chat/            role-filtered context assembly + answer generation
  web/index.html   advanced console page (/)
  web/tester.html  guided, no-technical-knowledge demo (/demo)
  storage/         SQLite provenance store (instances, knowledge, sessions)
  llm.py           one configured LLM endpoint (extractive fallback)
  gitinfo.py       Git CLI: repo/branch/SHA/log/files
  demo.py          demo repo + manifest helpers
demo/api-gateway/   real API Gateway repo (SOW, contract, impl, tests) — own git
demo/second-service/ small Inventory repo for the isolation proof — own git
scripts/            init_demo_repos.py, seed_demo.py, smoke_demo.py
tests/              acceptance tests TEST 1-12 (+RBAC/ingest extras)
```

---

## 12. Standard Requirement Created for Future SOWs (SOW §30)

After Service 013 is accepted, **every subsequent Safi SOW** shall include a
Service Expert section requiring the developer to:

1. instantiate a new scoped Service Expert from the Root Service Expert
2. fill the applicable Service Expert Template (`.safi/templates/*.yaml`)
3. supply the SOW
4. supply `openapi.yaml`
5. bind the Git repo, branch and SHA
6. supply acceptance tests
7. declare RBAC roles/context permissions
8. feed verified development outcomes with provenance
9. demonstrate role-sensitive Chat
10. demonstrate one fresh learned fact

Out of scope by design (SOW §31): fancy chat UI, new RBAC/identity systems,
fine-tuning, knowledge graphs, vector platforms, web search, billing,
autonomous source modification.

---

Proprietary and Copyright 2026 B. Gopinath
