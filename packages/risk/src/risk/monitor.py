from core.clock import Clock
from core.events import AlertEvent
from core.models import Greeks, RiskLimits


class RealTimeMonitor:
    def __init__(self, risk_limits: RiskLimits, clock: Clock) -> None:
        self._limits = risk_limits
        self._clock = clock
        self._peak_equity: float = 0.0

    def update_equity(self, equity: float) -> None:
        if equity > self._peak_equity:
            self._peak_equity = equity

    def check(
        self,
        portfolio_greeks: Greeks,
        equity: float,
    ) -> list[AlertEvent]:
        self.update_equity(equity)
        alerts: list[AlertEvent] = []
        now = self._clock.now()

        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            if drawdown > self._limits.max_drawdown:
                alerts.append(
                    AlertEvent(
                        message=f"Max drawdown exceeded: {drawdown:.2%}",
                        value=drawdown,
                        timestamp=now,
                    )
                )

        if abs(portfolio_greeks.delta) > self._limits.max_delta:
            alerts.append(
                AlertEvent(
                    message=f"Delta drift: {portfolio_greeks.delta:.2f} exceeds +/-{self._limits.max_delta}",
                    value=portfolio_greeks.delta,
                    timestamp=now,
                )
            )

        if abs(portfolio_greeks.vega) > self._limits.max_vega:
            alerts.append(
                AlertEvent(
                    message=f"Vega drift: {portfolio_greeks.vega:.2f} exceeds +/-{self._limits.max_vega}",
                    value=portfolio_greeks.vega,
                    timestamp=now,
                )
            )

        return alerts

    def should_circuit_break(
        self,
        portfolio_greeks: Greeks,
        equity: float,
    ) -> bool:
        self.update_equity(equity)
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            if drawdown > self._limits.max_drawdown:
                return True
        if abs(portfolio_greeks.delta) > self._limits.max_delta:
            return True
        return abs(portfolio_greeks.vega) > self._limits.max_vega
