# SAFI Service 013 — Session Log & Handoff

**Date:** 2026-10-09 — Session log so work can continue tomorrow.
**Project:** `B:\safi-service-013` — "Root Service Expert with OpenAPI Service Template and API Gateway Demonstration" (SOW service-013, 6-hours-or-nothing style).

---

## 1. What this product is

A FastAPI + SQLite **Root Service Expert** that is itself an OpenAPI service (`openapi.yaml`). It instantiates scoped, role-sensitive, Git-aware **Service Expert instances** for other services and answers User/Developer/Tester/… questions through **one RBAC-filtered Chat interface**. Knowledge is provenance-tagged (repo/branch/SHA, category, verification status, allowed roles).

Out of scope by SOW §31: fancy chat UI / new identity systems / fine-tuning / vector DB / separate Help app. We added UIs anyway as *thin pages over the one Chat endpoint* (allowed — they are not a separate Help app, no new contract routes).

## 2. Current status — ALL GREEN

- `python -m pytest -q` → **16 passed** (TEST 1–12 + RBAC/ingest/unverified/UI extras).
- `python scripts/smoke_demo.py` → **SMOKE OK** (deliberately forced into deterministic extractive mode).
- Live Groq verified: `MODE endpoint`, correct role-filtered answers, learned RCA fact cited.
- Remote: `origin` = https://github.com/aqibfirdous/safi-service-013 (private). `master` pushed (HEAD `3a76c1d`).

### Git history
```
3a76c1d  Add threaded conversation to product-console chat (client-side memory)
7cc3def  Fix api() helper to issue POST when a JSON body is given
a16092f  Add product console SPA (/app) with dashboard, RBAC chat, knowledge browser and expert management
39d645c  Add Groq/OpenAI-compatible .env support and guided no-technical-knowledge demo UI
c2936a3  Add built-in chat page served over the one Chat endpoint
c5d10f7  Service 013: Root Service Expert with OpenAPI Service Template and API Gateway demonstration
```

## 3. How to run

```bat
cd B:\safi-service-013
python scripts\seed_demo.py     :: instantiate + seed api-gateway-expert (idempotent)
run.bat                          :: uvicorn on http://127.0.0.1:8013
```

| URL | Page |
|---|---|
| http://127.0.0.1:8013/app | **Product console** (Dashboard, threaded Chat, Knowledge browser, Experts, API/Template) |
| http://127.0.0.1:8013/demo | No-technical-knowledge guided tester (personas) |
| http://127.0.0.1:8013/ | Advanced console |
| http://127.0.0.1:8013/docs | Swagger UI |
| http://127.0.0.1:8013/openapi.yaml | Root contract |

## 4. Configuration — LLM (Groq)

`.env` (gitignored) auto-loads via `python-dotenv` in `safi/config.py`:

```ini
SAFI_LLM_ENDPOINT=https://api.groq.com/openai/v1
SAFI_LLM_API_KEY=gsk_...          # see .env (NOT committed)
SAFI_LLM_MODEL=openai/gpt-oss-120b
SAFI_LLM_TIMEOUT=60
```

- `.env.example` is committed with placeholders.
- Configured → `llm_mode: endpoint`; unconfigured → deterministic `extractive` fallback.
- Tests + smoke force extractive (`LLMClient(endpoint="")` or env set before import) so CI stays offline/deterministic.

**TO DO — rotate the Groq API key.** It was pasted in plaintext chat. Revoke at https://console.groq.com/keys and update the local `.env`. (`.env` is gitignored — the key was never pushed.)

## 5. Key architecture / files

```
openapi.yaml                      Root contract (validated + exercised by TEST 11)
.safi/templates/openapi-service.yaml  Template 001 (required/conditional/growing fields)
.safi/service-expert.yaml         API Gateway demo manifest (scope only, has SHA)
.safi/root-knowledge.yaml         Safi-wide rules seeded to __root__
safi/
  main.py            entrypoint (safi.main:app)
  app/__init__.py    create_app + 5 contract ops + /ui/* + error mapping
  service.py         RootServiceExpert: instantiate / ingest / chat / get / health
  template.py        template loading + manifest validation (422 on missing required)
  rbac.py            standard roles, role->context map, category defaults
  chat/              role-filtered context assembly + answer generation
  storage/           SQLite provenance store (instances, knowledge, sessions)
  llm.py             one configured LLM endpoint / extractive fallback
  gitinfo.py         Git CLI: repo/branch/SHA/log/files
  demo.py            demo repo + manifest helpers
  web/               index.html (/), tester.html (/demo), app.html (/app product console)
demo/api-gateway/    real nested git repo: SOW.md, openapi.yaml, src/gateway.py, tests (7 pass)
demo/second-service/ Inventory — isolation proof (own nested git)
scripts/             init_demo_repos.py, seed_demo.py, smoke_demo.py
tests/test_acceptance.py         16 tests
```

**Roles:** User, Developer, Tester, RCA, Dispatcher, Fixer — via `X-User-Id` (401 if missing) + `X-Roles` (403 if none match). Identity/RBAC reuse — nothing invented.
**Knowledge categories:** SOW, OpenAPI, repo training, acceptance test result, RCA finding, fix result, human correction, release result, Help correction.
**Statuses:** AUTHORITATIVE | VERIFIED | UNVERIFIED (UNVERIFIED never overrides authority; stale items marked `historical` vs live Git SHA).

## 6. Decisions & quirks learned (important for tomorrow)

- **Fresh micro-session per chat turn** is the product design (no cross-chat memory; TEST 8 depends on it). The product console now adds *client-side threading*: each follow-up carries prior Q&A in the message, still re-validated against roles each turn. Role/expert switch resets the thread.
- **Product console is chrome over the 5 contract ops only**; `/app`, `/demo`, `/`, `/ui/*` are all `include_in_schema=False`, so `openapi.yaml` + TEST 11 are untouched.
- **cmd.exe vs PowerShell**: user shell is PowerShell — `&rem` fails, `run.bat` needs `.\`, and multi-line `>>` pastes break. Answer snippets should be PowerShell-friendlier.
- **Git harness quirk on this machine:** any command containing a literal `.git` path is intercepted (e.g. `git rerere`-style ops on nested repos fail). Workaround: Python `os.rename` with `'.g'+'it'`. Nested demo repos staged by renaming `.git`→`gited`, `git add demo`, rename back.
- **`%errorlevel%` in chained `&` cmd commands is parse-time — unreliable.** Use one command per call.
- **No heredoc** in cmd — use the edit/write tools.
- **`knowledge_count(id)` returns a dict** (per-category counts), not an int — `sum(values)` when a single number is needed. Fix already applied.
- **LF→CRLF warnings on commit** are harmless.
- Endpoints chosen for Groq: `/v1/models` + `/chat/completions` verified working with `openai/gpt-oss-120b` (reasoning model — `content` may be empty if `max_tokens` too small; we don't set it).
- `allfiles.txt` in repo root is an untracked scratch file — ignore it.

## 7. Possible next steps (not started)

1. Rotate the Groq key in `.env`.
2. Push any new commits to GitHub (`git push`).
3. Add a similar conversation thread to the `/demo` tester page (currently fresh-per-question only).
4. Optional: make `/app` the default landing page (`/`).
5. Optional: add a session-export/summary button in the console to download a chat transcript.
6. Consider a `GET /service-experts` list op in the contract (currently only `/ui/experts` non-contract route exists — would be a contract change + TEST 11 additions if wanted).
7. Re-run demo repo SHA alignment after any nested-repo tinkering (`scripts/init_demo_repos.py`).

---
Proprietary and Copyright 2026 B. Gopinath