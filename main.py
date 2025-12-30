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
    
    # Find selected cluster object
    selected_cluster = next((p for p in presets if p['name'] == selected_cluster_name), None)
    
    if not selected_cluster:
        st.error("Selected cluster not found.")
        return

    # Manage Vaults
    with st.expander("Manage Vaults in Cluster"):
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
                )
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
    if st.button("Fetch Cluster Data"):
        st.divider()
        st.subheader("Cluster Data")
        
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
            
            if all_data:
                df = pd.DataFrame(all_data)
                
                # Reorder columns to put important ones first
                cols = [
                    'configuredSymbol', 'inputAddress', 'vault', 'vaultName', 'vaultSymbol', 'assetSymbol',
                    'totalAssets', 'supplyCap', 
                    'currentUtilization', 'currentBorrowApy', 'currentSupplyApy',
                    'nativeYield'
                ]
                # Filter cols that actually exist in df
                existing_cols = [c for c in cols if c in df.columns]
                remaining_cols = [c for c in df.columns if c not in existing_cols]
                
                st.dataframe(
                    df[existing_cols + remaining_cols], 
                    use_container_width=True,
                    column_config={
                        "currentUtilization": st.column_config.NumberColumn(
                            "Util %",
                            format="%.2f %%"
                        ),
                        "currentBorrowApy": st.column_config.NumberColumn(
                            "Borrow APY",
                            format="%.2f %%"
                        ),
                        "currentSupplyApy": st.column_config.NumberColumn(
                            "Supply APY",
                            format="%.2f %%"
                        ),
                        "nativeYield": st.column_config.NumberColumn(
                            "Native Yield",
                            format="%.2f %%"
                        ),
                        "baseRateApy": st.column_config.NumberColumn(
                            "Base APY",
                            format="%.2f %%"
                        ),
                        "rateAtKink": st.column_config.NumberColumn(
                            "Kink APY",
                            format="%.2f %%"
                        ),
                        "totalAssets": st.column_config.NumberColumn(
                            "Total Assets",
                            format="%.2f"
                        ),
                        "supplyCap": st.column_config.NumberColumn(
                            "Supply Cap",
                            format="%.2f"
                        )
                    }
                )
            else:
                st.info("No data available.")

            st.divider()
            st.subheader("Vault Objects")
            vault_objects_rows = []
            for input_addr, vault in vault_object_map_by_input.items():
                cfg = vault_cfg_map_by_input.get(input_addr, {})
                vault_objects_rows.append(
                    {
                        "optics": cfg.get("optics", ""),
                        "inputAddress": input_addr,
                        "vault": vault.vault,
                        "assetSymbol": vault.asset_symbol,
                        "currentBorrowApy": vault.current_borrow_apy,
                        "currentSupplyApy": vault.current_supply_apy,
                        "nativeYield": vault.nativeYield,
                        "error": vault.error,
                        "fetched": vault.fetched,
                    }
                )
            if vault_objects_rows:
                st.dataframe(pd.DataFrame(vault_objects_rows), use_container_width=True, hide_index=True)
            else:
                st.info("No vault objects available.")

            st.divider()
            st.subheader("Vault Object Map")
            vault_object_map_view = {}
            for input_addr, vault in vault_object_map_by_input.items():
                cfg = vault_cfg_map_by_input.get(input_addr, {})
                vault_object_map_view[input_addr] = {
                    "config": cfg,
                    "vault": {
                        "vault": vault.vault,
                        "vaultSymbol": vault.vault_symbol,
                        "assetSymbol": vault.asset_symbol,
                        "currentBorrowApy": vault.current_borrow_apy,
                        "currentSupplyApy": vault.current_supply_apy,
                        "capsBorrowApy": vault.caps_borrow_apy,
                        "capsSupplyApy": vault.caps_supply_apy,
                        "nativeYield": vault.nativeYield,
                        "fetched": vault.fetched,
                        "error": vault.error,
                    },
                }
            if vault_object_map_view:
                st.json(vault_object_map_view)
            else:
                st.info("No vault object map available.")

            strategies = construct_strategies(vault_object_map_by_vault)
            if strategies:
                st.divider()
                st.subheader("Strategies (LTVs)")
                st.dataframe(pd.DataFrame(strategies), use_container_width=True, hide_index=True)

                st.divider()
                st.subheader("Strategy Yields")
                strategy_rows = []
                for s in strategies:
                    debt_asset = s.get("debtAsset")
                    collateral_asset = s.get("collateralAsset")
                    debt_vault = vault_object_map_by_vault.get(debt_asset)
                    collateral_vault = vault_object_map_by_vault.get(collateral_asset)
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
                                "borrowLTV": strategy_obj.borrowLTV,
                                "liquidationLTV": strategy_obj.liquidationLTV,
                                "currentYield": strategy_obj.calculate_current_yield(),
                                "capsYield": strategy_obj.calculate_caps_yield(),
                            }
                        )
                    except Exception:
                        continue

                if strategy_rows:
                    st.dataframe(pd.DataFrame(strategy_rows), use_container_width=True, hide_index=True)
                else:
                    st.info("No strategy yields available (missing vaults for collateral addresses).")
            else:
                st.info("No strategy data available.")

def main():
    render()

if __name__ == "__main__":
    main()
