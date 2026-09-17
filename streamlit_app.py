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
