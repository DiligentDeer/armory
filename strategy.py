from dataclasses import dataclass
from vault import Vault
from typing import Any

from utils import calculate_rates, calculate_max_leverage, calculate_yield_with_LTV, calculate_yield_with_leverage
 
@dataclass
class Strategy:
    debtVault: Vault
    collateralVault: Vault
    borrowLTV: float
    liquidationLTV: float
    strategy_name: str = ""

    def __post_init__(self) -> None:
        debt_symbol = self.debtVault.asset_symbol or self.debtVault.vault_symbol or self.debtVault.vault_address
        collateral_symbol = self.collateralVault.asset_symbol or self.collateralVault.vault_symbol or self.collateralVault.vault_address
        self.strategy_name = f"{debt_symbol} → {collateral_symbol}"

    def calculate_current_yield(self) -> float:
        gain = self.collateralVault.current_supply_apy + self.collateralVault.nativeYield
        cost = self.debtVault.current_borrow_apy

        yield_with_LTV = calculate_yield_with_LTV(gain, cost, self.borrowLTV)
        return yield_with_LTV

    def calculate_caps_yield(self) -> float:
        gain = self.collateralVault.caps_supply_apy + self.collateralVault.nativeYield
        cost = self.debtVault.caps_borrow_apy

        yield_with_LTV = calculate_yield_with_LTV(gain, cost, self.liquidationLTV)
        return yield_with_LTV

    def calculate_yield_with_utilization(self, debt_utilization: float, collateral_utilization: float) -> float:
        borrow_rate, _ = calculate_rates(debt_utilization, self.debtVault.interest_rate_model_info)
        _, supply_rate = calculate_rates(collateral_utilization, self.collateralVault.interest_rate_model_info)

        gain = supply_rate + self.collateralVault.nativeYield
        cost = borrow_rate

        yield_with_LTV = calculate_yield_with_LTV(gain, cost, self.borrowLTV)
        return yield_with_LTV


def construct_strategies(vault_object_map: dict[str, Vault]) -> list[dict[str, Any]]:
    strategies: list[dict[str, Any]] = []

    for vault_key, vault_obj in vault_object_map.items():
        debt_asset = getattr(vault_obj, "vault", None) or vault_key
        collateral_ltv_info = getattr(vault_obj, "collateralLTVInfo", None)
        if collateral_ltv_info is None:
            collateral_ltv_info = getattr(vault_obj, "collateral_ltv_info", [])

        if not isinstance(collateral_ltv_info, list):
            continue

        for item in collateral_ltv_info:
            if not isinstance(item, dict):
                continue
            strategies.append(
                {
                    "debtAsset": debt_asset,
                    "collateralAsset": item.get("collateral"),
                    "borrowLTV": item.get("borrowLTV"),
                    "liquidationLTV": item.get("liquidationLTV"),
                }
            )

    return strategies
