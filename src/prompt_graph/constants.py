"""Controlled vocabularies taken verbatim from the legal-review-table-builder skill.

Every list here is copied from the skill's SKILL.md, references/evaluation.md,
references/platform-adaptation.md, or assets/evaluation-log-template.md. The server's
validation rules match these exactly. Do not paraphrase or extend them without
updating the skill first.
"""

from __future__ import annotations

# --- Fallback vocabulary (SKILL.md "Give absence and uncertainty distinct meanings") ---

FALLBACK_VOCABULARY: tuple[str, ...] = (
    "Not addressed",
    "Not stated",
    "Not applicable",
    "Incorporated terms",
    "Unable to determine",
)

# Synonyms the skill prohibits (SKILL.md and requirements §8).
FALLBACK_SYNONYMS: tuple[str, ...] = ("N/A", "None", "Unclear", "Silent", "Unknown", "TBD")

# Terms that may carry a qualifier after an em dash, in Free Response columns only.
QUALIFIER_TERMS: tuple[str, ...] = ("Unable to determine", "Incorporated terms")

# --- Native column types (platform-adaptation.md "Confirmed capabilities") ---

NATIVE_TYPES: tuple[str, ...] = (
    "Classify",
    "Date",
    "Currency",
    "Number",
    "Duration",
    "Verbatim",
    "FreeResponse",
)

# Aliases Claude may submit after reading an export; normalised to the canonical spelling.
NATIVE_TYPE_ALIASES: dict[str, str] = {
    "classify": "Classify",
    "classification": "Classify",
    "date": "Date",
    "currency": "Currency",
    "number": "Number",
    "numeric": "Number",
    "duration": "Duration",
    "verbatim": "Verbatim",
    "freeresponse": "FreeResponse",
    "free response": "FreeResponse",
    "free_response": "FreeResponse",
    "free-response": "FreeResponse",
    "text": "FreeResponse",
}

# Types in which `Not stated` is the silence state (SKILL.md).
TYPED_COLUMNS: frozenset[str] = frozenset({"Date", "Number", "Currency", "Duration"})

# --- Harvey limits (platform-adaptation.md "Harvey design defaults") ---

CHAR_LIMIT_HARD = 10_000
CHAR_LIMIT_ADVISORY = 6_000
MAX_DOCS_PER_GROUP = 25

# --- Column lifecycle (prompt-inventory-template.md) ---

COLUMN_STATUSES: tuple[str, ...] = ("draft", "testing", "verified", "retired")

# --- Staged design roles (platform-adaptation.md "When references and dependencies are supported") ---

COLUMN_ROLES: tuple[str, ...] = (
    "orientation",
    "extraction",
    "validation",
    "reconciliation",
    "human_review",
)
ROLE_RANK: dict[str, int] = {role: i for i, role in enumerate(COLUMN_ROLES)}

# --- Failure taxonomy (evaluation.md "Failure taxonomy"), in the skill's order ---

FAILURE_CLASSES: dict[str, str] = {
    "scope_leakage": "Scope leakage",
    "concept_conflation": "Concept conflation",
    "document_type_error": "Document-type error",
    "temporal_status_error": "Temporal-status error",
    "evidence_overstatement": "Evidence overstatement",
    "holder_direction_error": "Holder or direction error",
    "silence_uncertainty_error": "Silence/uncertainty error",
    "vocabulary_drift": "Vocabulary drift",
    "suppressed_value": "Suppressed value",
    "type_rejection": "Type rejection",
    "applicability_error": "Applicability error",
    "dependency_routing_error": "Dependency-routing error",
    "dead_reference": "Dead reference",
    "cascade_error": "Cascade error",
    "stale_dependent_error": "Stale-dependent error",
    "grouped_source_error": "Grouped-source error",
    "aggregation_error": "Aggregation error",
    "output_leakage": "Output leakage",
    "verbosity": "Verbosity",
}

# Alternate spellings Claude may submit from a log; normalised to the slug.
FAILURE_CLASS_ALIASES: dict[str, str] = {
    label.lower(): slug for slug, label in FAILURE_CLASSES.items()
} | {
    "scope-leakage": "scope_leakage",
    "document type error": "document_type_error",
    "temporal status error": "temporal_status_error",
    "holder/direction error": "holder_direction_error",
    "holder direction error": "holder_direction_error",
    "silence-uncertainty error": "silence_uncertainty_error",
    "silence uncertainty error": "silence_uncertainty_error",
    "dependency routing error": "dependency_routing_error",
    "dead-reference": "dead_reference",
    "suppressed-value": "suppressed_value",
    "type-rejection": "type_rejection",
    "stale dependent error": "stale_dependent_error",
    "grouped source error": "grouped_source_error",
}

# --- Error types (evaluation-log-template.md) ---

ERROR_TYPES: tuple[str, ...] = ("substantive", "evidentiary", "formatting")

# --- Test-set coverage dimensions (evaluation-log-template.md), in template order ---
# (key, label, requires_grouping)

COVERAGE_DIMENSIONS: tuple[tuple[str, str, bool], ...] = (
    ("document_types", "Each material document type", False),
    ("single_multi_subject", "Single-subject and multi-subject files", False),
    (
        "execution_states",
        "Signed, partially signed, unsigned, filed, and government-issued documents",
        False,
    ),
    ("amendments_compilations", "Amendments, restatements, compilations, and attachments", False),
    ("express", "Documents that expressly address the issue", False),
    ("silent", "Documents that are silent", False),
    ("incorporated", "Documents that incorporate external terms", False),
    ("defective", "Incomplete, illegible, or internally conflicting records", False),
    ("multiple_records", "Multiple records about the same underlying subject", False),
    ("upstream_fallbacks", "Each upstream fallback state reaching each dependent column", False),
    ("multi_hop", "Multi-hop dependency chains and a changed upstream result", False),
    ("conditional", "Conditional columns with the condition met and not met", False),
    ("locked_cells", "Locked and unlocked cells during selective reruns", False),
    (
        "grouped",
        "Grouped sets with consistent, complementary, and conflicting evidence",
        True,
    ),
)
COVERAGE_DIMENSION_KEYS: tuple[str, ...] = tuple(k for k, _, _ in COVERAGE_DIMENSIONS)

# --- Dependency kinds (requirements §6) ---

DEPENDENCY_KINDS: tuple[str, ...] = ("intra_table_ref", "cross_table_parameter", "advisory")

# --- Parameter status / binding sites (requirements §6) ---

PARAMETER_STATUSES: tuple[str, ...] = ("unresolved", "resolved", "contested")
BINDING_SITES: tuple[str, ...] = ("table_instructions", "column_prompt")

# --- Memo assertion kinds (requirements §9) ---

ASSERTION_KINDS: tuple[str, ...] = ("extraction", "judgment")

# --- Default firm standard, from the skill's Table Instructions pattern ---

DEFAULT_DATE_PATTERN = "YYYY-MM-DD"
DEFAULT_EVIDENCE_BOUNDARY = "current review unit only"
