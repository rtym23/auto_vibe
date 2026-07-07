from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List

from auto_vibe.config.settings import CostConfig


@dataclass
class IterationRecord:
    """Record of one iteration: tokens, time, cost."""

    iteration_num: int
    prompt_tokens: int
    completion_tokens: int
    elapsed_seconds: float
    model_name: str
    estimated_cost_usd: float


@dataclass
class CostCalculator:
    """AutoVibe session cost calculator.

    Tracks tokens, time and money per iteration,
    aggregates results and generates a human-readable report.
    """

    config: CostConfig
    records: List[IterationRecord] = field(default_factory=list)
    session_start: float = field(default_factory=time.time)

    def start_session(self) -> None:
        """Start a new session: clear records and fix start time."""
        self.records.clear()
        self.session_start = time.time()

    def record_iteration(
        self,
        iteration_num: int,
        prompt_tokens: int,
        completion_tokens: int,
        elapsed_seconds: float,
        model_name: str,
    ) -> IterationRecord:
        """Calculate cost and save iteration record.

        Formula: (prompt_tokens + completion_tokens) / 1000 * price_per_1k_tokens
        """
        estimated_cost_usd = (
            (prompt_tokens + completion_tokens) / 1000
            * self.config.price_per_1k_tokens
        )

        record = IterationRecord(
            iteration_num=iteration_num,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_seconds=elapsed_seconds,
            model_name=model_name,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.records.append(record)
        return record

    def get_total_cost(self) -> dict:
        """Return summary for the entire session.

        Returns:
            total_tokens — total number of tokens (prompt + completion)
            total_time — total execution time in seconds
            estimated_cost_usd — total estimated cost
            currency — currency from config
        """
        total_tokens = sum(
            r.prompt_tokens + r.completion_tokens for r in self.records
        )
        total_time = sum(r.elapsed_seconds for r in self.records)
        estimated_cost_usd = sum(r.estimated_cost_usd for r in self.records)

        return {
            "total_tokens": total_tokens,
            "total_time": round(total_time, 2),
            "estimated_cost_usd": round(estimated_cost_usd, 6),
            "currency": self.config.currency,
        }

    def get_iteration_breakdown(self) -> List[IterationRecord]:
        """Return list of all iteration records."""
        return list(self.records)

    def get_cost_per_iteration(self) -> float:
        """Return average cost per iteration."""
        if not self.records:
            return 0.0
        total = sum(r.estimated_cost_usd for r in self.records)
        return round(total / len(self.records), 6)

    def format_summary(self) -> str:
        """Generate human-readable session report."""
        totals = self.get_total_cost()
        currency = totals["currency"]
        avg_cost = self.get_cost_per_iteration()
        session_elapsed = round(time.time() - self.session_start, 2)

        lines = [
            "=" * 50,
            "  AutoVibe — Cost Summary",
            "=" * 50,
            f"  Iterations:       {len(self.records)}",
            f"  Total tokens:     {totals['total_tokens']:,}",
            f"  Total time:       {totals['total_time']:.2f} s",
            f"  Session duration: {session_elapsed:.2f} s",
            f"  Estimated cost:   {totals['estimated_cost_usd']:.6f} {currency}",
            f"  Avg cost/iter:    {avg_cost:.6f} {currency}",
        ]

        if self.records:
            lines.append("")
            lines.append("  Per-iteration breakdown:")
            lines.append("  " + "-" * 46)
            for rec in self.records:
                lines.append(
                    f"  #{rec.iteration_num:2d}  "
                    f"{rec.model_name:<20s}  "
                    f"{rec.prompt_tokens + rec.completion_tokens:>8,} tokens  "
                    f"{rec.elapsed_seconds:>7.2f} s  "
                    f"{rec.estimated_cost_usd:.6f} {currency}"
                )

        lines.append("=" * 50)
        return "\n".join(lines)
