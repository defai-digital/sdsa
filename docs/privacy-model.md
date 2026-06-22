# SDSA Privacy Model

## Overview

SDSA combines two privacy techniques for tabular data:

1. data obfuscation at the column level
2. bounded local differential privacy on selected numeric columns
3. k-anonymity enforcement on declared quasi-identifiers

That combination is meant for enterprise data-sharing workflows where teams
need something more rigorous than ad hoc masking, but do not want to pretend
they have full synthetic-data generation or dataset-level differential privacy.

The result is a governed sanitization pipeline:

- upload a tabular dataset
- review detected sensitive fields
- choose the transformation for each field
- preview the expected suppression impact
- export sanitized data with a machine-readable privacy report

## What "Data Obfuscation" Means In SDSA

SDSA uses "data obfuscation" in a precise engineering sense: transform raw
values so the exported dataset is safer to share while still retaining enough
shape for testing, QA, analytics, or external processing.

Supported obfuscation patterns include:

- `mask`: preserve part of a string and hide the rest
- `hash`: deterministic HMAC-based pseudonymization
- `tokenize`: deterministic token generation
- `redact`: replace with a constant marker
- `numeric_bin`: generalize continuous values into ranges
- `date_truncate`: reduce precision from full date to month or year
- `string_truncate`: keep a prefix and suppress the rest
- `drop`: remove the column entirely

This is different from encryption. Encryption is reversible for authorized
parties with the key. SDSA transformations are designed for release and
analysis workflows, not for restoring the original record later.

## Differential Privacy In SDSA

SDSA supports the Laplace mechanism on numeric columns when the operator
declares:

- `epsilon`
- `lower`
- `upper`

The implementation clamps inputs to the declared range, adds Laplace noise,
and clamps outputs again to the same range. That keeps the mechanism bounded
to the declared domain and prevents obviously invalid output values.

Important limit:

SDSA does **not** claim dataset-level `(epsilon, delta)` differential privacy.
The privacy report says this explicitly. In v1, differential privacy is
applied per selected column as a local perturbation step inside the pipeline.

That means:

- it can reduce exact value leakage on sensitive numeric fields
- it does not make the whole released dataset globally DP
- it does not eliminate linkage risk from auxiliary data

### Per-session DP budget

A single noisy release does not let an attacker recover the true value, but
several independent noisy releases of the *same* value do: averaging `N`
releases shrinks the noise by roughly `1/sqrt(N)`. To prevent this, SDSA tracks
cumulative epsilon **per column for the lifetime of an uploaded session** and
refuses any release that would push a column past
`SDSA_EPSILON_SESSION_BUDGET` (default: `SDSA_EPSILON_MAX`). Re-uploading the
data starts a fresh budget. The privacy report shows both the per-release
epsilon and the cumulative epsilon per column.

## k-Anonymity In SDSA

After per-column transformations, SDSA enforces k-anonymity on the fields the
operator marks as quasi-identifiers.

In this system, k-anonymity is suppression-based:

- records in equivalence classes smaller than `k` are removed
- zero-row output is refused
- high suppression can be blocked by soft and hard utility caps

This matters because many real failures in sanitization are not direct-ID
failures. They come from combinations like:

- city + postal code + birth month
- department + level + location
- membership tier + region + signup date

Even if names and emails are removed, those combinations can still isolate a
small group or a single person. k-anonymity is SDSA's guardrail against that
class of mistake.

### Attribute disclosure and l-diversity

k-anonymity bounds *identity* disclosure (re-identification) but not *attribute*
disclosure. If every record in an equivalence class shares the same value of a
sensitive ("label") column that is released in cleartext, an attacker learns
that value for everyone in the class without singling anyone out — the
homogeneity attack.

SDSA always **measures** this: for the columns left in cleartext (or those the
operator explicitly marks sensitive), the report records how many released
equivalence classes are homogeneous and the minimum number of distinct values
per class. When any homogeneous class exists and l-diversity is not enforced,
the report carries an explicit attribute-disclosure warning.

SDSA can also **enforce** distinct l-diversity: when the operator sets `l >= 2`,
equivalence classes with fewer than `l` distinct values in a sensitive column
are suppressed alongside the usual k-anonymity suppression (subject to the same
utility caps). Mask, generalize, or drop a column to remove it from the
cleartext attribute-disclosure surface entirely.

## How The Pieces Work Together

The SDSA model is:

1. detect sensitive columns
2. let the operator confirm or override treatment
3. apply non-DP obfuscation transforms
4. apply DP noise where configured (subject to the per-session DP budget)
5. enforce k-anonymity on quasi-identifiers (and l-diversity when configured)
6. report what was done, what guarantee is being claimed, and any residual
   attribute-disclosure warnings

This is intentional. The product is designed to be auditable and reviewable,
not opaque.

## Why This Is Useful For Enterprise Teams

Enterprise users usually need more than a one-line claim like "anonymized."
They need to answer practical questions:

- Which fields were changed?
- Which fields were treated as quasi-identifiers?
- Was noise applied, and with what epsilon?
- How much data was suppressed to reach the target k?
- What exactly can we claim to an internal reviewer, customer, or auditor?

SDSA is aimed at that workflow.

The enterprise value is in:

- explicit field-level policy
- repeatable defaults through `sdsa-policy.json`
- operator review instead of silent guessing
- bounded privacy parameters
- per-run privacy reporting
- self-hosted operation without shipping raw data to a third party

## What SDSA Does Not Promise

SDSA should not be described as:

- "fully anonymous by default"
- "dataset-level differential privacy"
- "safe against every linkage attack"
- "synthetic data generation"
- "lossless privacy"

Those claims would overstate the current system.

The more accurate position is:

SDSA is an enterprise-oriented privacy control for tabular data release. It
combines deterministic obfuscation, optional bounded local DP noise, and
k-anonymity enforcement with explicit policy review and audit reporting.

## Recommended Product Language

Short version for the README or product page:

> SDSA is a self-hosted data sanitization system for enterprise tabular
> datasets. It combines field-level obfuscation, bounded differential privacy
> for selected numeric fields, and k-anonymity enforcement, then produces a
> privacy report that states exactly what guarantee is being claimed.

Short version for internal sales or solutioning:

> SDSA is built for enterprise-controlled data sharing. It gives operators
> explicit privacy controls, utility guardrails, and auditable outputs without
> pretending every release has full dataset-level differential privacy.

## Related Files

- [README.md](../README.md)
- [QUICKSTART.md](../QUICKSTART.md)
- [sdsa-policy.default.json](../sdsa-policy.default.json)
- [sdsa-policy.json.example](../sdsa-policy.json.example)
