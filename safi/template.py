import copy
from pathlib import Path

import yaml

SECTION_NAMES = ("required", "conditional", "growing")


def load_template_file(path):
    path = Path(path)
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"template file is not a mapping: {path}")
    template_id = data.get("template_id")
    if not template_id:
        raise ValueError(f"template file missing template_id: {path}")
    sections = data.get("sections")
    if not isinstance(sections, dict):
        raise ValueError(f"template file missing sections mapping: {path}")
    for name in SECTION_NAMES:
        if name not in sections or not isinstance(sections[name], list):
            raise ValueError(f"template '{template_id}' missing section '{name}': {path}")
    return data


def load_templates(templates_dir):
    templates = {}
    templates_dir = Path(templates_dir)
    if not templates_dir.exists():
        return templates
    for path in sorted(templates_dir.glob("*.yaml")) + sorted(templates_dir.glob("*.yml")):
        template = load_template_file(path)
        template["_source_path"] = str(path)
        templates[template["template_id"]] = template
    return templates


def get_path(mapping, dotted_key):
    node = mapping
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def set_path(mapping, dotted_key, value):
    parts = dotted_key.split(".")
    node = mapping
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):
            raise TypeError(f"cannot set {dotted_key}: {part} is not a mapping")
    node[parts[-1]] = value


def _is_empty(value):
    return value is None or value == "" or value == [] or value == {}


def _type_ok(value, expected):
    expected = expected if isinstance(expected, list) else [expected]
    for name in expected:
        if name == "string" and isinstance(value, str):
            return True
        if name == "list" and isinstance(value, list):
            return True
        if name == "object" and isinstance(value, dict):
            return True
        if name == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if name == "boolean" and isinstance(value, bool):
            return True
    return False


def validate_manifest(template, manifest):
    """Validate a Service Expert manifest against a Root template.

    Returns {"missing": [dotted keys], "invalid": [{"key","expected","actual"}]}.
    Required fields must be present and non-empty. Conditional fields are
    type-checked when supplied. Growing fields are optional but must have the
    declared shape when supplied.
    """
    report = {"missing": [], "invalid": []}
    if not isinstance(manifest, dict):
        report["missing"].append("(manifest)")
        return report

    sections = template.get("sections", {})
    for field in sections.get("required", []):
        key = field["key"]
        value = get_path(manifest, key)
        if _is_empty(value):
            report["missing"].append(key)
        elif not _type_ok(value, field.get("type", "string")):
            report["invalid"].append({
                "key": key,
                "expected": field.get("type", "string"),
                "actual": type(value).__name__,
            })

    for field in sections.get("conditional", []):
        key = field["key"]
        value = get_path(manifest, key)
        if _is_empty(value):
            continue
        if not _type_ok(value, field.get("type", "string")):
            report["invalid"].append({
                "key": key,
                "expected": field.get("type", "string"),
                "actual": type(value).__name__,
            })

    for field in sections.get("growing", []):
        key = field["key"]
        value = get_path(manifest, key)
        if _is_empty(value):
            continue
        if not _type_ok(value, field.get("type", "list")):
            report["invalid"].append({
                "key": key,
                "expected": field.get("type", "list"),
                "actual": type(value).__name__,
            })

    return report


def field_description(template, dotted_key):
    for section in SECTION_NAMES:
        for field in template.get("sections", {}).get(section, []):
            if field.get("key") == dotted_key:
                return field.get("description", "")
    return ""


def apply_overrides(manifest, overrides):
    """Merge top-level instantiate overrides into the manifest.

    Explicit top-level input wins over the manifest value.
    """
    manifest = copy.deepcopy(manifest)
    mapping = {
        "repo": "git.repo",
        "branch": "git.branch",
        "sha": "git.current_sha",
        "openapi": "api.openapi",
    }
    for top_key, dotted in mapping.items():
        value = overrides.get(top_key)
        if value:
            set_path(manifest, dotted, value)
    if overrides.get("acceptance_tests"):
        manifest["acceptance_tests"] = list(overrides["acceptance_tests"])
    if overrides.get("sow"):
        sow = manifest.get("sow")
        if not isinstance(sow, dict):
            sow = {}
        sow.update(overrides["sow"])
        manifest["sow"] = sow
    return manifest
