"""Adaptive degradation mode logic."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    name: str
    size_mult: float
    confidence_bonus: float
    exhaustion_bonus: float
    active_strategies: tuple[str, ...]


LEVELS = {
    0: Level("NORMAL", 1.0, 0.0, 0.0, ("ORACLE_ARB", "CROSS_ASSET_LAG", "EXHAUSTION_SNIPER", "MOMENTUM_RIDER", "MEAN_REVERSION")),
    1: Level("REDUCED", 0.70, 0.03, 0.3, ("ORACLE_ARB", "CROSS_ASSET_LAG", "EXHAUSTION_SNIPER", "MOMENTUM_RIDER", "MEAN_REVERSION")),
    2: Level("DEFENSIVE", 0.45, 0.06, 0.7, ("ORACLE_ARB", "CROSS_ASSET_LAG", "EXHAUSTION_SNIPER")),
    3: Level("SURVIVAL", 0.25, 0.10, 1.0, ("ORACLE_ARB",)),
}


class Degrader:
    """Determines active degradation level and profile."""

    def evaluate(self, consecutive_losses: int, drawdown_pct: float, win_rate_10: float) -> int:
        """Compute new level with auto-recovery signal."""
        level = 0
        if consecutive_losses >= 3 or drawdown_pct >= 0.10:
            level = 1
        if consecutive_losses >= 5 or drawdown_pct >= 0.15:
            level = 2
        if consecutive_losses >= 7 or drawdown_pct >= 0.18:
            level = 3

        if win_rate_10 >= 0.65 and consecutive_losses == 0 and level > 0:
            level -= 1
        return max(0, min(3, level))

    def profile(self, level: int) -> dict[str, float | str]:
        """Return sizing and threshold bonuses for current level."""
        lv = LEVELS.get(level, LEVELS[0])
        return {
            "name": lv.name,
            "size_mult": lv.size_mult,
            "confidence_bonus": lv.confidence_bonus,
            "exhaustion_bonus": lv.exhaustion_bonus,
            "active_strategies": list(lv.active_strategies),
        }
