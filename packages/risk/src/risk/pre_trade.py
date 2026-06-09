from core.events import SignalEvent
from core.models import Greeks, MarginInfo, Position, RiskLimits, ValidationResult


class PreTradeValidator:
    def __init__(self, risk_limits: RiskLimits) -> None:
        self._limits = risk_limits

    def validate(
        self,
        signal: SignalEvent,
        portfolio_greeks: Greeks,
        proposed_greeks: Greeks,
        positions: list[Position],
        margin_info: MarginInfo | None = None,
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

        if margin_info is not None and margin_info.equity_with_loan > 0:
            utilization = margin_info.init_margin / margin_info.equity_with_loan
            if utilization > self._limits.max_margin_utilization:
                return ValidationResult(
                    approved=False,
                    reason=f"Margin utilization exceeded: {utilization:.1%} > {self._limits.max_margin_utilization:.1%}",
                )

        return ValidationResult(approved=True)
