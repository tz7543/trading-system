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
        min_dte: int | None = None,
        margin_cushion: float | None = None,
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

        if min_dte is not None:
            if min_dte <= 3:
                alerts.append(
                    AlertEvent(
                        message=f"CRITICAL gamma risk: {min_dte} DTE remaining, close short options near ATM",
                        value=float(min_dte),
                        timestamp=now,
                    )
                )
            elif min_dte <= 7:
                alerts.append(
                    AlertEvent(
                        message=f"WARNING: elevated gamma risk at {min_dte} DTE",
                        value=float(min_dte),
                        timestamp=now,
                    )
                )
            elif min_dte <= 14:
                alerts.append(
                    AlertEvent(
                        message=f"Approaching gamma risk zone: {min_dte} DTE",
                        value=float(min_dte),
                        timestamp=now,
                    )
                )

        if margin_cushion is not None:
            if margin_cushion < 0.02:
                alerts.append(
                    AlertEvent(
                        message=f"RED: margin emergency, cushion {margin_cushion:.1%}",
                        value=margin_cushion,
                        timestamp=now,
                    )
                )
            elif margin_cushion < 0.05:
                alerts.append(
                    AlertEvent(
                        message=f"ORANGE: margin critical, cushion {margin_cushion:.1%}",
                        value=margin_cushion,
                        timestamp=now,
                    )
                )
            elif margin_cushion < 0.10:
                alerts.append(
                    AlertEvent(
                        message=f"YELLOW: margin warning, cushion {margin_cushion:.1%}",
                        value=margin_cushion,
                        timestamp=now,
                    )
                )

        return alerts

    def should_circuit_break(
        self,
        portfolio_greeks: Greeks,
        equity: float,
        min_dte: int | None = None,
        margin_cushion: float | None = None,
    ) -> bool:
        self.update_equity(equity)
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            if drawdown > self._limits.max_drawdown:
                return True
        if abs(portfolio_greeks.delta) > self._limits.max_delta:
            return True
        if abs(portfolio_greeks.vega) > self._limits.max_vega:
            return True
        if min_dte is not None and min_dte <= 0:
            return True
        return margin_cushion is not None and margin_cushion < 0.02
