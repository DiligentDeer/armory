from __future__ import annotations

from dataclasses import dataclass, field, fields
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from hexbytes import HexBytes
import requests
from web3 import Web3

from utils import calculate_rates, calculate_max_leverage, calculate_yield_with_LTV, calculate_yield_with_leverage


load_dotenv()

SECONDS_PER_YEAR = 31536000
SPY_SCALE = 10**27
UINT32_MAX = 4294967295

VAULT_LENS = "0xc3c45633e45041bf3be841f89d2cb51e2f657403"
RPC_URL = os.getenv("RPC_URL")
ABI_PATH = Path(__file__).with_name("vault_abi.json")
_ABI_CACHE: list[dict[str, Any]] | None = None


def _get_abi() -> list[dict[str, Any]]:
    global _ABI_CACHE
    if _ABI_CACHE is not None:
        return _ABI_CACHE
    with open(ABI_PATH, "r") as f:
        _ABI_CACHE = json.load(f)
    return _ABI_CACHE


def decode_primitive(data: Any) -> Any:
    if isinstance(data, HexBytes):
        return data.hex()
    if isinstance(data, bytes):
        return data.hex()
    return data


def map_to_schema(data: Any, components: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for i, component in enumerate(components):
        if i >= len(data):
            break
        name = component.get("name", "")
        type_str = component.get("type", "")
        value = data[i]

        if type_str == "tuple":
            result[name] = map_to_schema(value, component.get("components", []))
        elif type_str == "tuple[]":
            result[name] = [map_to_schema(item, component.get("components", [])) for item in value]
        else:
            result[name] = decode_primitive(value)
    return result


def fetch_vault_info(vault_address: str) -> Any:
    if not RPC_URL:
        raise RuntimeError("RPC_URL is not set")

    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        raise RuntimeError("Failed to connect to RPC")

    contract = w3.eth.contract(address=w3.to_checksum_address(VAULT_LENS), abi=_get_abi())
    if not w3.is_checksum_address(vault_address):
        vault_address = w3.to_checksum_address(vault_address)

    return contract.functions.getVaultInfoFull(vault_address).call()


def to_apy(rate_per_sec: int) -> float:
    r_decimal = rate_per_sec / SPY_SCALE
    if r_decimal == 0:
        return 0.0
    return ((1 + r_decimal) ** SECONDS_PER_YEAR) - 1


def decode_kink_params(hex_str: str) -> dict[str, Any]:
    if hex_str.startswith("0x"):
        hex_str = hex_str[2:]

    if len(hex_str) < 64 * 4:
        return {"error": "Insufficient params length"}

    chunks = [int(hex_str[i * 64 : (i + 1) * 64], 16) for i in range(4)]

    base_rate_raw = chunks[0]
    slope1_raw = chunks[1]
    slope2_raw = chunks[2]
    kink_raw = chunks[3]

    r0 = base_rate_raw
    r_kink = base_rate_raw + (slope1_raw * kink_raw)
    r_100 = r_kink + (slope2_raw * (UINT32_MAX - kink_raw))
    kink_util = kink_raw / UINT32_MAX

    return {
        "kinkPercent": round(kink_util * 100, 3),
        "baseRateApy": round(to_apy(r0) * 100, 3),
        "rateAtKink": round(to_apy(r_kink) * 100, 3),
        "maximumRate": round(to_apy(r_100) * 100, 3),
    }

def get_vault_info_json(vault_address: str) -> dict[str, Any]:
    raw_data = fetch_vault_info(vault_address)

    abi = _get_abi()
    fn_abi = next((x for x in abi if x.get("name") == "getVaultInfoFull"), None)
    if not fn_abi or "outputs" not in fn_abi or not fn_abi["outputs"]:
        raise RuntimeError("ABI missing getVaultInfoFull outputs")

    output_components = fn_abi["outputs"][0].get("components", [])
    data_to_map = raw_data
    if isinstance(raw_data, (list, tuple)) and len(raw_data) == 1 and isinstance(raw_data[0], (list, tuple)):
        data_to_map = raw_data[0]

    full_data = map_to_schema(data_to_map, output_components)

    vault_decimals = full_data.get("vaultDecimals", 0)
    scale_factor = 10 ** vault_decimals if vault_decimals else 1

    total_cash = round(full_data.get("totalCash", 0) / scale_factor, 2)
    total_borrowed = round(full_data.get("totalBorrowed", 0) / scale_factor, 2)
    total_assets = round(full_data.get("totalAssets", 0) / scale_factor, 2)
    supply_cap = round(full_data.get("supplyCap", 0) / scale_factor, 0)
    borrow_cap = round(full_data.get("borrowCap", 0) / scale_factor, 0)

    filtered: dict[str, Any] = {
        "timestamp": full_data.get("timestamp"),
        "vault": full_data.get("vault"),
        "vaultName": full_data.get("vaultName"),
        "vaultSymbol": full_data.get("vaultSymbol"),
        "vaultDecimals": full_data.get("vaultDecimals"),
        "asset": full_data.get("asset"),
        "assetName": full_data.get("assetName"),
        "assetSymbol": full_data.get("assetSymbol"),
        "assetDecimals": full_data.get("assetDecimals"),
        "totalCash": total_cash,
        "totalBorrowed": total_borrowed,
        "totalAssets": total_assets,
        "supplyCap": supply_cap,
        "borrowCap": borrow_cap,
        "interestRateModel": full_data.get("interestRateModel"),
        "interestRateModelInfo": {},
        "collateralLTVInfo": [],
    }

    irm_info = full_data.get("irmInfo", {}).get("interestRateModelInfo", {})
    irm_type = str(irm_info.get("interestRateModelType", ""))
    params_hex = irm_info.get("interestRateModelParams", "")
    if params_hex:
        if irm_type == "1":
            filtered["interestRateModelInfo"] = decode_kink_params(params_hex)
        elif not irm_type and len(params_hex) >= 2 + 64 * 4:
            filtered["interestRateModelInfo"] = decode_kink_params(params_hex)

    raw_ltv_info = full_data.get("collateralLTVInfo", [])
    if isinstance(raw_ltv_info, list):
        for item in raw_ltv_info:
            if not isinstance(item, dict):
                continue
            borrow_ltv = item.get("borrowLTV", 0) / 10000
            if borrow_ltv == 0:
                continue
            filtered["collateralLTVInfo"].append(
                {
                    "collateral": item.get("collateral"),
                    "borrowLTV": borrow_ltv,
                    "liquidationLTV": item.get("liquidationLTV", 0) / 10000,
                }
            )

    return filtered

def get_apy_by_pool_id(pool_id, field):
    """
    Get a specific APY field value from a DeFi Llama pool.
    
    Args:
        pool_id: The DeFi Llama pool UUID (e.g., "73e933a7-73b2-43ec-b1e9-d5d1d42ce2de")
        field: The field to extract (e.g., "apyReward", "apy", "apyBase")
    
    Returns:
        The numeric value of the specified field, or 0 if not found or if inputs are null/empty
    """
    # Return 0 if any input is null/None or empty string
    if not pool_id or not field:
        return 0
    
    try:
        url = "https://yields.llama.fi/pools"
        response = requests.get(url)
        response.raise_for_status()
        
        pools = response.json()['data']
        
        # Find the pool with matching pool_id
        pool_id = str(pool_id).strip()
        field = str(field).strip()
        matching_pool = next((pool for pool in pools if pool.get('pool') == pool_id), None)
        
        if matching_pool:
            # Return the field value, default to 0 if field doesn't exist or is None
            candidate_fields = [field]
            if field == "apyReward":
                candidate_fields.extend(["apy", "apyBase", "apyMean30d"])

            for f in candidate_fields:
                value = matching_pool.get(f)
                if value is None:
                    continue
                try:
                    return float(value)
                except Exception:
                    continue
            return 0
        else:
            return 0
            
    except Exception as e:
        print(f"Error fetching pool data: {e}")
        return 0

@dataclass
class Vault:
    vault_address: str
    defillama_pool: str | None = None
    defillama_field: str | None = None
    nativeYield: float = 0.0

    timestamp: int | None = None
    vault: str | None = None
    vault_name: str | None = None
    vault_symbol: str | None = None
    vault_decimals: int = 0

    asset: str | None = None
    asset_name: str | None = None
    asset_symbol: str | None = None
    asset_decimals: int = 0

    total_cash: float = 0.0
    total_borrowed: float = 0.0
    total_assets: float = 0.0
    supply_cap: float = 0.0
    borrow_cap: float = 0.0

    interest_rate_model: str | None = None
    interest_rate_model_info: dict[str, Any] = field(default_factory=dict)
    collateral_ltv_info: list[dict[str, Any]] = field(default_factory=list)

    current_utilization: float = 0.0
    utilization_at_caps: float = 0.0
    current_borrow_apy: float = 0.0
    current_supply_apy: float = 0.0
    caps_borrow_apy: float = 0.0
    caps_supply_apy: float = 0.0

    error: str | None = None
    fetched: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.vault_address = str(self.vault_address).strip()
        self.defillama_pool = str(self.defillama_pool).strip() if self.defillama_pool is not None else None
        self.defillama_field = str(self.defillama_field).strip() if self.defillama_field is not None else None
        try:
            self.refresh()
        except Exception as e:
            self.error = str(e)
            self.fetched = False

    def compute_derived_fields(self) -> None:
        self.current_utilization = 0.0
        if self.total_assets > 0:
            self.current_utilization = round((self.total_borrowed / self.total_assets) * 100, 3)

        self.utilization_at_caps = 0.0
        if self.supply_cap > 0:
            self.utilization_at_caps = round((self.borrow_cap / self.supply_cap) * 100, 3)

        if self.interest_rate_model_info and "kinkPercent" in self.interest_rate_model_info:
            # Create 0-1 scaled version for calculation, as params are stored in 0-100 scale
            irm_scaled = {
                "kinkPercent": float(self.interest_rate_model_info.get("kinkPercent", 0) or 0) / 100,
                "baseRateApy": float(self.interest_rate_model_info.get("baseRateApy", 0) or 0) / 100,
                "rateAtKink": float(self.interest_rate_model_info.get("rateAtKink", 0) or 0) / 100,
                "maximumRate": float(self.interest_rate_model_info.get("maximumRate", 0) or 0) / 100,
            }
            borrow_apy, supply_apy = calculate_rates(
                self.current_utilization / 100, irm_scaled
            )
            self.current_borrow_apy = round(borrow_apy * 100, 3)
            self.current_supply_apy = round(supply_apy * 100, 3)

            caps_borrow_apy, caps_supply_apy = calculate_rates(
                self.utilization_at_caps / 100, irm_scaled
            )
            self.caps_borrow_apy = round(caps_borrow_apy * 100, 3)
            self.caps_supply_apy = round(caps_supply_apy * 100, 3)
        else:
            self.current_borrow_apy = 0.0
            self.current_supply_apy = 0.0
            self.caps_borrow_apy = 0.0
            self.caps_supply_apy = 0.0

    def refresh(self) -> None:
        data = get_vault_info_json(self.vault_address)
        self.raw = dict(data) if isinstance(data, dict) else {"value": data}

        self.timestamp = self._as_int(data.get("timestamp"))
        self.vault = self._as_str(data.get("vault"))
        self.vault_name = self._as_str(data.get("vaultName"))
        self.vault_symbol = self._as_str(data.get("vaultSymbol"))
        self.vault_decimals = self._as_int(data.get("vaultDecimals")) or 0

        self.asset = self._as_str(data.get("asset"))
        self.asset_name = self._as_str(data.get("assetName"))
        self.asset_symbol = self._as_str(data.get("assetSymbol"))
        self.asset_decimals = self._as_int(data.get("assetDecimals")) or 0

        self.total_cash = self._as_float(data.get("totalCash"))
        self.total_borrowed = self._as_float(data.get("totalBorrowed"))
        self.total_assets = self._as_float(data.get("totalAssets"))
        self.supply_cap = self._as_float(data.get("supplyCap"))
        self.borrow_cap = self._as_float(data.get("borrowCap"))

        self.interest_rate_model = self._as_str(data.get("interestRateModel"))
        irm_info = data.get("interestRateModelInfo")
        self.interest_rate_model_info = dict(irm_info) if isinstance(irm_info, dict) else {}

        ltv_info = data.get("collateralLTVInfo")
        self.collateral_ltv_info = list(ltv_info) if isinstance(ltv_info, list) else []
        self.compute_derived_fields()

        self.nativeYield = round(float(get_apy_by_pool_id(self.defillama_pool, self.defillama_field) or 0.0), 3)

        self.error = None
        self.fetched = True

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "vault": self.vault,
            "vaultName": self.vault_name,
            "vaultSymbol": self.vault_symbol,
            "vaultDecimals": self.vault_decimals,
            "asset": self.asset,
            "assetName": self.asset_name,
            "assetSymbol": self.asset_symbol,
            "assetDecimals": self.asset_decimals,
            "totalCash": self.total_cash,
            "totalBorrowed": self.total_borrowed,
            "totalAssets": self.total_assets,
            "supplyCap": self.supply_cap,
            "borrowCap": self.borrow_cap,
            "interestRateModel": self.interest_rate_model,
            "interestRateModelInfo": self.interest_rate_model_info,
            "collateralLTVInfo": self.collateral_ltv_info,
            "currentUtilization": self.current_utilization,
            "utilizationAtCaps": self.utilization_at_caps,
            "currentBorrowApy": self.current_borrow_apy,
            "currentSupplyApy": self.current_supply_apy,
            "capsBorrowApy": self.caps_borrow_apy,
            "capsSupplyApy": self.caps_supply_apy,
        }

    @staticmethod
    def _as_str(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return str(value)

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _as_float(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except Exception:
            return 0.0
