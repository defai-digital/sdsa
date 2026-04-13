"""Per-column privacy budget accountant (ADR-0002).

Tracks ε spent per column within a session. We explicitly do NOT claim
sequential composition gives a dataset-level ε — users see per-column
ε and max-over-columns ε, with the disclaimer in the report.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Accountant:
    spent: dict[str, float] = field(default_factory=dict)

    def charge(self, column: str, epsilon: float) -> None:
        if epsilon <= 0:
            raise ValueError("epsilon must be > 0")
        self.spent[column] = self.spent.get(column, 0.0) + epsilon

    def max_epsilon(self) -> float:
        return max(self.spent.values(), default=0.0)

    def snapshot(self) -> dict[str, float]:
        return dict(self.spent)
