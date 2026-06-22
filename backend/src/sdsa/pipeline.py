"""End-to-end pipeline orchestration.

Order:
  1. apply non-DP policies (mask/hash/tokenize/redact/generalize/drop)
  2. apply DP Laplace where configured
  3. enforce k-anonymity over the declared QI columns
  4. compute before/after validation
  5. build privacy report
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import polars as pl
from pydantic import BaseModel, Field

from .anonymize.policy import ColumnPolicy, PolicyApplicationError, apply_policy
from .core.config import get_config
from .dp.accountant import Accountant
from .dp.laplace import LaplaceParams, apply_laplace
from .kanon.enforce import enforce_k
from .report import build_report
from .validate.metrics import build_validation


class ProcessRequest(BaseModel):
    policies: list[ColumnPolicy] = Field(..., max_length=500)
    k: int = Field(default=5, ge=2, le=1000)
    dp_params: dict[str, dict] = Field(default_factory=dict)
    # dp_params: {column_name: {"epsilon": float, "lower": float, "upper": float}}
    deterministic_key_name: str | None = Field(default=None, min_length=1, max_length=256)
    accept_weaker_guarantee: bool = False
    # Distinct l-diversity over sensitive ("label") columns. l=1 disables
    # enforcement but homogeneity is still measured and reported. When
    # sensitive_columns is empty, the cleartext non-QI columns are used as the
    # attribute-disclosure surface for both measurement and (l>=2) enforcement.
    sensitive_columns: list[str] = Field(default_factory=list, max_length=500)
    l: int = Field(default=1, ge=1, le=1000)


@dataclass
class ProcessResult:
    df: pl.DataFrame
    report: dict[str, Any]
    # Cumulative per-column DP budget (prior + this run) for the caller to
    # persist on the session so it survives across releases.
    dp_spent_cumulative: dict[str, float] = field(default_factory=dict)


class PipelineError(ValueError):
    pass


def _qi_cardinality_report(df: pl.DataFrame, qi_cols: list[str]) -> str:
    """Return a short human-readable summary of per-QI cardinality, worst first."""
    rows: list[tuple[str, int, int]] = []
    n = df.height
    for c in qi_cols:
        if c in df.columns:
            rows.append((c, int(df[c].n_unique()), n))
    rows.sort(key=lambda r: r[1], reverse=True)
    parts = [f"'{c}' ({u}/{n} unique)" for c, u, _ in rows]
    return ", ".join(parts) if parts else "(none)"


def _zero_rows_message(df: pl.DataFrame, qi_cols: list[str], k: int) -> str:
    if not qi_cols:
        return (
            f"k-anonymity enforcement produced zero rows with k={k} "
            f"but no QI columns were declared. This indicates an internal "
            f"error — please report."
        )
    return (
        f"All {df.height} rows were suppressed: no equivalence class of "
        f"size >= k={k} exists under the chosen QIs. "
        f"QI columns by cardinality (worst first): "
        f"{_qi_cardinality_report(df, qi_cols)}. "
        f"Fix by (a) unchecking high-cardinality QIs, "
        f"(b) generalizing them further (broader bins, year-only dates, "
        f"shorter string prefixes), or (c) lowering k."
    )


def _high_suppression_message(
    df: pl.DataFrame, qi_cols: list[str], k: int,
    suppression: float, cap: float,
) -> str:
    return (
        f"k={k} requires suppressing {suppression:.1%} of rows "
        f"(soft cap: {cap:.0%}). "
        f"QI columns by cardinality (worst first): "
        f"{_qi_cardinality_report(df, qi_cols)}. "
        f"To proceed: either reduce suppression by unchecking high-cardinality "
        f"QIs or generalizing them further, OR enable "
        f"\"Allow >{cap:.0%} row suppression\" and re-run. "
        f"Zero-row output is always refused."
    )


def _hard_suppression_message(
    df: pl.DataFrame, qi_cols: list[str], k: int,
    suppression: float, cap: float,
) -> str:
    return (
        f"k={k} would suppress {suppression:.1%} of rows, exceeding the hard "
        f"utility cap of {cap:.0%}. "
        f"QI columns by cardinality (worst first): "
        f"{_qi_cardinality_report(df, qi_cols)}. "
        f"This output is refused even with accept_weaker_guarantee=true. "
        f"Reduce the QI set, generalize high-cardinality fields, or lower k."
    )


def _derive_deterministic_key(key_name: str, deployment_salt: bytes) -> bytes:
    """Deploy-salt-scoped HMAC key derivation for deterministic mode (ADR-0008).

    Two invocations with the same (deployment_salt, key_name) produce the
    same 32-byte key → same hashes/tokens across sessions. Two different
    deployments with the same key_name get different keys (because salts
    differ), preserving the deployment-level trust boundary.
    """
    import hashlib
    import hmac as _hmac
    return _hmac.new(
        deployment_salt,
        b"sdsa-det-v1|" + key_name.encode("utf-8"),
        hashlib.sha256,
    ).digest()


# Actions that remove or obscure a column's true value. Anything NOT in this
# set leaves the original value readable in the output, making it part of the
# attribute-disclosure ("label leakage") surface.
_HIDING_ACTIONS = frozenset({
    "mask", "hash", "tokenize", "redact",
    "numeric_bin", "date_truncate", "string_truncate",
    "dp_laplace", "drop",
})


def resolve_sensitive_columns(
    df_columns: list[str],
    policies: list[ColumnPolicy],
    qi_columns: list[str],
    declared: list[str],
) -> list[str]:
    """Determine which columns to treat as sensitive for l-diversity.

    If the caller declared sensitive columns explicitly, use those after
    removing QIs, missing columns, and columns whose policy hides the true
    value. Otherwise default to the columns that remain in cleartext in the
    output — i.e. retained or untouched, non-QI columns — since those are
    exactly where attribute disclosure can happen.
    """
    qi_set = set(qi_columns)
    actions = {p.column: p.action for p in policies}
    def is_cleartext_column(c: str) -> bool:
        return (
            c in df_columns
            and c not in qi_set
            and actions.get(c, "retain") not in _HIDING_ACTIONS
        )

    if declared:
        return [c for c in dict.fromkeys(declared) if is_cleartext_column(c)]
    return [c for c in df_columns if is_cleartext_column(c)]


def run_pipeline(
    original: pl.DataFrame,
    request: ProcessRequest,
    session_id: str,
    hmac_key: bytes,
    schema: list[dict],
    pii_suggestions: dict[str, dict],
    *,
    prior_dp_spent: dict[str, float] | None = None,
    epsilon_budget: float | None = None,
) -> ProcessResult:
    cfg = get_config()
    df = original.clone()
    accountant = Accountant()
    policies_applied: list[dict] = []

    dp_columns = {p.column for p in request.policies if p.action == "dp_laplace"}
    if request.deterministic_key_name and dp_columns:
        raise PipelineError(
            "Deterministic mode cannot be combined with DP columns (ADR-0008)."
        )
    if request.deterministic_key_name and cfg.deployment_salt_is_ephemeral:
        raise PipelineError(
            "Deterministic mode requires SDSA_DEPLOYMENT_SALT to be set."
        )

    # Deterministic mode: override the session-random hmac_key with a key
    # derived from (deployment_salt, user-supplied key name). Without this,
    # the `deterministic_key_name` request field was silently ignored and
    # every session produced different tokens — breaking the one real
    # use case of deterministic mode (joinable pseudonyms across exports).
    if request.deterministic_key_name:
        hmac_key = _derive_deterministic_key(
            request.deterministic_key_name, cfg.deployment_salt
        )

    # 1. non-DP transforms
    for p in request.policies:
        try:
            df = apply_policy(df, p, hmac_key)
        except PolicyApplicationError as e:
            raise PipelineError(str(e)) from e
        policies_applied.append({
            "column": p.column,
            "action": p.action,
            "params": p.params,
            "is_quasi_identifier": p.is_quasi_identifier,
        })

    # 2. DP pass
    for col in dp_columns:
        if col not in df.columns:
            continue
        params = request.dp_params.get(col)
        if not params or "epsilon" not in params:
            raise PipelineError(
                f"DP requested for column '{col}' without epsilon/bounds"
            )
        try:
            eps = float(params["epsilon"])
        except (TypeError, ValueError) as e:
            raise PipelineError(f"epsilon for '{col}' must be numeric") from e
        if not (cfg.epsilon_min <= eps <= cfg.epsilon_max):
            raise PipelineError(
                f"epsilon for '{col}' ({eps}) outside allowed range "
                f"[{cfg.epsilon_min}, {cfg.epsilon_max}]"
            )
        if "lower" not in params or "upper" not in params:
            raise PipelineError(
                f"DP column '{col}' needs declared bounds (lower, upper)"
            )
        if not df[col].dtype.is_numeric():
            raise PipelineError(
                f"column '{col}' has dtype {df[col].dtype}; dp_laplace requires "
                f"a numeric column"
            )
        try:
            lp = LaplaceParams(
                epsilon=eps,
                lower=float(params["lower"]),
                upper=float(params["upper"]),
            )
        except (TypeError, ValueError) as e:
            raise PipelineError(f"DP bounds for '{col}' must be numeric") from e
        try:
            noised = apply_laplace(df[col], lp)
        except ValueError as e:
            raise PipelineError(f"invalid DP params for '{col}': {e}") from e
        df = df.with_columns(noised.alias(col))
        accountant.charge(col, eps)

    # 2b. DP budget enforcement (fail before producing any output).
    # Cumulative per-column ε = budget already spent in prior releases of this
    # session + what this run would spend. Refuse if any column exceeds the
    # budget — otherwise repeated independent noisy releases of the same data
    # could be averaged to recover the true value.
    this_run_spent = accountant.snapshot()
    dp_cumulative = dict(prior_dp_spent or {})
    for col, eps in this_run_spent.items():
        dp_cumulative[col] = dp_cumulative.get(col, 0.0) + eps
    if epsilon_budget is not None:
        over = sorted(c for c, v in dp_cumulative.items() if v > epsilon_budget + 1e-9)
        if over:
            detail = ", ".join(f"'{c}' (ε={dp_cumulative[c]:g})" for c in over)
            raise PipelineError(
                f"DP privacy budget exhausted for column(s): {detail}. "
                f"Cumulative ε across releases would exceed the per-column "
                f"session budget of {epsilon_budget:g}. Repeated noisy releases "
                f"of the same data enable averaging attacks, so this release is "
                f"refused. Re-upload the data to start a fresh budget."
            )

    # 3. k-anonymity (+ optional l-diversity over sensitive columns)
    # dict.fromkeys preserves order while deduplicating — duplicate QI entries
    # from the same column would cause a Polars DuplicateError in group_by.
    qi_cols = list(dict.fromkeys(
        p.column for p in request.policies
        if p.is_quasi_identifier and p.column in df.columns
    ))
    sensitive_cols = resolve_sensitive_columns(
        df.columns, request.policies, qi_cols, request.sensitive_columns
    )
    k_result = enforce_k(
        df, qi_cols, request.k,
        sensitive_columns=sensitive_cols, l=request.l,
    )

    # Always refuse zero-row output — an empty dataset is never a useful result,
    # regardless of the accept_weaker_guarantee flag.
    if k_result.df.height == 0:
        raise PipelineError(_zero_rows_message(df, qi_cols, request.k))

    if k_result.suppression_ratio > cfg.hard_max_suppression_ratio:
        raise PipelineError(_hard_suppression_message(
            df, qi_cols, request.k, k_result.suppression_ratio,
            cfg.hard_max_suppression_ratio,
        ))

    if (k_result.suppression_ratio > cfg.max_suppression_ratio
            and not request.accept_weaker_guarantee):
        raise PipelineError(_high_suppression_message(
            df, qi_cols, request.k, k_result.suppression_ratio,
            cfg.max_suppression_ratio,
        ))
    df = k_result.df

    # 4. validation
    validation = build_validation(original, df)

    # 5. report
    kanon_report = {
        "k_target": request.k,
        "k_achieved": k_result.k_achieved,
        "rows_total": k_result.rows_total,
        "rows_suppressed": k_result.rows_suppressed,
        "suppression_ratio": k_result.suppression_ratio,
        "classes_total": k_result.classes_total,
        "classes_below_k": k_result.classes_below_k,
        "qi_columns": qi_cols,
        "l_diversity": {
            "sensitive_columns": k_result.sensitive_columns,
            "l_target": k_result.l_target,
            "l_achieved": k_result.l_achieved,
            "homogeneous_classes": k_result.homogeneous_classes,
            "classes_below_l": k_result.classes_below_l,
            "enforced": request.l >= 2,
        },
    }

    # Attribute-disclosure warning: when l-diversity is not being enforced and a
    # released equivalence class is homogeneous in a cleartext column, that
    # column's value leaks for everyone in the class (the "label leakage" the
    # k-anonymity guarantee does NOT cover).
    warnings: list[str] = []
    if request.l < 2 and k_result.sensitive_columns:
        leaky = sorted(c for c, n in k_result.homogeneous_classes.items() if n > 0)
        if leaky:
            warnings.append(
                "Attribute disclosure risk: one or more released equivalence "
                f"classes are homogeneous in cleartext column(s) {leaky}. "
                "k-anonymity does not prevent an attacker from learning these "
                "values for individuals in such a class. Mitigate by enabling "
                "l-diversity (l >= 2) on these columns, generalizing/masking "
                "them, or dropping them."
            )

    report = build_report(
        session_id=session_id,
        schema=schema,
        pii_suggestions=pii_suggestions,
        policies_applied=policies_applied,
        dp_spent=this_run_spent,
        dp_cumulative=dp_cumulative,
        epsilon_budget=epsilon_budget,
        kanon=kanon_report,
        validation=validation,
        deterministic_key_name=request.deterministic_key_name,
        warnings=warnings,
    )
    return ProcessResult(df=df, report=report, dp_spent_cumulative=dp_cumulative)
