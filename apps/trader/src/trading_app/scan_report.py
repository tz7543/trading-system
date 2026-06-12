# apps/trader/src/trading_app/scan_report.py
"""Console table and JSON serialization for swing scan results."""

from __future__ import annotations

import dataclasses
from typing import Any

from strategy.swing.scanner import ScanResult

_VERDICT_ORDER = {"CANDIDATE": 0, "WATCH": 1, "REJECT": 2, "SKIP": 3}


def _round4(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {k: _round4(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round4(v) for v in value]
    return value


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def render_report(results: list[ScanResult]) -> str:
    ordered = sorted(results, key=lambda r: (_VERDICT_ORDER[r.verdict], r.symbol))
    lines = [
        f"{'SYMBOL':<8}{'VERDICT':<11}{'ENTRY':>9}{'STOP':>9}"
        f"{'T1':>9}{'RR':>7}{'SHARES':>8}  REASON"
    ]
    for r in ordered:
        reason = r.reasons[0] if r.reasons else ""
        shares = "-" if r.shares is None else str(r.shares)
        rr = "-" if r.rr is None else f"{r.rr:.2f}"
        lines.append(
            f"{r.symbol:<8}{r.verdict:<11}{_fmt(r.entry):>9}{_fmt(r.stop):>9}"
            f"{_fmt(r.t1):>9}{rr:>7}{shares:>8}  {reason}"
        )
    for r in ordered:
        if r.verdict not in ("CANDIDATE", "WATCH"):
            continue
        lines.append("")
        lines.append(f"== {r.symbol} ({r.verdict}) ==")
        lines.append(
            f"entry={_fmt(r.entry)} stop={_fmt(r.stop)} ({r.stop_basis}) "
            f"t1={_fmt(r.t1)}{' (fallback)' if r.t1_fallback else ''} "
            f"rr={'-' if r.rr is None else f'{r.rr:.2f}'} shares={r.shares}"
        )
        if r.confirmations:
            flags = " ".join(
                f"{name}={'✓' if ok else '✗'}" for name, ok in r.confirmations.items()
            )
            lines.append(f"confirmations: {flags}")
        if r.indicator_snapshot:
            snap = r.indicator_snapshot
            lines.append(
                f"gates: ADX={snap['adx']:.1f} atr_ratio={snap['atr_ratio']:.2f} "
                f"bb_width={snap['bb_width']:.4f} (p20={snap['bb_width_p20']:.4f})"
            )
        if r.exit_plan:
            lines.append(
                f"exit: 5MA={_fmt(r.exit_plan['ma5'])} "
                f"10MA={_fmt(r.exit_plan['ma10'])} 20MA={_fmt(r.exit_plan['ma20'])} "
                f"| {r.exit_plan['time_stop']}"
            )
        for reason in r.reasons:
            lines.append(f"note: {reason}")
        for item in r.manual_checklist:
            lines.append(f"manual: {item}")
    return "\n".join(lines)


def json_payload(results: list[ScanResult], *, generated_at: str) -> dict:
    return {
        "generated_at": generated_at,
        "results": [_round4(dataclasses.asdict(r)) for r in results],
    }
