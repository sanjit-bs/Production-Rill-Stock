import streamlit as st
import pandas as pd
# import gspread
# from google.oauth2.service_account import Credentials
from io import BytesIO
from datetime import date
import datetime
import math
import re
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

####################################### Paper Rill Stock ######################################

# ------------------------------------------------------
# Google Apps Script API Configuration
# ------------------------------------------------------
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxgc7mva9mumxyU37aaKmTGkcBM4BPGNq1kVCKauv5U-TiMWJ8RhiDPNPxy4gzcFeXe/exec"

COLUMNS_MASTER = [
    "Size",
    "GSM",
    "BF",
    "Quantity",
    "Weight",
    "Breakup_Weight",
    "Remark",
]
COLUMNS_HISTORY = [
    "Date",
    "Type",
    "Size",
    "GSM",
    "BF",
    "Quantity",
    "Weight",
    "Breakup_Weight",
    "Remark",
]


# ------------------------------------------------------
# Helpers: Breakup Weight Processing & Callbacks
# ------------------------------------------------------
def parse_breakup_weights(breakup_str):
    """Parses a string like '12.5, 15.0, 10.2' into a total weight sum and count.
    Returns (total_sum, count, cleaned_str)
    """
    if not breakup_str or not str(breakup_str).strip():
        return 0.0, 0, ""

    parts = [p.strip() for p in str(breakup_str).split(",") if p.strip()]
    valid_weights = []

    for p in parts:
        try:
            val = float(p)
            if val > 0:
                valid_weights.append(val)
        except ValueError:
            continue

    total_sum = sum(valid_weights)
    cleaned_str = ", ".join([f"{w:.2f}" for w in valid_weights])
    return round(total_sum, 2), len(valid_weights), cleaned_str


def sync_mod_breakup():
    """Callback to auto-sum and auto-count for Existing Stock updates"""
    key_suf = st.session_state.form_key
    raw = st.session_state.get(f"bk_mod_{key_suf}", "")

    # Only override the numbers if there is actually breakup text entered
    if raw.strip():
        calc_w, calc_q, _ = parse_breakup_weights(raw)
        st.session_state[f"q_mod_{key_suf}"] = int(calc_q)
        st.session_state[f"w_mod_{key_suf}"] = float(calc_w)


def sync_new_breakup():
    """Callback to auto-sum and auto-count for New Stock additions"""
    key_suf = st.session_state.form_key
    raw = st.session_state.get(f"bk_new_{key_suf}", "")

    # Only override the numbers if there is actually breakup text entered
    if raw.strip():
        calc_w, calc_q, _ = parse_breakup_weights(raw)
        st.session_state[f"q_new_{key_suf}"] = int(calc_q)
        st.session_state[f"w_new_{key_suf}"] = float(calc_w)


def update_master_breakup(curr_breakup_str, txn_breakup_str, action_type):
    _, _, cleaned_curr = parse_breakup_weights(curr_breakup_str)
    curr_list = (
        [float(x.strip()) for x in cleaned_curr.split(",") if x.strip()]
        if cleaned_curr
        else []
    )

    _, _, cleaned_txn = parse_breakup_weights(txn_breakup_str)
    txn_list = (
        [float(x.strip()) for x in cleaned_txn.split(",") if x.strip()]
        if cleaned_txn
        else []
    )

    missing_weights = []

    if action_type == "Purchased (+)":
        updated_list = curr_list + txn_list
    else:  # "Used (-)"
        updated_list = list(curr_list)
        for item in txn_list:
            match_idx = None
            for idx, val in enumerate(updated_list):
                if abs(val - item) < 0.01:
                    match_idx = idx
                    break
            if match_idx is not None:
                updated_list.pop(match_idx)
            else:
                missing_weights.append(item)

    updated_str = ", ".join([f"{w:.2f}" for w in updated_list])
    return updated_str, missing_weights


# ------------------------------------------------------
# Load Data via Apps Script
# ------------------------------------------------------
#@st.cache_data(ttl=5)
def fetch_all_data():
    try:
        response = requests.get(
            f"{APPS_SCRIPT_URL}?action=read_all", allow_redirects=True, timeout=30
        )

        if "text/html" in response.headers.get("Content-Type", ""):
            st.error(
                "⚠️ Google returned HTML instead of JSON. Ensure Web App access is"
                " set to 'Anyone'."
            )
            return pd.DataFrame(columns=COLUMNS_MASTER), pd.DataFrame(
                columns=COLUMNS_HISTORY
            )

        data = response.json()
        master_df = pd.DataFrame(data.get("master", []))
        history_df = pd.DataFrame(data.get("history", []))

        for col in COLUMNS_MASTER:
            if col not in master_df.columns:
                master_df[col] = 0 if col in ["Quantity", "Weight"] else ""

        for col in COLUMNS_HISTORY:
            if col not in history_df.columns:
                history_df[col] = 0 if col in ["Quantity", "Weight"] else ""

        return master_df[COLUMNS_MASTER], history_df[COLUMNS_HISTORY]

    except Exception as e:
        st.error(f"Error connecting to Apps Script API: {e}")
        return pd.DataFrame(columns=COLUMNS_MASTER), pd.DataFrame(
            columns=COLUMNS_HISTORY
        )


# ------------------------------------------------------
# Submit Record via Apps Script
# ------------------------------------------------------
# def get_retry_session():
#    session = requests.Session()
#    retries = Retry(
#        total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504]
#    )
#    session.mount("https://", HTTPAdapter(max_retries=retries))
#    return session

# def send_update_to_sheet(params):
#    try:
#      session = get_retry_session()
#      # Increased timeout to 45 seconds to accommodate Google Apps Script cold starts
#      res = session.get(APPS_SCRIPT_URL, params=params, timeout=45)
#      res_data = res.json()
#
#      if res_data.get("status") == "success":
#        st.toast("✅ Stock updated successfully!")
#        st.cache_data.clear()
#        st.session_state.form_key += 1
#        st.rerun()
#      else:
#        err_msg = res_data.get("message", "Unknown script error.")
#        st.error(f"Backend Error: {err_msg}")
#    except requests.exceptions.Timeout:
#      st.error(
#          "⏰ Request timed out. Google Script took too long to respond. Please"
#          " check your sheet."
#      )
#    except Exception as e:
#      st.error(f"Transaction failed: {e}")


def send_update_to_sheet(payload):
    try:
        res = requests.post(APPS_SCRIPT_URL, json=payload, allow_redirects=True, timeout=60)

        if "text/html" in res.headers.get("Content-Type", ""):
            st.error("⚠️ Failed to update: Received HTML response. Check Web App URL permissions.")
            return

        res_data = res.json()

        if res_data.get("status") == "success":
            st.toast("✅ Updated successfully!")
            st.cache_data.clear()
            st.session_state.form_key += 1
            st.rerun()
        else:
            st.error(f"❌ Apps Script Error: {res_data.get('message', 'Unknown Error')}")

    except Exception as e:
        st.error(f"Failed to send update: {e}")


# ------------------------------------------------------
# Main Application Flow
# ------------------------------------------------------
rill_df, history_df = fetch_all_data()

st.markdown("---")
st.subheader("📜 Paper Rill Stock Ledger & Audit Log")

with st.expander("📐 Quick CM to Inches Converter"):
    cm_input = st.number_input(
        "Enter Size in CM",
        min_value=0.0,
        step=0.1,
        format="%.2f",
        key="standalone_cm_converter",
    )
    if cm_input > 0:
        inch_result = round(cm_input / 2.54, 2)
        st.success(f"**{cm_input:.2f} cm** = **{inch_result:.2f} Inches**")

if "form_key" not in st.session_state:
    st.session_state.form_key = 0
key_suffix_rill = st.session_state.form_key

tab_entry, tab_history = st.tabs(["⚡ Record Entry", "📜 History Log"])

# ------------------------------------------------------
# Tab 1: Record Entry
# ------------------------------------------------------
with tab_entry:
    st.markdown("##### 🔍 Select Product Specifications (Auto-Fills Details or Add New)")

    avail_sizes = (
        sorted(list(set(rill_df["Size"].astype(str).str.strip().unique())))
        if not rill_df.empty
        else []
    )
    avail_gsms = (
        sorted(list(set(rill_df["GSM"].astype(str).str.strip().unique())))
        if not rill_df.empty
        else []
    )
    avail_bfs = (
        sorted(list(set(rill_df["BF"].astype(str).str.strip().unique())))
        if not rill_df.empty
        else []
    )

    col_s1, col_s2, col_s3 = st.columns(3)

    with col_s1:
        sel_sz = st.selectbox(
            "Size *",
            options=["Select Size...", "➕ Add New..."] + avail_sizes,
            key=f"sheet_sz_{key_suffix_rill}",
        )
        if sel_sz == "➕ Add New...":
            final_size = st.text_input("Type New Size *", key=f"new_sz_{key_suffix_rill}")
        else:
            final_size = sel_sz if sel_sz != "Select Size..." else ""

    with col_s2:
        sel_gsm = st.selectbox(
            "GSM *",
            options=["Select GSM...", "➕ Add New..."] + avail_gsms,
            key=f"sheet_gsm_{key_suffix_rill}",
        )
        if sel_gsm == "➕ Add New...":
            final_gsm = st.text_input("Type New GSM *", key=f"new_gsm_{key_suffix_rill}")
        else:
            final_gsm = sel_gsm if sel_gsm != "Select GSM..." else ""

    with col_s3:
        sel_bf = st.selectbox(
            "BF *",
            options=["Select BF...", "➕ Add New..."] + avail_bfs,
            key=f"sheet_bf_{key_suffix_rill}",
        )
        if sel_bf == "➕ Add New...":
            final_bf = st.text_input("Type New BF *", key=f"new_bf_{key_suffix_rill}")
        else:
            final_bf = sel_bf if sel_bf != "Select BF..." else ""

    has_unselected = not (final_size and final_gsm and final_bf)

    if has_unselected:
        st.info("👆 Please select or type all details to proceed.")
    else:
        match_df = rill_df[
            (rill_df["Size"].astype(str).str.strip() == final_size.strip())
            & (rill_df["GSM"].astype(str).str.strip() == final_gsm.strip())
            & (rill_df["BF"].astype(str).str.strip() == final_bf.strip())
        ]

        # ==========================================
        # MODE A: UPDATE EXISTING STOCK
        # ==========================================
        if not match_df.empty:
            curr_qty = int(pd.to_numeric(match_df["Quantity"]).sum())
            curr_weight = float(pd.to_numeric(match_df["Weight"]).sum())
            curr_breakup = str(match_df.iloc[0]["Breakup_Weight"])
            display_breakup = curr_breakup if curr_breakup.strip() else "None"

            st.success(
                f"📌 **Selected Spec:** {final_size} Size | {final_gsm} GSM |"
                f" {final_bf} BF  \n⚡ **Current Stock:** {curr_qty} Rolls | **Weight:**"
                f" {curr_weight:.2f} kg  \n📦 **Available Breakup Weights:**"
                f" {display_breakup}"
            )

            action_type = st.radio(
                "Transaction Type", ["Purchased (+)", "Used (-)"], index=None, horizontal=True, key=f"tab1_type_{key_suffix_rill}"
            )

            col_m1, col_m2 = st.columns([1.5, 4.5])
            with col_m1:
                txn_date = st.date_input(
                    "Date", value=date.today(), key=f"dt_mod_{key_suffix_rill}"
                )
            with col_m2:
                raw_breakup = st.text_input(
                    "Breakup Weight Entry (kg)",
                    placeholder="e.g. 25.5, 30.0, 28.2",
                    help="Enter weights separated by commas.",
                    key=f"bk_mod_{key_suffix_rill}",
                    on_change=sync_mod_breakup,
                )

            _, _, clean_breakup_str = parse_breakup_weights(raw_breakup)
            new_master_breakup, missing_weights = update_master_breakup(
                curr_breakup, raw_breakup, action_type
            )

            # Initialize states so the callbacks can safely overwrite them
            if f"q_mod_{key_suffix_rill}" not in st.session_state:
                st.session_state[f"q_mod_{key_suffix_rill}"] = 0
            if f"w_mod_{key_suffix_rill}" not in st.session_state:
                st.session_state[f"w_mod_{key_suffix_rill}"] = 0.0

            col_m4, col_m5, col_m6 = st.columns([1.5, 1.5, 3])
            with col_m4:
                qty_change = st.number_input(
                    "Qty (Rills) *",
                    min_value=0,
                    step=1,
                    key=f"q_mod_{key_suffix_rill}",
                )
            with col_m5:
                weight_change = st.number_input(
                    "Total Weight (kg) *",
                    min_value=0.0,
                    step=0.1,
                    format="%.2f",
                    key=f"w_mod_{key_suffix_rill}",
                )
            with col_m6:
                new_remark = st.text_input(
                    "Remark", value="", key=f"r_mod_{key_suffix_rill}"
                )

            final_qty = (
                curr_qty + qty_change
                if action_type == "Purchased (+)"
                else curr_qty - qty_change
            )
            final_weight = (
                curr_weight + weight_change
                if action_type == "Purchased (+)"
                else curr_weight - weight_change
            )

            if st.button("Submit Record", type="primary", key="btn_update_rill"):
                if action_type is None:
                    st.warning("Please select a Transaction Type (Purchased or Used) before submitting.")
                elif action_type == "Used (-)" and qty_change > curr_qty:
                    st.warning(f"Cannot subtract {qty_change} rills! Available stock is only {curr_qty} rills.")
                elif action_type == "Used (-)" and weight_change > curr_weight:
                    st.warning(f"Cannot subtract {weight_change:.2f} kg! Available weight is only {curr_weight:.2f} kg.")
                elif qty_change == 0 and weight_change == 0:
                    st.warning("Please enter weight breakups or a non-zero quantity/weight.")
                else:
                    if action_type == "Used (-)" and missing_weights:
                        missing_str = ", ".join([f"{w:.2f}" for w in missing_weights])
                        st.info(f"ℹ️ Note: Weight(s) [{missing_str}] were not originally in the stock breakup list.")

                    payload = {
                        "action": "update_stock",
                        "date": txn_date.strftime("%d/%m/%Y"),
                        "type": "Purchased" if action_type == "Purchased (+)" else "Used",
                        "size": final_size.strip(),
                        "gsm": final_gsm.strip(),
                        "bf": final_bf.strip(),
                        "qty_change": int(qty_change),
                        "weight_change": float(weight_change),
                        "new_qty": int(final_qty),
                        "new_weight": float(final_weight),
                        "breakup_weight": clean_breakup_str,
                        "new_breakup_weight": new_master_breakup,
                        "remark": new_remark.strip(),
                    }
                    with st.spinner("Updating stock entry... Please wait."):
                        send_update_to_sheet(payload)

        # ==========================================
        # MODE B: ADD NEW ITEM
        # ==========================================
        else:
            st.warning("💡 **New Combination Detected:** Create this new specification below.")
            st.markdown("##### 📝 Initial Stock Entry for New Specification")

            col_n1, col_n2 = st.columns([1.5, 4.5])
            with col_n1:
                txn_date = st.date_input(
                    "Date", value=date.today(), key=f"dt_new_{key_suffix_rill}"
                )
            with col_n2:
                raw_breakup_new = st.text_input(
                    "Breakup Weight Entry (kg)",
                    placeholder="e.g. 25.5, 30.0, 28.2",
                    help="Optional: Enter initial weights separated by commas.",
                    key=f"bk_new_{key_suffix_rill}",
                    on_change=sync_new_breakup,
                )

            _, _, clean_breakup_new = parse_breakup_weights(raw_breakup_new)

            # Initialize states so the callbacks can safely overwrite them
            if f"q_new_{key_suffix_rill}" not in st.session_state:
                st.session_state[f"q_new_{key_suffix_rill}"] = 0
            if f"w_new_{key_suffix_rill}" not in st.session_state:
                st.session_state[f"w_new_{key_suffix_rill}"] = 0.0

            col_n3, col_n4, col_n5 = st.columns([1.5, 1.5, 3])
            with col_n3:
                new_initial_qty = st.number_input(
                    "Initial Quantity *",
                    min_value=0,
                    step=1,
                    key=f"q_new_{key_suffix_rill}",
                )
            with col_n4:
                new_weight = st.number_input(
                    "Initial Weight (kg) *",
                    min_value=0.0,
                    step=0.1,
                    format="%.2f",
                    key=f"w_new_{key_suffix_rill}",
                )
            with col_n5:
                new_remark_text = st.text_input(
                    "Remark", key=f"r_new_{key_suffix_rill}"
                )

            if st.button("Save New Stock Item", type="primary", key="btn_add_new_rill"):
                clean_size = final_size.strip()
                clean_gsm = final_gsm.strip()
                clean_bf = final_bf.strip()

                if not clean_size or not clean_gsm or not clean_bf:
                    st.warning("Please fill in Size, GSM, and BF.")
                elif new_initial_qty <= 0 and new_weight <= 0:
                    st.warning("Please enter an initial Quantity or Weight greater than 0.")
                else:
                    payload = {
                        "action": "add_new",
                        "date": txn_date.strftime("%d/%m/%Y"),
                        "type": "Purchased",
                        "size": clean_size,
                        "gsm": clean_gsm,
                        "bf": clean_bf,
                        "qty": int(new_initial_qty),
                        "weight": float(new_weight),
                        "qty_change": int(new_initial_qty),
                        "weight_change": float(new_weight),
                        "new_qty": int(new_initial_qty),
                        "new_weight": float(new_weight),
                        "breakup_weight": clean_breakup_new,
                        "new_breakup_weight": clean_breakup_new,
                        "remark": f"Initial Stock - {new_remark_text.strip()}".strip(" -"),
                    }
                    with st.spinner("Saving new stock item... Please wait."):
                        send_update_to_sheet(payload)

    # Display Stock Summary (Out of if/else block)
    st.markdown("### 📋 Current Stock Summary")
    st.dataframe(rill_df, use_container_width=True, hide_index=True)


# ------------------------------------------------------
# Tab 2: Record History Log View
# ------------------------------------------------------
with tab_history:
    st.markdown("### 📜 Detailed Record History Log")

    if history_df.empty:
        st.info("No record history available yet.")
    else:
        filtered_df = history_df.copy()

        # Data Cleaning
        filtered_df["Date"] = (
            filtered_df["Date"].astype(str).str.replace("'", "").str.strip()
        )
        filtered_df["Type"] = filtered_df["Type"].astype(str).str.strip()
        filtered_df["Size"] = filtered_df["Size"].astype(str).str.strip()
        filtered_df["GSM"] = filtered_df["GSM"].astype(str).str.strip()
        filtered_df["BF"] = filtered_df["BF"].astype(str).str.strip()

        filtered_df["Quantity"] = (
            pd.to_numeric(filtered_df["Quantity"], errors="coerce")
            .fillna(0)
            .astype(int)
        )
        filtered_df["Weight"] = (
            pd.to_numeric(filtered_df["Weight"], errors="coerce")
            .fillna(0.0)
            .astype(float)
        )
        filtered_df["Breakup_Weight"] = (
            filtered_df["Breakup_Weight"]
            .astype(str)
            .replace("nan", "")
            .str.strip()
        )
        filtered_df["Remark"] = (
            filtered_df["Remark"].astype(str).replace("nan", "").str.strip()
        )

        parsed_dates = pd.to_datetime(
            filtered_df["Date"], dayfirst=True, format="mixed", errors="coerce"
        ).dt.date
        valid_dates = parsed_dates.dropna()
        min_date = valid_dates.min() if not valid_dates.empty else date.today()
        max_date = valid_dates.max() if not valid_dates.empty else date.today()

        col_h1, col_h2, col_h3, col_h4 = st.columns(4)
        with col_h1:
            date_range = st.date_input(
                "Filter Date Range",
                value=(min_date, max_date),
                key=f"rill_hist_filter_date_{key_suffix_rill}",
            )
        with col_h2:
            filter_type = st.multiselect(
                "Filter Action Type",
                options=["Purchased", "Used"],
                default=["Purchased", "Used"],
                key=f"rill_hist_filter_type_{key_suffix_rill}",
            )
        with col_h3:
            filter_size = st.multiselect(
                "Filter Size",
                options=sorted(filtered_df["Size"].unique()),
                key=f"rill_hist_filter_size_{key_suffix_rill}",
            )
        with col_h4:
            search_text = st.text_input(
                "Search Remarks/Breakups/Specs",
                key=f"rill_hist_search_{key_suffix_rill}",
            )

        if date_range:
            if isinstance(date_range, (tuple, list)):
                if len(date_range) == 2:
                    start_d, end_d = date_range
                    filtered_df = filtered_df[
                        (parsed_dates >= start_d) & (parsed_dates <= end_d)
                    ]
                elif len(date_range) == 1:
                    start_d = date_range[0]
                    filtered_df = filtered_df[parsed_dates >= start_d]
            elif isinstance(date_range, date):
                filtered_df = filtered_df[parsed_dates == date_range]

        if filter_type:
            filtered_df = filtered_df[filtered_df["Type"].isin(filter_type)]
        if filter_size:
            filtered_df = filtered_df[filtered_df["Size"].isin(filter_size)]
        if search_text:
            filtered_df = filtered_df[
                filtered_df["Remark"].str.contains(search_text, case=False)
                | filtered_df["Breakup_Weight"].str.contains(search_text, case=False)
                | filtered_df["Size"].str.contains(search_text, case=False)
            ]

        st.dataframe(
            filtered_df,
            column_config={
                "Quantity": st.column_config.NumberColumn(
                    "Quantity (Rolls)", format="%d"
                ),
                "Weight": st.column_config.NumberColumn(
                    "Weight (kg)", format="%.2f"
                ),
                "Breakup_Weight": st.column_config.TextColumn(
                    "Breakup Weight Entry"
                ),
            },
            use_container_width=True,
            hide_index=True,
        )


# -----------------------------------------------------------------------------------------------------------------------------------------------------------------#
#############################-------------------------- Production Stock Configuration--------------------------------##############################################
# -----------------------------------------------------------------------------------------------------------------------------------------------------------------#
WEB_APP_URL = "https://script.google.com/macros/s/AKfycbxDEYO6Q6NaLyMv9TccVNHcM4jYCpFv9Mi95EaBAw6RYUcTz7JMzn3jjoNT1Jn43zth/exec"

st.set_page_config(page_title="Production Stock Ledger", layout="wide")


def clean_date_column(df, col_name="Date"):
    """
    Converts Apps Script ISO UTC timestamps (e.g. '2026-08-31T18:30:00.000Z') 
    back to Asia/Kolkata (IST) DD/MM/YYYY format.
    """
    if df.empty or col_name not in df.columns:
        return df

    def convert_val(val):
        if pd.isna(val) or str(val).strip() == "":
            return ""
        val_str = str(val).strip()

        # Handle ISO strings from Google Apps Script (e.g., 2026-08-31T18:30:00.000Z)
        if "T" in val_str or "Z" in val_str:
            dt = pd.to_datetime(val_str, errors="coerce", utc=True)
            if pd.notna(dt):
                return dt.tz_convert("Asia/Kolkata").strftime("%d/%m/%Y")

        # Handle DD/MM/YYYY string formats
        try:
            dt = pd.to_datetime(val_str, format="%d/%m/%Y", errors="coerce")
            if pd.notna(dt):
                return dt.strftime("%d/%m/%Y")
        except Exception:
            pass

        # Handle YYYY-MM-DD or other standard string formats
        dt = pd.to_datetime(val_str, errors="coerce")
        if pd.notna(dt):
            return dt.strftime("%d/%m/%Y")

        return val_str

    df[col_name] = df[col_name].apply(convert_val)
    return df


#@st.cache_data(ttl=5)
def fetch_data():
    try:
        response = requests.get(WEB_APP_URL, timeout=20).json()
        if response.get("status") == "success":
            master_df = pd.DataFrame(response.get("master", []))
            history_df = pd.DataFrame(response.get("history", []))

            # Format date columns to match Google Sheet DD/MM/YYYY format
            master_df = clean_date_column(master_df, "Date")
            history_df = clean_date_column(history_df, "Date")

            return master_df, history_df
    except Exception as e:
        st.error(f"Failed to fetch data from backend: {e}")
    return pd.DataFrame(), pd.DataFrame()


def calculate_totals(pcs, category, conversion_rule, rate_val):
    if pcs is None or rate_val is None or not conversion_rule:
        return None, None

    rule = str(conversion_rule).lower().strip()
    total_box = 0.0

    if "sheet * 2" in rule:
        total_box = pcs * 2.0
    elif "sheet * 1" in rule:
        total_box = pcs * 1.0
    elif "sheet / 2" in rule:
        total_box = pcs / 2.0
    elif "sheet * 6" in rule:
        total_box = pcs * 6.0
    elif "sheet * 8" in rule:
        total_box = pcs * 8.0
    elif "sheet * 16" in rule:
        total_box = pcs * 16.0
    elif "sheet * 9" in rule:
        total_box = pcs * 9.0
    else:
        total_box = float(pcs)

    # Inner and Label categories charge per sheet; Mini and NF charge per box
    if str(category).strip().lower() in ["inner", "label"]:
        total_charge = pcs * rate_val
    else:
        total_charge = total_box * rate_val

    return round(total_box, 2), round(total_charge, 2)


master_df, history_df = fetch_data()

st.markdown("---")
st.subheader("📦 Production Stock Tracker")

tab1, tab2, tab3 = st.tabs(["⚡ Record Entry", "📋 Master Stock", "📜 History Log"])

# ------------------------------------------------------
# Tab 1: Live Interactive Record Entry (No st.form)
# ------------------------------------------------------
with tab1:
    st.subheader("Add Production Record")

    entry_date = st.date_input("Select Entry Date *", value=date.today())

    avail_companies = (
        sorted(list(set(master_df["Company"].dropna().astype(str).str.strip())))
        if not master_df.empty and "Company" in master_df.columns
        else []
    )

    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        sel_company = st.selectbox(
            "Select Company *",
            ["Select Company...", "➕ Add New Company"] + avail_companies,
        )

    if sel_company == "➕ Add New Company":
        final_company = st.text_input(
            "Type New Company Name *", placeholder="Enter company name"
        )
        avail_products = []
    elif sel_company != "Select Company...":
        final_company = sel_company
        comp_matched_df = master_df[master_df["Company"] == sel_company]
        avail_products = sorted(
            list(set(comp_matched_df["Product"].dropna().astype(str).str.strip()))
        )
    else:
        final_company = ""
        avail_products = []

    with col_sel2:
        if sel_company not in ["Select Company...", "➕ Add New Company"]:
            sel_product = st.selectbox(
                "Select Product *",
                ["Select Product...", "➕ Add New Product"] + avail_products,
            )
        elif sel_company == "➕ Add New Company":
            sel_product = "➕ Add New Product"
        else:
            sel_product = "Select Product..."

    if sel_product == "➕ Add New Product":
        final_product = st.text_input(
            "Type New Product Name *", placeholder="Enter product name"
        )
    elif sel_product != "Select Product...":
        final_product = sel_product
    else:
        final_product = ""

    # Auto-fill preset values when selecting an existing product
    default_cat = None
    default_rule = ""
    default_rate = None

    if (
        final_company
        and final_product
        and not master_df.empty
        and sel_product != "➕ Add New Product"
    ):
        matched_item = master_df[
            (master_df["Company"].astype(str).str.strip() == final_company)
            & (master_df["Product"].astype(str).str.strip() == final_product)
        ]
        if not matched_item.empty:
            default_cat = str(matched_item.iloc[0].get("Category", ""))
            default_rule = str(
                matched_item.iloc[0].get("Sheet to Box or Inner", "")
            )
            raw_rate = str(matched_item.iloc[0].get("Rate (Rs)", ""))
            try:
                default_rate = float(raw_rate.split("/")[0].strip())
            except (ValueError, TypeError, AttributeError):
                default_rate = None

    st.markdown("---")

    col_f1, col_f2 = st.columns(2)

    categories = ["Select Category...", "Mini", "Inner", "NF", "Label"]
    cat_index = (
        categories.index(default_cat) if default_cat in categories else 0
    )

    with col_f1:
        category_val = st.selectbox("Category *", categories, index=cat_index)
        sheet_to_box_val = st.text_input(
            "Sheet to Box or Inner *",
            value=default_rule,
            placeholder="e.g. sheet * 2 = box",
        )
        pcs_val = st.number_input(
            "Number of sheet (PCS) *",
            min_value=1,
            step=1,
            value=None,
            placeholder="Enter sheet quantity",
        )

    with col_f2:
        rate_val = st.number_input(
            "Rate (Rs) *",
            min_value=0.0,
            step=0.01,
            value=default_rate,
            placeholder="Enter rate",
        )

        # Calculate live outputs immediately on widget value changes
        calc_box, calc_charge = calculate_totals(
            pcs_val,
            category_val if category_val != "Select Category..." else "",
            sheet_to_box_val,
            rate_val,
        )

        total_box_val = st.number_input(
            "TotalBox/Inner/Sheet *",
            min_value=0.0,
            step=0.1,
            value=calc_box,
            placeholder="Auto-calculated or enter value",
        )
        total_charge_val = st.number_input(
            "Total Processing Charge (Rs) *",
            min_value=0.0,
            step=0.1,
            value=calc_charge,
            placeholder="Auto-calculated or enter value",
        )

    st.write("")
    submitted = st.button("Submit Production Entry", type="primary")

    if submitted:
        if not final_company or not final_product:
            st.warning("⚠️ Please select or specify Company and Product.")
        elif category_val == "Select Category...":
            st.warning("⚠️ Please select a Category.")
        elif pcs_val is None:
            st.warning("⚠️ Please enter Number of sheet (PCS).")
        elif rate_val is None:
            st.warning("⚠️ Please enter Rate (Rs).")
        else:
            payload = {
                "Date": entry_date.strftime("%d/%m/%Y"),
                "Company": final_company.strip(),
                "Product": final_product.strip(),
                "PCS": int(pcs_val),
                "Category": category_val,
                "SheetToBox": sheet_to_box_val.strip(),
                "TotalBox/Inner/Sheet": float(
                    total_box_val if total_box_val is not None else 0.0
                ),
                "Rate": float(rate_val),
                "TotalCharge": float(
                    total_charge_val if total_charge_val is not None else 0.0
                ),
            }

            with st.spinner("Writing to Google Sheets..."):
                try:
                    res = requests.post(
                        WEB_APP_URL, json=payload, allow_redirects=True, timeout=30
                    )
                    if (
                        res.status_code == 200
                        and res.json().get("status") == "success"
                    ):
                        st.success("✅ Entry added successfully!")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(
                            f"❌ Script error: {res.json().get('message', 'Unknown error')}"
                        )
                except Exception as err:
                    st.error(f"❌ Network error: {err}")

# ------------------------------------------------------
# Tab 2: Master Stock Summary
# ------------------------------------------------------
with tab2:
    st.subheader("📋 Current Master Stock (Production_Stock)")
    if not master_df.empty:
        st.dataframe(master_df, use_container_width=True, hide_index=True)
    else:
        st.info("No master records available.")

# ------------------------------------------------------
# Tab 3: History Log
# ------------------------------------------------------
with tab3:
    st.subheader("📜 Production History Log (Production_Stock_H)")
    if not history_df.empty:
        st.dataframe(history_df, use_container_width=True, hide_index=True)
    else:
        st.info("No history log records available.")
