import streamlit as st
import json
import os
import pandas as pd

from vault import Vault
from strategy import Strategy, construct_strategies

# Constants
PRESET_FILE = os.path.join(os.path.dirname(__file__), "cluster_preset_v2.json")

def load_presets():
    if not os.path.exists(PRESET_FILE):
        return []
    with open(PRESET_FILE, 'r') as f:
        return json.load(f)

def save_presets(presets):
    with open(PRESET_FILE, 'w') as f:
        json.dump(presets, f, indent=4)

def _reset_cluster_state() -> None:
    for k in (
        "cluster_name",
        "vault_object_map_by_input",
        "vault_object_map_by_vault",
        "vault_cfg_map_by_input",
        "onchain_df",
        "onchain_assumptions_df",
        "onchain_params_by_input",
        "assumptions_df",
        "assumptions_editor_version",
        "strategy_rows",
    ):
        st.session_state.pop(k, None)

def _build_assumptions_df(vault_object_map_by_input: dict[str, Vault]) -> pd.DataFrame:
    rows: list[dict] = []
    for input_addr, vault in vault_object_map_by_input.items():
        irm = vault.interest_rate_model_info or {}
        rows.append(
            {
                "inputAddress": input_addr,
                "vault": vault.vault,
                "vaultSymbol": vault.vault_symbol,
                "assetSymbol": vault.asset_symbol,
                "supplyCap": vault.supply_cap,
                "borrowCap": vault.borrow_cap,
                "kinkPercent": irm.get("kinkPercent"),
                "baseRateApy": irm.get("baseRateApy"),
                "rateAtKink": irm.get("rateAtKink"),
                "maximumRate": irm.get("maximumRate"),
            }
        )
    return pd.DataFrame(rows)

def render():
    st.title("Vault Cluster Manager")

    # Load presets
    presets = load_presets()
    
    if not presets:
        st.warning("No cluster presets found.")
        return

    # Cluster Selection
    cluster_names = [p['name'] for p in presets]
    selected_cluster_name = st.selectbox("Select Cluster", cluster_names)
    st.caption("Pick a preset cluster, then fetch on-chain data and optionally apply assumptions.")

    if st.session_state.get("cluster_name") != selected_cluster_name:
        _reset_cluster_state()
        st.session_state["cluster_name"] = selected_cluster_name
    
    # Find selected cluster object
    selected_cluster = next((p for p in presets if p['name'] == selected_cluster_name), None)
    
    if not selected_cluster:
        st.error("Selected cluster not found.")
        return

    # Manage Vaults
    with st.expander("Manage Vaults in Cluster"):
        st.caption("Add/remove vaults and edit preset metadata (addresses + DeFiLlama mapping).")
        # Convert dictionary to DataFrame for editing
        vaults_list = selected_cluster.get('vaults', [])
        
        # Create list of dicts for DataFrame
        vault_data = [
            {
                "Optics": v.get("optics", ""),
                "Address": v.get("address", ""),
                "DefiLlamaPool": v.get("defillama_pool", ""),
                "Field": v.get("field", ""),
            }
            for v in vaults_list
            if isinstance(v, dict)
        ]
        df = pd.DataFrame(vault_data)
        
        edited_df = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key=f"editor_{selected_cluster_name}",
            column_config={
                "Optics": st.column_config.TextColumn(
                    "Optics",
                    help="e.g. USDC, WETH",
                    required=True
                ),
                "Address": st.column_config.TextColumn(
                    "Vault Address",
                    help="Enter the vault address (starts with 0x)",
                    width="large",
                    required=True,
                    validate="^0x[a-fA-F0-9]{40}$"
                ),
                "DefiLlamaPool": st.column_config.TextColumn(
                    "DefiLlama Pool ID",
                    help="UUID from yields.llama.fi (optional)",
                    required=False,
                    width="large",
                ),
                "Field": st.column_config.TextColumn(
                    "Field",
                    help="e.g. apyReward, apy, apyBase (optional)",
                    required=False,
                ),
            }
        )
        
        # Reconstruct list from edited DataFrame
        # Handle empty DF case
        if edited_df is not None and not edited_df.empty:
            # Filter out rows with empty keys or values
            valid_rows = edited_df[edited_df["Optics"].astype(str).str.strip().astype(bool) &
                                 edited_df["Address"].astype(str).str.strip().astype(bool)]
            
            new_vaults = []
            for _, row in valid_rows.iterrows():
                new_vaults.append(
                    {
                        "optics": str(row.get("Optics", "")).strip(),
                        "address": str(row.get("Address", "")).strip(),
                        "defillama_pool": str(row.get("DefiLlamaPool", "")).strip(),
                        "field": str(row.get("Field", "")).strip(),
                    }
                )
        else:
            new_vaults = []
            
        if new_vaults != vaults_list:
            selected_cluster['vaults'] = new_vaults
            save_presets(presets)
            st.rerun()

    # Fetch Data Button
    st.caption("Fetch reads on-chain values and resets the assumptions editor to match on-chain.")
    if st.button("Fetch Cluster Data"):
        with st.spinner("Fetching data..."):
            all_data = []
            vault_object_map_by_input: dict[str, Vault] = {}
            vault_object_map_by_vault: dict[str, Vault] = {}
            vault_cfg_map_by_input: dict[str, dict] = {}
            vaults_to_process = selected_cluster.get('vaults', [])
            progress_bar = st.progress(0)
            total_vaults = len(vaults_to_process)
            
            # Iterate over dictionary items
            for idx, vault_cfg in enumerate(vaults_to_process):
                try:
                    symbol = vault_cfg.get("optics", "")
                    vault_addr = vault_cfg.get("address", "")
                    defillama_pool = vault_cfg.get("defillama_pool", "")
                    defillama_field = vault_cfg.get("field", "")

                    vault = Vault(
                        vault_addr,
                        defillama_pool=defillama_pool,
                        defillama_field=defillama_field,
                    )
                    vault_object_map_by_input[vault_addr] = vault
                    vault_cfg_map_by_input[vault_addr] = dict(vault_cfg) if isinstance(vault_cfg, dict) else {}
                    vault_key = vault.vault or vault_addr
                    if vault_key:
                        vault_object_map_by_vault[vault_key] = vault

                    row = {
                        "configuredSymbol": symbol,
                        "inputAddress": vault_addr,
                        "timestamp": vault.timestamp,
                        "vault": vault.vault,
                        "vaultName": vault.vault_name,
                        "vaultSymbol": vault.vault_symbol,
                        "vaultDecimals": vault.vault_decimals,
                        "asset": vault.asset,
                        "assetName": vault.asset_name,
                        "assetSymbol": vault.asset_symbol,
                        "assetDecimals": vault.asset_decimals,
                        "totalCash": vault.total_cash,
                        "totalBorrowed": vault.total_borrowed,
                        "totalAssets": vault.total_assets,
                        "supplyCap": vault.supply_cap,
                        "borrowCap": vault.borrow_cap,
                        "interestRateModel": vault.interest_rate_model,
                        "currentUtilization": vault.current_utilization,
                        "utilizationAtCaps": vault.utilization_at_caps,
                        "currentBorrowApy": vault.current_borrow_apy,
                        "currentSupplyApy": vault.current_supply_apy,
                        "capsBorrowApy": vault.caps_borrow_apy,
                        "capsSupplyApy": vault.caps_supply_apy,
                        "nativeYield": vault.nativeYield,
                    }

                    for k, v in vault.interest_rate_model_info.items():
                        row[f"irm_{k}"] = v

                    all_data.append(row)
                except Exception as e:
                    st.error(f"Error fetching {symbol} ({vault_addr}): {e}")
                
                if total_vaults > 0:
                    progress_bar.progress((idx + 1) / total_vaults)
            
            st.session_state["vault_object_map_by_input"] = vault_object_map_by_input
            st.session_state["vault_object_map_by_vault"] = vault_object_map_by_vault
            st.session_state["vault_cfg_map_by_input"] = vault_cfg_map_by_input
            st.session_state["onchain_df"] = pd.DataFrame(all_data) if all_data else pd.DataFrame()
            onchain_assumptions_df = _build_assumptions_df(vault_object_map_by_input)
            st.session_state["onchain_assumptions_df"] = onchain_assumptions_df
            st.session_state["assumptions_df"] = onchain_assumptions_df.copy()
            st.session_state["assumptions_editor_version"] = int(st.session_state.get("assumptions_editor_version", 0) or 0) + 1
            st.session_state["onchain_params_by_input"] = {
                input_addr: {
                    "supply_cap": v.supply_cap,
                    "borrow_cap": v.borrow_cap,
                    "irm": dict(v.interest_rate_model_info or {}),
                }
                for input_addr, v in vault_object_map_by_input.items()
            }
            st.session_state.pop("strategy_rows", None)

    onchain_df = st.session_state.get("onchain_df")
    vault_object_map_by_input = st.session_state.get("vault_object_map_by_input")
    vault_object_map_by_vault = st.session_state.get("vault_object_map_by_vault")
    vault_cfg_map_by_input = st.session_state.get("vault_cfg_map_by_input")

    if isinstance(onchain_df, pd.DataFrame) and not onchain_df.empty:
        st.divider()
        st.subheader("Vault Metrics")
        st.caption("Combined on-chain values with utilization visualization.")
        
        # Select required columns
        base_cols = [
            'assetSymbol', 'totalAssets', 'totalBorrowed', 
            'currentUtilization', 'currentBorrowApy', 'currentSupplyApy', 
            'nativeYield', 'supplyCap', 'borrowCap'
        ]
        
        # Ensure all columns exist
        available_cols = [c for c in base_cols if c in onchain_df.columns]
        dashboard_df = onchain_df[available_cols].copy()
        
        # Ensure numeric types and handle missing values
        numeric_cols = ['totalAssets', 'supplyCap', 'totalBorrowed', 'borrowCap', 'currentUtilization']
        for col in numeric_cols:
            if col in dashboard_df.columns:
                dashboard_df[col] = pd.to_numeric(dashboard_df[col], errors='coerce').fillna(0)

        # Helper for K/M formatting
        def fmt_val(val):
            val = float(val) if pd.notnull(val) else 0
            if val >= 1_000_000:
                return f"{val/1_000_000:.2f}M"
            elif val >= 1_000:
                return f"{val/1_000:.2f}K"
            else:
                return f"{val:,.2f}"

        # Calculate Fill Percentages (0-100) for Progress Bars
        if 'totalAssets' in dashboard_df.columns and 'supplyCap' in dashboard_df.columns:
            dashboard_df['supplyFill'] = dashboard_df.apply(
                lambda x: (x['totalAssets'] / x['supplyCap'] * 100) if x['supplyCap'] > 0 else 0, 
                axis=1
            )
            # Create display string: "Value / Cap"
            dashboard_df['totalAssets_display'] = dashboard_df.apply(
                lambda x: f"{fmt_val(x['totalAssets'])} / {fmt_val(x['supplyCap'])}",
                axis=1
            )
        
        if 'totalBorrowed' in dashboard_df.columns and 'borrowCap' in dashboard_df.columns:
            dashboard_df['borrowFill'] = dashboard_df.apply(
                lambda x: (x['totalBorrowed'] / x['borrowCap'] * 100) if x['borrowCap'] > 0 else 0, 
                axis=1
            )
            # Create display string: "Value / Cap"
            dashboard_df['totalBorrowed_display'] = dashboard_df.apply(
                lambda x: f"{fmt_val(x['totalBorrowed'])} / {fmt_val(x['borrowCap'])}",
                axis=1
            )

        # Define display order
        final_cols = [
            'assetSymbol', 
            'totalAssets_display', 'supplyFill', 
            'totalBorrowed_display', 'borrowFill', 
            'currentUtilization', 
            'currentBorrowApy', 'currentSupplyApy', 'nativeYield'
        ]
        # Filter to only cols that exist
        final_df = dashboard_df[[c for c in final_cols if c in dashboard_df.columns]].copy()

        # Create Styler for number formatting (Commas)
        styler = final_df.style
        format_dict = {
            "currentBorrowApy": "{:.3f} %",
            "currentSupplyApy": "{:.3f} %",
            "nativeYield": "{:.3f} %",
        }
        styler.format(format_dict, na_rep="-")
        
        st.dataframe(
            styler,
            use_container_width=True,
            column_config={
                "assetSymbol": st.column_config.TextColumn("Asset"),
                "totalAssets_display": st.column_config.TextColumn("Total Assets (Value / Cap)"),
                "supplyFill": st.column_config.ProgressColumn(
                    "Supply Fill %", 
                    format="%.1f %%", 
                    min_value=0, 
                    max_value=100,
                    help="Assets / Supply Cap"
                ),
                "totalBorrowed_display": st.column_config.TextColumn("Total Borrowed (Value / Cap)"),
                "borrowFill": st.column_config.ProgressColumn(
                    "Borrow Fill %", 
                    format="%.1f %%", 
                    min_value=0, 
                    max_value=100,
                    help="Borrowed / Borrow Cap"
                ),
                "currentUtilization": st.column_config.ProgressColumn(
                    "Util %", 
                    format="%.1f %%", 
                    min_value=0, 
                    max_value=100,
                    help="Utilization Rate"
                ),
                "currentBorrowApy": st.column_config.NumberColumn("Borrow APY"),
                "currentSupplyApy": st.column_config.NumberColumn("Supply APY"),
                "nativeYield": st.column_config.NumberColumn("Native Yield"),
            }
        )

        st.divider()
        st.subheader("Assumptions")
        st.caption("Edit caps + IRM parameters here, then recompute strategies. These edits do not change the preset file.")
        assumptions_base_df = st.session_state.get("onchain_assumptions_df")
        if not isinstance(assumptions_base_df, pd.DataFrame):
            assumptions_base_df = _build_assumptions_df(vault_object_map_by_input)
            st.session_state["onchain_assumptions_df"] = assumptions_base_df

        if "assumptions_df" not in st.session_state or not isinstance(st.session_state.get("assumptions_df"), pd.DataFrame):
            st.session_state["assumptions_df"] = assumptions_base_df.copy()

        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("Reset Assumptions to On-chain"):
                st.session_state["assumptions_df"] = assumptions_base_df.copy()
                editor_key = f"assumptions_{selected_cluster_name}_{int(st.session_state.get('assumptions_editor_version', 0) or 0)}"
                st.session_state.pop(editor_key, None)
                st.session_state["assumptions_editor_version"] = int(st.session_state.get("assumptions_editor_version", 0) or 0) + 1

                onchain_params_by_input = st.session_state.get("onchain_params_by_input")
                if isinstance(onchain_params_by_input, dict):
                    for input_addr, params in onchain_params_by_input.items():
                        vault = vault_object_map_by_input.get(input_addr)
                        if vault is None or not isinstance(params, dict):
                            continue
                        supply_cap = params.get("supply_cap")
                        borrow_cap = params.get("borrow_cap")
                        irm = params.get("irm")
                        if supply_cap is not None:
                            vault.supply_cap = float(supply_cap)
                        if borrow_cap is not None:
                            vault.borrow_cap = float(borrow_cap)
                        vault.interest_rate_model_info = dict(irm) if isinstance(irm, dict) else {}
                        vault.compute_derived_fields()

                st.session_state.pop("strategy_rows", None)
                st.rerun()

        editor_version = int(st.session_state.get("assumptions_editor_version", 0) or 0)
        editor_key = f"assumptions_{selected_cluster_name}_{editor_version}"
        
        # Prepare DataFrame for editor (hide technical columns)
        df_full = st.session_state["assumptions_df"]
        visible_cols = [
            "vaultSymbol", "assetSymbol", 
            "supplyCap", "borrowCap", 
            "kinkPercent", "baseRateApy", "rateAtKink", "maximumRate"
        ]
        # Ensure all columns exist
        available_cols = [c for c in visible_cols if c in df_full.columns]
        df_editor_view = df_full[available_cols].copy()
        
        # Format Caps as strings with commas for better readability in the editor
        for col in ["supplyCap", "borrowCap"]:
            if col in df_editor_view.columns:
                df_editor_view[col] = df_editor_view[col].apply(
                    lambda x: f"{x:,.0f}" if pd.notnull(x) else ""
                )

        edited_df_view = st.data_editor(
            df_editor_view,
            num_rows="fixed",
            use_container_width=True,
            hide_index=True,
            key=editor_key,
            column_config={
                "vaultSymbol": st.column_config.TextColumn("Vault", disabled=True, help="Vault Symbol"),
                "assetSymbol": st.column_config.TextColumn("Asset", disabled=True, help="Underlying Asset"),
                "supplyCap": st.column_config.TextColumn(
                    "Supply Cap", 
                    required=False, 
                    help="Maximum amount that can be supplied (supports commas)",
                    validate="^[0-9,]*$"
                ),
                "borrowCap": st.column_config.TextColumn(
                    "Borrow Cap", 
                    required=False, 
                    help="Maximum amount that can be borrowed (supports commas)",
                    validate="^[0-9,]*$"
                ),
                "kinkPercent": st.column_config.NumberColumn(
                    "Kink %", 
                    required=False, 
                    format="%.3f %%",
                    min_value=0,
                    max_value=100,
                    help="Utilization point where the interest rate slope increases"
                ),
                "baseRateApy": st.column_config.NumberColumn(
                    "Base APY", 
                    required=False, 
                    format="%.3f %%",
                    min_value=0,
                    help="Interest rate at 0% utilization"
                ),
                "rateAtKink": st.column_config.NumberColumn(
                    "Rate @ Kink", 
                    required=False, 
                    format="%.3f %%",
                    min_value=0,
                    help="Interest rate at the kink utilization"
                ),
                "maximumRate": st.column_config.NumberColumn(
                    "Max Rate", 
                    required=False, 
                    format="%.3f %%",
                    min_value=0,
                    help="Interest rate at 100% utilization"
                ),
            },
        )
        
        # Update the main state DataFrame with edited values (converting strings back to floats)
        if edited_df_view is not None:
            df_to_update = edited_df_view.copy()
            for col in ["supplyCap", "borrowCap"]:
                if col in df_to_update.columns:
                    # Clean commas and convert to numeric, handling errors
                    df_to_update[col] = (
                        df_to_update[col]
                        .astype(str)
                        .str.replace(",", "")
                    )
                    df_to_update[col] = pd.to_numeric(df_to_update[col], errors='coerce')
            
            # We use index alignment since num_rows is fixed
            st.session_state["assumptions_df"].update(df_to_update)

        if st.button("Compute Strategies"):
            # Use the full dataframe which now has updated values
            for _, row in st.session_state["assumptions_df"].iterrows():
                input_addr = str(row.get("inputAddress", "")).strip()
                vault = vault_object_map_by_input.get(input_addr)
                if vault is None:
                    continue

                supply_cap = row.get("supplyCap", None)
                borrow_cap = row.get("borrowCap", None)
                if pd.notna(supply_cap):
                    vault.supply_cap = float(supply_cap)
                if pd.notna(borrow_cap):
                    vault.borrow_cap = float(borrow_cap)

                irm = dict(vault.interest_rate_model_info or {})
                for key in ("kinkPercent", "baseRateApy", "rateAtKink", "maximumRate"):
                    v = row.get(key, None)
                    if pd.notna(v):
                        irm[key] = float(v)
                vault.interest_rate_model_info = irm
                vault.compute_derived_fields()

            strategies = construct_strategies(vault_object_map_by_vault) if isinstance(vault_object_map_by_vault, dict) else []
            strategy_rows = []
            for s in strategies:
                debt_asset = s.get("debtAsset")
                collateral_asset = s.get("collateralAsset")
                debt_vault = vault_object_map_by_vault.get(debt_asset) if isinstance(vault_object_map_by_vault, dict) else None
                collateral_vault = vault_object_map_by_vault.get(collateral_asset) if isinstance(vault_object_map_by_vault, dict) else None
                if debt_vault is None or collateral_vault is None:
                    continue
                try:
                    strategy_obj = Strategy(
                        debtVault=debt_vault,
                        collateralVault=collateral_vault,
                        borrowLTV=float(s.get("borrowLTV") or 0.0),
                        liquidationLTV=float(s.get("liquidationLTV") or 0.0),
                    )
                    strategy_rows.append(
                        {
                            "strategy": strategy_obj.strategy_name,
                            "currentYield": strategy_obj.calculate_current_yield(),
                            "capsYield": strategy_obj.calculate_caps_yield(),
                        }
                    )
                except Exception:
                    continue

            st.session_state["strategy_rows"] = strategy_rows

    strategy_rows = st.session_state.get("strategy_rows")
    if isinstance(strategy_rows, list) and strategy_rows:
        st.divider()
        st.subheader("Strategy Yields")
        st.caption("Computed after applying assumptions: currentYield uses borrowLTV; capsYield uses liquidationLTV.")
        st.dataframe(
            pd.DataFrame(strategy_rows), 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "currentYield": st.column_config.NumberColumn("Current Yield", format="%.3f %%"),
                "capsYield": st.column_config.NumberColumn("Caps Yield", format="%.3f %%"),
            }
        )

def main():
    render()

if __name__ == "__main__":
    main()
