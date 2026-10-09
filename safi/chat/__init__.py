import re

from safi.rbac import AUTHORITY_RANK, CATEGORY_ORDER, permitted_categories

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "do", "does", "did",
    "how", "what", "where", "when", "which", "who", "why", "i", "me", "my", "we", "you",
    "your", "it", "its", "this", "that", "these", "those", "to", "in", "of", "for",
    "on", "at", "by", "from", "with", "as", "and", "or", "not", "no", "can", "could",
    "should", "would", "will", "shall", "may", "might", "please", "show", "tell",
    "give", "list", "get", "set", "if", "then", "than", "into", "out", "up", "so",
    "them", "they", "he", "she", "them", "us", "am", "have", "has", "had", "about",
    "available", "exactly", "specific",
}

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def tokenize(text):
    return [t.lower() for t in TOKEN_RE.findall(text or "") if t.lower() not in STOPWORDS]


def _score(question_tokens, item):
    text = (item.get("category", "") + " " + item.get("content", "")).lower()
    item_tokens = set(tokenize(text))
    if not item_tokens:
        return 0
    score = 0
    for tok in question_tokens:
        if tok in item_tokens:
            score += 3 if len(tok) > 6 else 2
    return score


def _authority_key(item):
    return (
        AUTHORITY_RANK.get(item.get("verification_status"), 3),
        CATEGORY_ORDER.get(item.get("category"), 50),
        item.get("created_at", ""),
    )


def select_items(question, items, limit=6):
    q_tokens = tokenize(question)
    scored = [(_score(q_tokens, item), item) for item in items]
    hits = [item for score, item in scored if score > 0]
    hits.sort(key=lambda item: (-_score(q_tokens, item), _authority_key(item)))
    selected = hits[:limit]
    if len(selected) < 3:
        seen = {item["knowledge_id"] for item in selected}
        fillers = sorted(
            (item for item in items if item["knowledge_id"] not in seen
             and item.get("verification_status") == "AUTHORITATIVE"),
            key=_authority_key,
        )
        for item in fillers:
            if len(selected) >= 3:
                break
            selected.append(item)
    if not selected:
        selected = sorted(items, key=_authority_key)[:3]
    return selected


def _truncate(text, limit):
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _instance_service(instance):
    manifest = instance.get("manifest") or {}
    service = manifest.get("service") or {}
    return service


def assemble_context(root, instance, effective_roles, question):
    """Load ONLY role-permitted knowledge, annotated with Git/SHA status.

    Security filtering happens here, before any model context assembly.
    """
    expert_id = instance["id"]
    manifest = instance.get("manifest") or {}
    stored_git = instance.get("git_state") or {}
    live_git = root.live_git(manifest)
    current_sha = (live_git or {}).get("sha") or stored_git.get("sha") or ""

    rows = root.store.list_knowledge([expert_id, "__root__"], roles=effective_roles)

    historical = 0
    items = []
    for row in rows:
        observed = row.get("observed_at_sha") or ""
        if current_sha and observed and observed != current_sha:
            sha_status = "historical"
            historical += 1
        elif current_sha and observed:
            sha_status = "current"
        else:
            sha_status = "unknown"
        row["sha_status"] = sha_status
        row["content"] = _truncate(row.get("content", ""), 1600)
        items.append(row)

    items.sort(key=lambda item: (_authority_key(item), item.get("service_expert_id") != expert_id))

    notes = []
    if historical:
        notes.append(
            f"{historical} experience item(s) were observed at a different SHA than the "
            f"current Git state and are marked historical; current Git state outranks "
            f"historical memory."
        )
    unverified = [i for i in items if i.get("verification_status") == "UNVERIFIED"]
    if unverified:
        notes.append(
            "Unverified experience is marked [UNVERIFIED] and does not silently "
            "override authoritative SOW / openapi.yaml / acceptance-test material."
        )

    return {
        "items": items,
        "live_git": live_git,
        "current_sha": current_sha,
        "permitted_categories": permitted_categories(effective_roles),
        "notes": notes,
    }


def _format_item(item):
    observed = item.get("observed_at_sha") or "n/a"
    return (
        f"- [{item.get('category')}] ({item.get('verification_status')}, "
        f"observed at {observed}, {item.get('sha_status')}, "
        f"roles: {', '.join(item.get('allowed_roles') or [])})\n"
        f"  {item.get('content', '')}"
    )


def build_prompt(question, ctx, instance, effective_roles, user_id, session_id):
    service = _instance_service(instance)
    git = ctx.get("live_git") or {}
    header_lines = [
        f"Service Expert: {instance['id']} (template {instance.get('template_id')}, "
        f"service {service.get('name', '?')})",
        f"Session: {session_id} (fresh micro-session, no prior chat memory)",
        f"Caller: user={user_id or 'unknown'}, roles={effective_roles}",
    ]
    if git:
        header_lines.append(
            f"Current Git state: repo={git.get('repo')} branch={git.get('branch')} "
            f"sha={git.get('sha')} (current Git state outranks historical memory)"
        )
    header_lines.append(
        f"Role-permitted context categories: {', '.join(ctx['permitted_categories'])}"
    )
    header_lines.append(
        f"Context loaded ({len(ctx['items'])} items, RBAC-filtered BEFORE model):"
    )
    body = "\n\n".join(_format_item(item) for item in ctx["items"]) or \
        "(no permitted context available for this question under these roles)"
    notes = "\n".join(f"Note: {note}" for note in ctx["notes"])
    user_prompt = (
        f"{chr(10).join(header_lines)}\n\n{body}\n\n{notes}\n\n"
        f"Current question: {question}"
    )
    return user_prompt


SYSTEM_PROMPT = (
    "You are a SAFI Service Expert. Answer ONLY from the provided role-permitted "
    "context. Never invent endpoints, files, tests, or behaviour that is not in the "
    "context. When you use an experience item, mention the SHA it was observed at "
    "and whether it is current or historical. Authoritative material (SOW, "
    "openapi.yaml, acceptance tests, current Git state) outranks experience; "
    "unverified experience must be labelled as unverified. If the permitted context "
    "does not contain the answer, say exactly that and state which roles would have "
    "the missing context."
)


def extractive_answer(question, ctx, instance, effective_roles, user_id, session_id):
    """Deterministic fallback: answer is composed strictly from filtered context."""
    service = _instance_service(instance)
    git = ctx.get("live_git") or {}
    lines = []
    lines.append(
        f"Service Expert '{instance['id']}' (template {instance.get('template_id')}, "
        f"service {service.get('name', '?')}) — fresh micro-session {session_id}."
    )
    if git:
        lines.append(
            f"Current Git state: repo {git.get('repo')}, branch {git.get('branch')}, "
            f"SHA {git.get('sha')} (current Git state outranks historical memory)."
        )
    lines.append(
        f"RBAC: roles {effective_roles}; permitted context categories: "
        f"{', '.join(ctx['permitted_categories'])}. Context was filtered by role "
        f"before assembly."
    )
    selected = select_items(question, ctx["items"])
    if not selected:
        lines.append(
            "No permitted context is available for this question under the current "
            "roles. No answer is generated from outside the permitted context."
        )
    else:
        lines.append("Answer from role-permitted context:")
        for item in selected:
            lines.append(_format_item(item))
    for note in ctx["notes"]:
        lines.append(f"Note: {note}")
    return "\n".join(lines)


def generate_answer(root, question, ctx, instance, effective_roles, user_id, session_id):
    """Return (answer, mode). Tries the configured LLM endpoint, falls back to
    the deterministic extractive answerer on any failure."""
    if root.llm.configured:
        try:
            prompt = build_prompt(question, ctx, instance, effective_roles, user_id, session_id)
            answer = root.llm.complete(SYSTEM_PROMPT, prompt)
            if answer and answer.strip():
                return answer.strip(), "endpoint"
        except Exception:
            pass
    answer = extractive_answer(question, ctx, instance, effective_roles, user_id, session_id)
    return answer, "extractive"
