import streamlit as st
import json
import os
import pandas as pd

from vault import Vault
from strategy import Strategy, construct_strategies

# --- Constants ---
PRESET_FILE = os.path.join(os.path.dirname(__file__), "cluster_preset_v2.json")

# --- Helper Functions ---

def load_presets():
    if not os.path.exists(PRESET_FILE):
        return []
    with open(PRESET_FILE, 'r') as f:
        return json.load(f)

def save_presets(presets):
    with open(PRESET_FILE, 'w') as f:
        json.dump(presets, f, indent=4)

def fmt_val(val):
    """Format numeric values with K/M suffixes."""
    val = float(val) if pd.notnull(val) else 0
    if val >= 1_000_000:
        return f"{val/1_000_000:.2f}M"
    elif val >= 1_000:
        return f"{val/1_000:.2f}K"
    else:
        return f"{val:,.2f}"

def _reset_cluster_state() -> None:
    """Clear session state variables related to the cluster."""
    keys_to_remove = (
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
    )
    for k in keys_to_remove:
        st.session_state.pop(k, None)

def _build_assumptions_df(vault_object_map_by_input: dict[str, Vault]) -> pd.DataFrame:
    """Create a DataFrame for assumptions editing from vault objects."""
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
                "nativeYield": vault.nativeYield,
            }
        )
    return pd.DataFrame(rows)

# --- UI Components ---

def render_vault_management(selected_cluster, presets):
    """Render the 'Manage Vaults' expander."""
    with st.expander("Manage Vaults in Cluster"):
        st.caption("Add/remove vaults and edit preset metadata (addresses + DeFiLlama mapping).")
        vaults_list = selected_cluster.get('vaults', [])
        
        # Prepare data for editor
        vault_data = [
            {
                "Optics": v.get("optics", ""),
                "Address": v.get("address", ""),
                "DefiLlamaPool": v.get("defillama_pool", ""),
                "Field": v.get("field", ""),
            }
            for v in vaults_list if isinstance(v, dict)
        ]
        df = pd.DataFrame(vault_data)
        
        edited_df = st.data_editor(
            df,
            num_rows="dynamic",
            width="stretch",
            hide_index=True,
            key=f"editor_{selected_cluster.get('name')}",
            column_config={
                "Optics": st.column_config.TextColumn("Optics", help="e.g. USDC, WETH", required=True),
                "Address": st.column_config.TextColumn("Vault Address", help="Enter the vault address (starts with 0x)", width="large", required=True, validate="^0x[a-fA-F0-9]{40}$"),
                "DefiLlamaPool": st.column_config.TextColumn("DefiLlama Pool ID", help="UUID from yields.llama.fi (optional)", required=False, width="large"),
                "Field": st.column_config.TextColumn("Field", help="e.g. apyReward, apy, apyBase (optional)", required=False),
            }
        )
        
        # Save changes if any
        if edited_df is not None and not edited_df.empty:
            valid_rows = edited_df[edited_df["Optics"].astype(str).str.strip().astype(bool) &
                                 edited_df["Address"].astype(str).str.strip().astype(bool)]
            
            new_vaults = []
            for _, row in valid_rows.iterrows():
                new_vaults.append({
                    "optics": str(row.get("Optics", "")).strip(),
                    "address": str(row.get("Address", "")).strip(),
                    "defillama_pool": str(row.get("DefiLlamaPool", "")).strip(),
                    "field": str(row.get("Field", "")).strip(),
                })
        else:
            new_vaults = []
            
        if new_vaults != vaults_list:
            selected_cluster['vaults'] = new_vaults
            save_presets(presets)
            st.rerun()

def fetch_and_store_data(selected_cluster):
    """Fetch data from chain/DeFiLlama and update session state."""
    with st.spinner("Fetching data..."):
        all_data = []
        vault_object_map_by_input: dict[str, Vault] = {}
        vault_object_map_by_vault: dict[str, Vault] = {}
        vault_cfg_map_by_input: dict[str, dict] = {}
        
        vaults_to_process = selected_cluster.get('vaults', [])
        progress_bar = st.progress(0)
        total_vaults = len(vaults_to_process)
        
        for idx, vault_cfg in enumerate(vaults_to_process):
            try:
                symbol = vault_cfg.get("optics", "")
                vault_addr = vault_cfg.get("address", "")
                
                vault = Vault(
                    vault_addr,
                    defillama_pool=vault_cfg.get("defillama_pool", ""),
                    defillama_field=vault_cfg.get("field", ""),
                )
                vault_object_map_by_input[vault_addr] = vault
                vault_cfg_map_by_input[vault_addr] = dict(vault_cfg) if isinstance(vault_cfg, dict) else {}
                
                if vault.vault or vault_addr:
                    vault_object_map_by_vault[vault.vault or vault_addr] = vault

                # Build row data
                row = {
                    "configuredSymbol": symbol,
                    "inputAddress": vault_addr,
                    "timestamp": vault.timestamp,
                    "vault": vault.vault,
                    "vaultName": vault.vault_name,
                    "vaultSymbol": vault.vault_symbol,
                    "assetSymbol": vault.asset_symbol,
                    "totalCash": vault.total_cash,
                    "totalBorrowed": vault.total_borrowed,
                    "totalAssets": vault.total_assets,
                    "supplyCap": vault.supply_cap,
                    "borrowCap": vault.borrow_cap,
                    "currentUtilization": vault.current_utilization,
                    "currentBorrowApy": vault.current_borrow_apy,
                    "currentSupplyApy": vault.current_supply_apy,
                    "nativeYield": vault.nativeYield,
                }
                # Flatten IRM info
                for k, v in vault.interest_rate_model_info.items():
                    row[f"irm_{k}"] = v
                all_data.append(row)
                
            except Exception as e:
                st.error(f"Error fetching {symbol} ({vault_addr}): {e}")
            
            if total_vaults > 0:
                progress_bar.progress((idx + 1) / total_vaults)
        
        # Update Session State
        st.session_state["vault_object_map_by_input"] = vault_object_map_by_input
        st.session_state["vault_object_map_by_vault"] = vault_object_map_by_vault
        st.session_state["vault_cfg_map_by_input"] = vault_cfg_map_by_input
        st.session_state["onchain_df"] = pd.DataFrame(all_data) if all_data else pd.DataFrame()
        
        # Initialize Assumptions
        onchain_assumptions_df = _build_assumptions_df(vault_object_map_by_input)
        st.session_state["onchain_assumptions_df"] = onchain_assumptions_df
        st.session_state["assumptions_df"] = onchain_assumptions_df.copy()
        st.session_state["assumptions_editor_version"] = int(st.session_state.get("assumptions_editor_version", 0) or 0) + 1
        
        # Store initial params
        st.session_state["onchain_params_by_input"] = {
            input_addr: {
                "supply_cap": v.supply_cap,
                "borrow_cap": v.borrow_cap,
                "irm": dict(v.interest_rate_model_info or {}),
            }
            for input_addr, v in vault_object_map_by_input.items()
        }
        st.session_state.pop("strategy_rows", None)

def render_vault_metrics(onchain_df):
    """Render the Vault Metrics table."""
    st.divider()
    st.subheader("Vault Metrics")
    st.caption("Combined on-chain values with utilization visualization.")
    
    # Filter and Copy
    base_cols = [
        'assetSymbol', 'totalAssets', 'totalBorrowed', 
        'currentUtilization', 'currentBorrowApy', 'currentSupplyApy', 
        'nativeYield', 'supplyCap', 'borrowCap'
    ]
    available_cols = [c for c in base_cols if c in onchain_df.columns]
    dashboard_df = onchain_df[available_cols].copy()
    
    # Numeric conversion
    numeric_cols = ['totalAssets', 'supplyCap', 'totalBorrowed', 'borrowCap', 'currentUtilization']
    for col in numeric_cols:
        if col in dashboard_df.columns:
            dashboard_df[col] = pd.to_numeric(dashboard_df[col], errors='coerce').fillna(0)

    # Calculate Derived Columns
    if 'totalAssets' in dashboard_df.columns and 'supplyCap' in dashboard_df.columns:
        dashboard_df['supplyFill'] = dashboard_df.apply(
            lambda x: (x['totalAssets'] / x['supplyCap'] * 100) if x['supplyCap'] > 0 else 0, axis=1
        )
        dashboard_df['totalAssets_display'] = dashboard_df.apply(
            lambda x: f"{fmt_val(x['totalAssets'])} / {fmt_val(x['supplyCap'])}", axis=1
        )
    
    if 'totalBorrowed' in dashboard_df.columns and 'borrowCap' in dashboard_df.columns:
        dashboard_df['borrowFill'] = dashboard_df.apply(
            lambda x: (x['totalBorrowed'] / x['borrowCap'] * 100) if x['borrowCap'] > 0 else 0, axis=1
        )
        dashboard_df['totalBorrowed_display'] = dashboard_df.apply(
            lambda x: f"{fmt_val(x['totalBorrowed'])} / {fmt_val(x['borrowCap'])}", axis=1
        )

    # Display Columns
    final_cols = [
        'assetSymbol', 
        'totalAssets_display', 'supplyFill', 
        'totalBorrowed_display', 'borrowFill', 
        'currentUtilization', 
        'currentBorrowApy', 'currentSupplyApy', 'nativeYield'
    ]
    final_df = dashboard_df[[c for c in final_cols if c in dashboard_df.columns]].copy()

    # Styler
    styler = final_df.style
    styler.format({
        "currentBorrowApy": "{:.2f} %",
        "currentSupplyApy": "{:.2f} %",
        "nativeYield": "{:.2f} %",
    }, na_rep="-")
    
    st.dataframe(
        styler,
        width="stretch",
        column_config={
            "assetSymbol": st.column_config.TextColumn("Asset"),
            "totalAssets_display": st.column_config.TextColumn("Total Assets (Value / Cap)"),
            "supplyFill": st.column_config.ProgressColumn("Supply Fill %", format="%.1f %%", min_value=0, max_value=100),
            "totalBorrowed_display": st.column_config.TextColumn("Total Borrowed (Value / Cap)"),
            "borrowFill": st.column_config.ProgressColumn("Borrow Fill %", format="%.1f %%", min_value=0, max_value=100),
            "currentUtilization": st.column_config.ProgressColumn("Util %", format="%.1f %%", min_value=0, max_value=100),
            "currentBorrowApy": st.column_config.NumberColumn("Borrow APY"),
            "currentSupplyApy": st.column_config.NumberColumn("Supply APY"),
            "nativeYield": st.column_config.NumberColumn("Native Yield"),
        }
    )

def render_assumptions_editor(selected_cluster_name, vault_object_map_by_input):
    """Render the Assumptions editor and handle resets."""
    st.divider()
    st.subheader("Assumptions")
    st.caption("Edit caps + IRM parameters here, then recompute strategies. These edits do not change the preset file.")
    
    # Ensure state exists
    assumptions_base_df = st.session_state.get("onchain_assumptions_df")
    if not isinstance(assumptions_base_df, pd.DataFrame):
        assumptions_base_df = _build_assumptions_df(vault_object_map_by_input)
        st.session_state["onchain_assumptions_df"] = assumptions_base_df

    if "assumptions_df" not in st.session_state:
        st.session_state["assumptions_df"] = assumptions_base_df.copy()

    # Ensure nativeYield exists in current assumptions if missing (migration for existing session)
    if "nativeYield" not in st.session_state["assumptions_df"].columns:
        # Try to backfill from vault objects
        st.session_state["assumptions_df"]["nativeYield"] = st.session_state["assumptions_df"]["inputAddress"].apply(
            lambda addr: vault_object_map_by_input.get(str(addr)).nativeYield if vault_object_map_by_input.get(str(addr)) else 0.0
        )

    # Reset Button
    if st.button("Reset Assumptions to On-chain"):
        st.session_state["assumptions_df"] = assumptions_base_df.copy()
        st.session_state["assumptions_editor_version"] = int(st.session_state.get("assumptions_editor_version", 0) or 0) + 1
        
        # Reset Vault objects to original state
        onchain_params = st.session_state.get("onchain_params_by_input", {})
        for input_addr, params in onchain_params.items():
            vault = vault_object_map_by_input.get(input_addr)
            if vault:
                vault.supply_cap = float(params.get("supply_cap", 0))
                vault.borrow_cap = float(params.get("borrow_cap", 0))
                vault.interest_rate_model_info = dict(params.get("irm", {}))
                vault.compute_derived_fields()
        
        st.session_state.pop("strategy_rows", None)
        st.rerun()

    # Editor View
    editor_key = f"assumptions_{selected_cluster_name}_{st.session_state.get('assumptions_editor_version', 0)}"
    df_full = st.session_state["assumptions_df"]
    
    # Prepare Display DataFrame
    visible_cols = ["vaultSymbol", "assetSymbol", "supplyCap", "borrowCap", "kinkPercent", "baseRateApy", "rateAtKink", "maximumRate", "nativeYield"]
    df_editor_view = df_full[[c for c in visible_cols if c in df_full.columns]].copy()
    
    # Format Caps with Commas for View
    for col in ["supplyCap", "borrowCap"]:
        if col in df_editor_view.columns:
            df_editor_view[col] = df_editor_view[col].apply(lambda x: f"{x:,.0f}" if pd.notnull(x) else "")

    edited_df_view = st.data_editor(
        df_editor_view,
        num_rows="fixed",
        width="stretch",
        hide_index=True,
        key=editor_key,
        column_config={
            "vaultSymbol": st.column_config.TextColumn("Vault", disabled=True),
            "assetSymbol": st.column_config.TextColumn("Asset", disabled=True),
            "supplyCap": st.column_config.TextColumn("Supply Cap", validate="^[0-9,]*$"),
            "borrowCap": st.column_config.TextColumn("Borrow Cap", validate="^[0-9,]*$"),
            "kinkPercent": st.column_config.NumberColumn("Kink %", format="%.3f %%", min_value=0, max_value=100),
            "baseRateApy": st.column_config.NumberColumn("Base APY", format="%.3f %%", min_value=0),
            "rateAtKink": st.column_config.NumberColumn("Rate @ Kink", format="%.3f %%", min_value=0),
            "maximumRate": st.column_config.NumberColumn("Max Rate", format="%.3f %%", min_value=0),
            "nativeYield": st.column_config.NumberColumn("Native Yield", format="%.3f %%"),
        },
    )

    # Sync edits back to session state
    if edited_df_view is not None:
        df_to_update = edited_df_view.copy()
        for col in ["supplyCap", "borrowCap"]:
            if col in df_to_update.columns:
                df_to_update[col] = df_to_update[col].astype(str).str.replace(",", "")
                df_to_update[col] = pd.to_numeric(df_to_update[col], errors='coerce')
        
        st.session_state["assumptions_df"].update(df_to_update)

def compute_and_render_strategies(vault_object_map_by_input, vault_object_map_by_vault):
    """Compute strategies based on current assumptions and display them."""
    if st.button("Compute Strategies"):
        # 1. Update Vault Objects from Assumptions DF
        for _, row in st.session_state["assumptions_df"].iterrows():
            input_addr = str(row.get("inputAddress", "")).strip()
            vault = vault_object_map_by_input.get(input_addr)
            if not vault: continue

            # Update Caps
            if pd.notna(row.get("supplyCap")): vault.supply_cap = float(row.get("supplyCap"))
            if pd.notna(row.get("borrowCap")): vault.borrow_cap = float(row.get("borrowCap"))
            
            # Update Native Yield
            if pd.notna(row.get("nativeYield")):
                vault.nativeYield = float(row.get("nativeYield"))
            
            # Update IRM
            irm = dict(vault.interest_rate_model_info or {})
            for key in ("kinkPercent", "baseRateApy", "rateAtKink", "maximumRate"):
                if pd.notna(row.get(key)):
                    irm[key] = float(row.get(key))
            vault.interest_rate_model_info = irm
            vault.compute_derived_fields()

        # 2. Compute Strategies
        strategies = construct_strategies(vault_object_map_by_vault) if isinstance(vault_object_map_by_vault, dict) else []
        strategy_rows = []
        for s in strategies:
            debt_vault = vault_object_map_by_vault.get(s.get("debtAsset"))
            coll_vault = vault_object_map_by_vault.get(s.get("collateralAsset"))
            if not debt_vault or not coll_vault: continue
            
            try:
                strategy_obj = Strategy(
                    debtVault=debt_vault,
                    collateralVault=coll_vault,
                    borrowLTV=float(s.get("borrowLTV") or 0.0),
                    liquidationLTV=float(s.get("liquidationLTV") or 0.0),
                )
                strategy_rows.append({
                    "strategy": strategy_obj.strategy_name,
                    "debtAsset": debt_vault.asset_symbol or debt_vault.vault_symbol or debt_vault.vault_address,
                    "collateralAsset": coll_vault.asset_symbol or coll_vault.vault_symbol or coll_vault.vault_address,
                    "currentYield": strategy_obj.calculate_current_yield(),
                    "capsYield": strategy_obj.calculate_caps_yield(),
                })
            except Exception:
                continue

        st.session_state["strategy_rows"] = strategy_rows

    # 3. Render Strategy Results
    strategy_rows = st.session_state.get("strategy_rows")
    if isinstance(strategy_rows, list) and strategy_rows:
        st.divider()
        st.subheader("Strategy Yields")
        st.caption("Computed after applying assumptions: currentYield uses borrowLTV; capsYield uses liquidationLTV.")
        
        df = pd.DataFrame(strategy_rows)
        
        def color_yield(val):
            if not isinstance(val, (int, float)):
                return ''
            color = 'green' if val >= 0 else 'red'
            return f'color: {color}'
            
        styler = df.style.map(color_yield, subset=["currentYield", "capsYield"])
        styler.format({
            "currentYield": "{:.3f} %",
            "capsYield": "{:.3f} %",
        })

        st.dataframe(
            styler, 
            width="stretch", 
            hide_index=True,
            column_config={
                "strategy": st.column_config.TextColumn("Strategy Name"),
                "debtAsset": st.column_config.TextColumn("Debt Asset"),
                "collateralAsset": st.column_config.TextColumn("Collateral Asset"),
                "currentYield": st.column_config.NumberColumn("Current Yield"),
                "capsYield": st.column_config.NumberColumn("Caps Yield"),
            }
        )

# --- Main Execution Flow ---

def main():
    st.title("Vault Cluster Manager")
    
    # 1. Initialization
    presets = load_presets()
    if not presets:
        st.warning("No cluster presets found.")
        return

    cluster_names = [p['name'] for p in presets]
    selected_cluster_name = st.selectbox("Select Cluster", cluster_names)
    
    if st.session_state.get("cluster_name") != selected_cluster_name:
        _reset_cluster_state()
        st.session_state["cluster_name"] = selected_cluster_name
    
    selected_cluster = next((p for p in presets if p['name'] == selected_cluster_name), None)
    if not selected_cluster:
        st.error("Selected cluster not found.")
        return

    # 2. Vault Management
    render_vault_management(selected_cluster, presets)

    # 3. Data Fetching
    st.caption("Fetch reads on-chain values and resets the assumptions editor to match on-chain.")
    if st.button("Fetch Cluster Data"):
        fetch_and_store_data(selected_cluster)

    # 4. Metrics & Assumptions (Only if data exists)
    onchain_df = st.session_state.get("onchain_df")
    vault_object_map_by_input = st.session_state.get("vault_object_map_by_input")
    vault_object_map_by_vault = st.session_state.get("vault_object_map_by_vault")

    if isinstance(onchain_df, pd.DataFrame) and not onchain_df.empty:
        render_vault_metrics(onchain_df)
        
        if vault_object_map_by_input:
            render_assumptions_editor(selected_cluster_name, vault_object_map_by_input)
            compute_and_render_strategies(vault_object_map_by_input, vault_object_map_by_vault)

if __name__ == "__main__":
    main()
