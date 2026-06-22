"""Privacy report builder (ADR-0001, ADR-0002)."""
from __future__ import annotations

from typing import Any


CLAIM_PHASE1 = (
    "Pseudonymized microdata with per-column local-DP noise where configured. "
    "This output is NOT dataset-level (ε,δ)-differentially private. "
    "Linkage attacks using auxiliary data may still succeed. "
    "k-anonymity bounds prosecutor re-identification risk to at most 1/k."
)


def _shareable_schema(schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only source-schema metadata needed to audit policy choices.

    Upload responses expose full schema statistics to the operator before
    release. The exported privacy report travels with the sanitized data, so it
    should not include source-side cardinality, null counts, or numeric bounds.
    """
    allowed = {"name", "dtype", "kind"}
    return [{k: v for k, v in col.items() if k in allowed} for col in schema]


def _shareable_validation(validation: dict[str, Any]) -> dict[str, Any]:
    """Strip original (pre-sanitization) statistics from the validation block.

    The privacy report is exported alongside the sanitized CSV, so it must be
    safe to hand to the same downstream recipient. The `before` stats expose
    exact extremes (min/max), histogram edges, and the original joint
    distribution (`correlation_before`) of the *input* data — including the true
    tails of DP-noised columns, which would undermine the noise. We keep only
    `after` statistics, which describe the released data already present in the
    CSV, plus row counts (least-disclosure principle).
    """
    safe_columns = []
    for col in validation.get("columns", []):
        safe = {k: v for k, v in col.items()
                if k not in ("before", "before_histogram")}
        safe_columns.append(safe)
    return {
        "columns": safe_columns,
        "correlation_after": validation.get("correlation_after", {}),
        "rows_before": validation.get("rows_before"),
        "rows_after": validation.get("rows_after"),
    }


def _shareable_utility(utility: dict[str, Any] | None) -> dict[str, Any]:
    """Strip exact source-side utility inputs from exported reports."""
    if not utility:
        return {}
    safe = dict(utility)
    safe_columns: list[dict[str, Any]] = []
    for col in utility.get("columns", []):
        safe_columns.append({
            k: v for k, v in col.items()
            if k not in {"distinct_before", "noise_scale"}
        })
    safe["columns"] = safe_columns
    return safe


def build_report(
    *,
    session_id: str,
    schema: list[dict],
    pii_suggestions: dict[str, dict],
    policies_applied: list[dict],
    dp_spent: dict[str, float],
    kanon: dict[str, Any],
    validation: dict[str, Any],
    deterministic_key_name: str | None,
    utility: dict[str, Any] | None = None,
    dp_cumulative: dict[str, float] | None = None,
    epsilon_budget: float | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    report = {
        "session_id": session_id,
        "claim": CLAIM_PHASE1,
        "warnings": list(warnings or []),
        "schema": _shareable_schema(schema),
        "pii_suggestions": pii_suggestions,
        "policies_applied": policies_applied,
        "privacy": {
            "mechanism_per_column": dp_spent,
            "max_epsilon": max(dp_spent.values(), default=0.0),
            "cumulative_epsilon_per_column": dict(dp_cumulative or {}),
            "session_epsilon_budget": epsilon_budget,
            "delta": None,
            "composition_note": (
                "Per-column local-DP budgets are reported individually. "
                "They do not compose to a dataset-level ε guarantee. The "
                "cumulative budget is enforced per column across releases to "
                "prevent averaging attacks."
            ),
        },
        "k_anonymity": kanon,
        "utility": _shareable_utility(utility),
        "validation": _shareable_validation(validation),
    }
    if deterministic_key_name:
        report["deterministic_mode"] = {
            "key_name": deterministic_key_name,
            "warning": (
                "Outputs using the same key from this deployment will link. "
                "Do not share the key across trust boundaries. "
                "Deterministic pseudonymization is vulnerable to dictionary "
                "attacks if the attacker can guess input values."
            ),
        }
    return report


def _md_escape(s: str) -> str:
    """Escape markdown special characters in user-controlled strings."""
    for ch in ('\\', '`', '*', '_', '[', ']', '(', ')', '#', '|', '<', '>'):
        s = s.replace(ch, '\\' + ch)
    return s


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# SDSA Privacy Report — session `{report['session_id']}`")
    lines.append("")
    lines.append("## Claim")
    lines.append(report["claim"])
    lines.append("")
    warnings = report.get("warnings") or []
    if warnings:
        lines.append("## ⚠ Warnings")
        for w in warnings:
            lines.append(f"- {_md_escape(w)}")
        lines.append("")
    lines.append("## k-Anonymity")
    k = report["k_anonymity"]
    lines.append(f"- k target: {k.get('k_target')}")
    lines.append(f"- k achieved: {k.get('k_achieved')}")
    lines.append(f"- rows suppressed: {k.get('rows_suppressed')} / {k.get('rows_total')} "
                 f"({k.get('suppression_ratio', 0):.2%})")
    lines.append(f"- prosecutor risk upper bound: {1 / max(k.get('k_achieved', 1), 1):.4f}")
    ld = k.get("l_diversity") or {}
    if ld.get("sensitive_columns"):
        lines.append("")
        lines.append("## l-Diversity (attribute disclosure)")
        lines.append(f"- sensitive columns: "
                     f"{', '.join('`' + _md_escape(c) + '`' for c in ld['sensitive_columns'])}")
        lines.append(f"- l target: {ld.get('l_target')} "
                     f"({'enforced' if ld.get('enforced') else 'measured only'})")
        for col, l_val in (ld.get("l_achieved") or {}).items():
            homo = (ld.get("homogeneous_classes") or {}).get(col, 0)
            note = f" — {homo} homogeneous class(es)" if homo else ""
            lines.append(f"- `{_md_escape(col)}`: min distinct values per class = {l_val}{note}")
    lines.append("")
    lines.append("## Differential Privacy (per-column)")
    priv = report["privacy"]
    if priv["mechanism_per_column"]:
        for col, eps in priv["mechanism_per_column"].items():
            lines.append(f"- `{_md_escape(col)}`: Laplace, ε = {eps}")
    else:
        lines.append("- No DP noise applied.")
    lines.append(f"- max ε across columns: {priv['max_epsilon']}")
    lines.append(f"- {priv['composition_note']}")
    lines.append("")
    lines.append("## Policies applied")
    for p in report["policies_applied"]:
        qi = " (QI)" if p.get("is_quasi_identifier") else ""
        lines.append(f"- `{_md_escape(p['column'])}`: {p['action']}{qi}")
    if "deterministic_mode" in report:
        lines.append("")
        lines.append("## Deterministic Mode")
        lines.append(f"- key name: `{_md_escape(report['deterministic_mode']['key_name'])}`")
        lines.append(f"- {report['deterministic_mode']['warning']}")
    u = report.get("utility") or {}
    if u.get("columns_total"):
        lines.append("")
        lines.append("## Utility (information loss)")
        lines.append(f"- overall utility score: {u.get('overall_score')}/100")
        lines.append(f"- rows retained: {u.get('rows_after')} / {u.get('rows_before')} "
                     f"({u.get('row_retention', 0):.2%})")
        lines.append(f"- columns retained: {u.get('columns_kept')} / {u.get('columns_total')} "
                     f"({u.get('column_retention', 0):.2%})")
        lines.append(f"- mean kept-column fidelity: {u.get('mean_column_fidelity')}")
        lines.append("")
        lines.append("| Column | Action | Disposition | Released distinct values | Fidelity |")
        lines.append("|---|---|---|---|---|")
        for c in u.get("columns", []):
            after = c.get("distinct_after")
            after_str = "—" if after is None else str(after)
            lines.append(
                f"| `{_md_escape(c['column'])}` | {c.get('action')} "
                f"| {c.get('disposition')} | {after_str} | {c.get('fidelity')} |"
            )
        lines.append("")
        lines.append(f"> {u.get('method_note', '')}")
    lines.append("")
    lines.append("## Validation summary")
    v = report["validation"]
    lines.append(f"- rows before → after: {v['rows_before']} → {v['rows_after']}")
    lines.append(f"- columns reported: {len(v['columns'])}")
    return "\n".join(lines)
