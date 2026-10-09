STANDARD_ROLES = ("User", "Developer", "Tester", "RCA", "Dispatcher", "Fixer")

ALL_ROLES = list(STANDARD_ROLES)

ROLE_CONTEXT = {
    "User": {
        "public_api", "how_to", "examples", "user_limitations",
    },
    "Developer": {
        "public_api", "how_to", "examples", "user_limitations",
        "architecture", "implementation", "git_history", "tests", "technical_decisions",
    },
    "Tester": {
        "public_api", "how_to", "examples", "tests", "implementation", "acceptance_criteria",
    },
    "RCA": {
        "public_api", "architecture", "implementation", "git_history",
        "logs_failures", "rca_findings", "diagnostics",
    },
    "Dispatcher": {
        "public_api", "how_to", "user_limitations", "release_results", "rca_findings",
    },
    "Fixer": {
        "architecture", "implementation", "git_history", "tests",
        "rca_findings", "accepted_fixes", "write_boundaries",
    },
}

INGEST_CATEGORIES = (
    "SOW",
    "OpenAPI",
    "repo training",
    "acceptance test result",
    "RCA finding",
    "fix result",
    "human correction",
    "release result",
    "Help correction",
)

VERIFICATION_STATUSES = ("AUTHORITATIVE", "VERIFIED", "UNVERIFIED")

AUTHORITY_RANK = {"AUTHORITATIVE": 0, "VERIFIED": 1, "UNVERIFIED": 2}

CATEGORY_ORDER = {
    "root rule": 0,
    "SOW": 1,
    "OpenAPI": 2,
    "acceptance test result": 3,
    "repo training": 4,
    "human correction": 5,
    "fix result": 6,
    "RCA finding": 7,
    "release result": 8,
    "Help correction": 9,
}

CATEGORY_DEFAULT_ROLES = {
    "root rule": ALL_ROLES,
    "SOW": ALL_ROLES,
    "OpenAPI": ALL_ROLES,
    "repo training": ["Developer", "Tester", "RCA", "Fixer"],
    "acceptance test result": ["Developer", "Tester", "RCA", "Fixer", "Dispatcher"],
    "RCA finding": ["RCA", "Fixer", "Developer"],
    "fix result": ["Fixer", "Developer", "RCA", "Tester"],
    "human correction": ALL_ROLES,
    "release result": ["Developer", "Tester", "RCA", "Dispatcher", "Fixer"],
    "Help correction": ["User", "Developer", "Tester"],
}

CATEGORY_DEFAULT_STATUS = {
    "root rule": "AUTHORITATIVE",
    "SOW": "AUTHORITATIVE",
    "OpenAPI": "AUTHORITATIVE",
    "acceptance test result": "AUTHORITATIVE",
    "human correction": "AUTHORITATIVE",
}


def parse_roles(header_value):
    if header_value is None:
        return []
    roles = []
    for part in str(header_value).split(","):
        role = part.strip()
        if role:
            roles.append(role)
    return roles


def resolve_roles(requested_roles, declared_roles):
    """Return (effective_roles, rejected_roles).

    Only the standard Safi role vocabulary is honoured; person-specific roles
    are rejected. Effective roles are the intersection of requested and
    declared roles for the Service Expert instance.
    """
    declared = [r for r in (declared_roles or []) if r in STANDARD_ROLES]
    effective = []
    rejected = []
    seen = set()
    for role in requested_roles or []:
        if role in STANDARD_ROLES and role in declared and role not in seen:
            effective.append(role)
            seen.add(role)
        elif role not in seen:
            rejected.append(role)
            seen.add(role)
    return effective, rejected


def permitted_categories(effective_roles):
    categories = set()
    for role in effective_roles:
        categories |= ROLE_CONTEXT.get(role, set())
    return sorted(categories)


def default_roles_for_category(category):
    return list(CATEGORY_DEFAULT_ROLES.get(category, ALL_ROLES))
