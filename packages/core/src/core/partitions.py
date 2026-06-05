from pathlib import Path

from core.models import Contract


def tick_contract_dir(base_dir: str | Path, contract: Contract) -> Path:
    path = (
        Path(base_dir)
        / "ticks"
        / f"sec_type={contract.sec_type}"
        / f"symbol={contract.symbol}"
    )
    if contract.sec_type == "OPT":
        path = (
            path
            / f"expiry={contract.expiry}"
            / f"strike={contract.strike}"
            / f"right={contract.right}"
        )
    return path


def tick_partition_path(
    base_dir: str | Path, contract: Contract, date: str
) -> Path:
    return tick_contract_dir(base_dir, contract) / f"date={date}"
