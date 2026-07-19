"""Schema-driven UI field descriptors for profile editing.

Derives UI structure from UserProfile's Pydantic v2 JSON schema so that
the GUI and CLI never need hardcoded field lists or option enumerations.
Controlled vocabularies (WorkplaceType, EmploymentType, BrowserType, etc.)
are read directly from the schema, so adding a new option to the model
automatically appears in all UIs.

Example:
    >>> from auto_apply.application.services.ui_schema import build_ui_schema
    >>> from auto_apply.domain.models.profile import UserProfile
    >>> fields = build_ui_schema(UserProfile, "en")
    >>> len(fields) >= 25
    True
    >>> fields[0].label
    'Profile Name'
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from auto_apply.application.services.i18n import configure_locale, get_text


FieldKind = Literal["text", "number", "select", "multiselect", "path", "bool", "email", "url"]


@dataclass(frozen=True)
class UIField:
    """Descriptor for a single editable profile field.

    Attributes:
        key: Dot-separated path into UserProfile (e.g. "personal_info.first_name").
        label: Human-readable label, already resolved for the requested locale.
        help: Optional description or hint string.
        kind: Widget type hint for GUI/CLI renderers.
        options: Tuple of allowed values for select/multiselect fields, else None.
        min: Minimum numeric value or string length (if constrained).
        max: Maximum numeric value or string length (if constrained).
        required: True if the field must have a value.
    """

    key: str
    label: str
    help: str
    kind: FieldKind
    options: tuple[str, ...] | None
    min: float | None
    max: float | None
    required: bool


# Fields whose names suggest they hold filesystem paths.
_PATH_FIELD_NAMES: frozenset[str] = frozenset({"resume_path", "cover_letter"})

# Fields whose names suggest they hold URLs.
_URL_FIELD_NAMES: frozenset[str] = frozenset({
    "linkedin_url", "github_url", "portfolio_url",
})


def build_ui_schema(
    profile_cls: type[BaseModel],
    locale: str = "en",
) -> list[UIField]:
    """Builds a flat list of UIField descriptors from a Pydantic model's JSON schema.

    Walks the model's properties (including nested sub-models) and creates one
    UIField per leaf field. Enum-typed fields have their options populated from
    the schema; array fields with enum items become multiselect fields.

    Args:
        profile_cls: A Pydantic BaseModel subclass (typically UserProfile).
        locale: ISO 639-1 language code for label resolution.

    Returns:
        List of UIField objects, one per renderable leaf field.
    """
    configure_locale(language=locale)
    schema = profile_cls.model_json_schema()
    defs = schema.get("$defs", {})

    fields: list[UIField] = []
    _walk_properties(
        properties=schema.get("properties", {}),
        required_set=set(schema.get("required", [])),
        defs=defs,
        prefix="",
        fields=fields,
    )
    return fields


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────

def _walk_properties(
    properties: dict[str, Any],
    required_set: set[str],
    defs: dict[str, Any],
    prefix: str,
    fields: list[UIField],
) -> None:
    """Recursively walks schema properties and appends UIField objects."""
    for prop_name, prop_schema in properties.items():
        key = f"{prefix}{prop_name}" if prefix else prop_name
        resolved = _resolve_ref(prop_schema, defs)

        if resolved.get("type") == "object" or "$ref" in prop_schema:
            # Nested sub-model — recurse.
            sub_required = set(resolved.get("required", []))
            sub_props = resolved.get("properties", {})
            if sub_props:
                _walk_properties(sub_props, sub_required, defs, f"{key}.", fields)
                continue

        field = _make_field(key, prop_name, prop_schema, resolved, required_set)
        if field is not None:
            fields.append(field)


def _make_field(
    key: str,
    prop_name: str,
    raw_schema: dict[str, Any],
    resolved: dict[str, Any],
    required_set: set[str],
) -> UIField | None:
    """Converts a single resolved schema property into a UIField."""
    kind, options = _classify_field(prop_name, resolved)
    if kind is None:
        return None

    title = resolved.get("title") or raw_schema.get("title") or _snake_to_title(prop_name)
    description = resolved.get("description") or raw_schema.get("description") or ""

    # Attempt i18n resolution — fall back to title.
    label = _try_get_text(prop_name) or title

    min_val = resolved.get("minimum") or resolved.get("minLength")
    max_val = resolved.get("maximum") or resolved.get("maxLength")

    return UIField(
        key=key,
        label=label,
        help=description,
        kind=kind,
        options=options,
        min=float(min_val) if min_val is not None else None,
        max=float(max_val) if max_val is not None else None,
        required=prop_name in required_set,
    )


def _classify_field(
    prop_name: str,
    schema: dict[str, Any],
) -> tuple[FieldKind | None, tuple[str, ...] | None]:
    """Returns (kind, options) for a resolved schema property."""
    # anyOf — typically nullable wrappers; unwrap to the non-null variant.
    if "anyOf" in schema:
        non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
        if non_null:
            return _classify_field(prop_name, non_null[0])
        return None, None

    schema_type = schema.get("type")
    enum_vals = schema.get("enum")
    fmt = schema.get("format", "")

    # Enum → select
    if enum_vals:
        return "select", tuple(str(v) for v in enum_vals)

    # Array — may be multiselect if items have enum, else skip.
    if schema_type == "array":
        items = schema.get("items", {})
        item_enum = items.get("enum") or (
            items.get("anyOf", [{}])[0].get("enum") if items.get("anyOf") else None
        )
        if item_enum:
            return "multiselect", tuple(str(v) for v in item_enum)
        # Free-text list (e.g. desired_job_titles) → text
        return "text", None

    if schema_type == "boolean":
        return "bool", None

    if schema_type in ("integer", "number"):
        return "number", None

    if schema_type == "string":
        if prop_name in _PATH_FIELD_NAMES:
            return "path", None
        if prop_name in _URL_FIELD_NAMES or fmt in ("uri", "url"):
            return "url", None
        if fmt == "email":
            return "email", None
        return "text", None

    # Object fields that aren't $refs (rare) — skip
    if schema_type == "object":
        return None, None

    return "text", None


def _resolve_ref(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Follows a $ref one level deep into $defs."""
    ref = schema.get("$ref", "")
    if ref.startswith("#/$defs/"):
        name = ref.split("/")[-1]
        return defs.get(name, schema)
    return schema


def _snake_to_title(name: str) -> str:
    """Converts snake_case to Title Case for use as a fallback label."""
    return name.replace("_", " ").title()


def _try_get_text(key: str) -> str | None:
    """Attempts to find an i18n translation for a field name; returns None on miss."""
    # Try common namespaces in priority order.
    for ns in ("wizard", "settings", "profile", "gui"):
        full_key = f"{ns}.field_{key}"
        result = get_text(full_key)
        if result != full_key:  # service returns the key itself on miss
            return result
    return None