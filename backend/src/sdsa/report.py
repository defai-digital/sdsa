"""Privacy report builder (ADR-0001, ADR-0002)."""
from __future__ import annotations

from typing import Any


CLAIM_PHASE1 = (
    "Pseudonymized microdata with per-column local-DP noise where configured. "
    "This output is NOT dataset-level (ε,δ)-differentially private. "
    "Linkage attacks using auxiliary data may still succeed. "
    "k-anonymity bounds prosecutor re-identification risk to at most 1/k."
)


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
) -> dict[str, Any]:
    report = {
        "session_id": session_id,
        "claim": CLAIM_PHASE1,
        "schema": schema,
        "pii_suggestions": pii_suggestions,
        "policies_applied": policies_applied,
        "privacy": {
            "mechanism_per_column": dp_spent,
            "max_epsilon": max(dp_spent.values(), default=0.0),
            "delta": None,
            "composition_note": (
                "Per-column local-DP budgets are reported individually. "
                "They do not compose to a dataset-level ε guarantee."
            ),
        },
        "k_anonymity": kanon,
        "validation": validation,
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


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# SDSA Privacy Report — session `{report['session_id']}`")
    lines.append("")
    lines.append("## Claim")
    lines.append(report["claim"])
    lines.append("")
    lines.append("## k-Anonymity")
    k = report["k_anonymity"]
    lines.append(f"- k target: {k.get('k_target')}")
    lines.append(f"- k achieved: {k.get('k_achieved')}")
    lines.append(f"- rows suppressed: {k.get('rows_suppressed')} / {k.get('rows_total')} "
                 f"({k.get('suppression_ratio', 0):.2%})")
    lines.append(f"- prosecutor risk upper bound: {1 / max(k.get('k_achieved', 1), 1):.4f}")
    lines.append("")
    lines.append("## Differential Privacy (per-column)")
    priv = report["privacy"]
    if priv["mechanism_per_column"]:
        for col, eps in priv["mechanism_per_column"].items():
            lines.append(f"- `{col}`: Laplace, ε = {eps}")
    else:
        lines.append("- No DP noise applied.")
    lines.append(f"- max ε across columns: {priv['max_epsilon']}")
    lines.append(f"- {priv['composition_note']}")
    lines.append("")
    lines.append("## Policies applied")
    for p in report["policies_applied"]:
        qi = " (QI)" if p.get("is_quasi_identifier") else ""
        lines.append(f"- `{p['column']}`: {p['action']}{qi}")
    if "deterministic_mode" in report:
        lines.append("")
        lines.append("## Deterministic Mode")
        lines.append(f"- key name: `{report['deterministic_mode']['key_name']}`")
        lines.append(f"- {report['deterministic_mode']['warning']}")
    lines.append("")
    lines.append("## Validation summary")
    v = report["validation"]
    lines.append(f"- rows before → after: {v['rows_before']} → {v['rows_after']}")
    lines.append(f"- columns reported: {len(v['columns'])}")
    return "\n".join(lines)
