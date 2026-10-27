"""Monthly spend cap for AI calls. New research stops when the cap is reached."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from truecap.research.llm import Usage

# Rough upper bound for one fresh report, used to refuse a run that would cross the cap.
ESTIMATED_REPORT_INR = 25.0


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    cap_inr: float
    usd_to_inr: float
    spent_fn: Callable[[], float] = lambda: 0.0  # INR already spent this month
    record_fn: Callable[[Usage, float], None] = lambda usage, inr: None
    run_usage: list[Usage] = field(default_factory=list)

    def run_cost_inr(self) -> float:
        return sum(u.cost_usd() for u in self.run_usage) * self.usd_to_inr

    def ensure_room(self, estimate_inr: float = ESTIMATED_REPORT_INR) -> None:
        spent = self.spent_fn() + self.run_cost_inr()
        if spent + estimate_inr > self.cap_inr:
            raise BudgetExceeded(
                f"Monthly AI budget reached (₹{spent:,.0f} of ₹{self.cap_inr:,.0f}). "
                "Cached reports still open; new research resumes next month."
            )

    def record(self, usage: Usage) -> None:
        self.run_usage.append(usage)
        self.record_fn(usage, usage.cost_usd() * self.usd_to_inr)
