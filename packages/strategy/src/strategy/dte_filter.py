from datetime import datetime


def days_to_expiry(expiry: str, now: datetime) -> int:
    exp_date = datetime.strptime(expiry, "%Y%m%d").date()
    return (exp_date - now.date()).days


def in_dte_window(
    expiry: str, now: datetime, min_dte: int = 30, max_dte: int = 45
) -> bool:
    return min_dte <= days_to_expiry(expiry, now) <= max_dte
