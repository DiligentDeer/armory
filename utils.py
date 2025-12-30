from typing import Any

def calculate_rates(
    utilization: float,
    irm_info_or_kink: Any,
    base_rate: float | None = None,
    rate_at_kink: float | None = None,
    max_rate: float | None = None,
) -> tuple[float, float]:
    if isinstance(irm_info_or_kink, dict):
        kink = float(irm_info_or_kink.get("kinkPercent", 0) or 0)
        base_rate = float(irm_info_or_kink.get("baseRateApy", 0) or 0)
        rate_at_kink = float(irm_info_or_kink.get("rateAtKink", 0) or 0)
        max_rate = float(irm_info_or_kink.get("maximumRate", 0) or 0)
    else:
        kink = float(irm_info_or_kink or 0)
        if base_rate is None or rate_at_kink is None or max_rate is None:
            return 0.0, 0.0

    if utilization < 0:
        utilization = 0.0
    if utilization > 1:
        utilization = 1.0

    if utilization <= kink:
        if kink > 0:
            slope = (rate_at_kink - base_rate) / kink
            borrow_rate = base_rate + (slope * utilization)
        else:
            borrow_rate = base_rate
    else:
        if kink < 1:
            slope = (max_rate - rate_at_kink) / (1 - kink)
            borrow_rate = rate_at_kink + (slope * (utilization - kink))
        else:
            borrow_rate = rate_at_kink

    supply_rate = utilization * 0.9 * borrow_rate
    return borrow_rate, supply_rate

def calculate_max_leverage(borrowLTV: float) -> float:
    return 1.0 / (1.0 - borrowLTV)                                  

def calculate_yield_with_LTV(supply_rate: float, borrow_rate: float, borrowLTV: float) -> float:
    return (supply_rate - borrow_rate * borrowLTV) / (1.0 - borrowLTV)

def calculate_yield_with_leverage(supply_rate: float, borrow_rate: float, leverage: float) -> float:    
    return (leverage * (supply_rate - borrow_rate)) + borrow_rate
