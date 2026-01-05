from dataclasses import dataclass
from typing import Any

import plotly.graph_objects as go
import numpy as np

from vault import Vault
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

    def generate_simulation_chart(self):
        # Resolution for the heatmap
        steps = 101
        x = np.linspace(0, 1, steps)  # Collateral Utilization
        y = np.linspace(0, 1, steps)  # Debt Utilization
        
        z = []
        for d_util in y:
            row = []
            for c_util in x:
                yield_val = self.calculate_yield_with_utilization(debt_utilization=d_util, collateral_utilization=c_util)
                row.append(yield_val) # Already in percentage
            z.append(row)

        fig = go.Figure(data=go.Heatmap(
            z=z,
            x=x * 100, # Display as percentage
            y=y * 100, # Display as percentage
            colorscale='Viridis',
            zmin=5,
            zmax=25,
            colorbar=dict(title='Yield %'),
            hovertemplate='Collateral Util: %{x:.1f}%<br>Debt Util: %{y:.1f}%<br>Yield: %{z:.2f}%<extra></extra>'
        ))

        # Point 1: Current Utilization (from raw on-chain data)
        def get_raw_util(v: Vault) -> float:
            # Safely access raw dictionary
            if not v.raw: return 0.0
            assets = float(v.raw.get("totalAssets", 0))
            borrowed = float(v.raw.get("totalBorrowed", 0))
            if assets > 0:
                return (borrowed / assets) * 100
            return 0.0

        d_curr_real = get_raw_util(self.debtVault)
        c_curr_real = get_raw_util(self.collateralVault)

        # Point 3: Utilization at Caps (from assumption table)
        d_caps = self.debtVault.utilization_at_caps
        c_caps = self.collateralVault.utilization_at_caps

        # Trace 1: Current (Circle)
        fig.add_trace(go.Scatter(
            x=[c_curr_real], y=[d_curr_real],
            mode='markers',
            name='Current Util',
            marker=dict(symbol='circle', size=12, color='white', line=dict(width=1, color='black')),
            hovertemplate='Current<br>Collateral: %{x:.1f}%<br>Debt: %{y:.1f}%<extra></extra>'
        ))

        # Trace 3: At Caps (Circle)
        fig.add_trace(go.Scatter(
            x=[c_caps], y=[d_caps],
            mode='markers',
            name='Util at Caps',
            marker=dict(symbol='circle', size=12, color='red', line=dict(width=1, color='black')),
            hovertemplate='At Caps<br>Collateral: %{x:.1f}%<br>Debt: %{y:.1f}%<extra></extra>'
        ))

        fig.update_layout(
            title=f'Yield Heatmap: {self.strategy_name}',
            xaxis_title='Collateral Utilization (%)',
            yaxis_title='Debt Utilization (%)',
            width=600,
            height=600,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        return fig

    def generate_collateral_sensitivity_chart(self, fixed_debt_utilization: float):
        steps = 101
        x = np.linspace(0, 1, steps)  # Collateral Utilization
        y_vals = []
        valid_x = []

        for c_util in x:
            val = self.calculate_yield_with_utilization(debt_utilization=fixed_debt_utilization, collateral_utilization=c_util)
            y_vals.append(val)
            if 0 <= val <= 30:
                valid_x.append(c_util * 100)
            
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x*100, y=y_vals, mode='lines', name='Yield'))
        
        # Grid styling
        grid_style = dict(showgrid=True, gridwidth=1, gridcolor='#E5E5E5')

        layout_args = {
            "title": f"Yield vs Collateral Util (Fixed Debt Util: {fixed_debt_utilization*100:.1f}%)",
            "xaxis_title": "Collateral Utilization (%)", 
            "yaxis_title": "Yield (%)",
            "yaxis": dict(range=[0, 30], **grid_style),
            "xaxis": dict(**grid_style),
            "height": 400
        }
        
        if valid_x:
            min_x = max(0, min(valid_x) - 2)
            max_x = min(100, max(valid_x) + 2)
            layout_args["xaxis"].update(range=[min_x, max_x])
            
        fig.update_layout(**layout_args)
        return fig

    def generate_debt_sensitivity_chart(self, fixed_collateral_utilization: float):
        steps = 101
        x = np.linspace(0, 1, steps)  # Debt Utilization
        y_vals = []
        valid_x = []

        for d_util in x:
            val = self.calculate_yield_with_utilization(debt_utilization=d_util, collateral_utilization=fixed_collateral_utilization)
            y_vals.append(val)
            if 0 <= val <= 30:
                valid_x.append(d_util * 100)

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x*100, y=y_vals, mode='lines', name='Yield'))
        
        # Grid styling
        grid_style = dict(showgrid=True, gridwidth=1, gridcolor='#E5E5E5')

        layout_args = {
            "title": f"Yield vs Debt Util (Fixed Collateral Util: {fixed_collateral_utilization*100:.1f}%)",
            "xaxis_title": "Debt Utilization (%)", 
            "yaxis_title": "Yield (%)",
            "yaxis": dict(range=[0, 30], **grid_style),
            "xaxis": dict(**grid_style),
            "height": 400
        }
        
        if valid_x:
            min_x = max(0, min(valid_x) - 2)
            max_x = min(100, max(valid_x) + 2)
            layout_args["xaxis"].update(range=[min_x, max_x])
            
        fig.update_layout(**layout_args)
        return fig


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
