from core.events import SignalEvent
from core.models import Greeks, Position, RiskLimits, ValidationResult


class PreTradeValidator:
    def __init__(self, risk_limits: RiskLimits) -> None:
        self._limits = risk_limits

    def validate(
        self,
        signal: SignalEvent,
        portfolio_greeks: Greeks,
        proposed_greeks: Greeks,
        positions: list[Position],
    ) -> ValidationResult:
        new_count = len(positions) + 1
        if new_count > self._limits.max_position_size:
            return ValidationResult(
                approved=False,
                reason=f"Position limit exceeded: {new_count} > {self._limits.max_position_size}",
            )

        new_delta = portfolio_greeks.delta + proposed_greeks.delta
        if abs(new_delta) > self._limits.max_delta:
            return ValidationResult(
                approved=False,
                reason=f"Delta limit exceeded: {new_delta:.2f} > +/-{self._limits.max_delta}",
            )

        new_vega = portfolio_greeks.vega + proposed_greeks.vega
        if abs(new_vega) > self._limits.max_vega:
            return ValidationResult(
                approved=False,
                reason=f"Vega limit exceeded: {new_vega:.2f} > +/-{self._limits.max_vega}",
            )

        return ValidationResult(approved=True)
