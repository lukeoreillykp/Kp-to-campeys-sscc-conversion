import streamlit as st
import pandas as pd
import re
from datetime import datetime
import pytz
import io
import urllib.parse
import requests
import base64

# Form Title Configuration
st.set_page_config(page_title="KP to Campeys SSCC Sender", layout="wide")
st.title("📦 KP to Campeys SSCC Sender")

# 1. Inputs for the additional information fields
st.subheader("1. Additional Information")
col1, col2 = st.columns(2)
with col1:
    extra_info_1 = st.text_input("Enter Load Ref (Names your file and repeats in Load Ref column):")
with col2:
    jde_order_ref = st.text_input("Enter JDE Order Ref (Populates the new Movement column):")

# 2. Raw Text Paste Area
st.subheader("2. Paste WMS Data Below")
st.caption("Include your header row! Copy the entire grid from your WMS (Ctrl+A -> Ctrl+C) and paste it below (Ctrl+V). Column order does not matter.")

pasted_text = st.text_area("Paste data here:", height=250, placeholder="SSCC Code\tItem Code\tDescription\tUnits...")

# Expected 9 WMS columns from your grid
EXPECTED_WMS_COLUMNS = [
    "SSCC Code", 
    "Item Code", 
    "Description", 
    "Units", 
    "Rotation Date", 
    "Batch", 
    "Status", 
    "Positive Release", 
    "Catch Weight To Remove"
]

# Helper function to drop invalid summary rows
def is_invalid_summary_row(row):
    sscc_val = str(row.get("SSCC Code", "")).strip().lower()
    if not sscc_val or pd.isna(row.get("SSCC Code")):
        return True
    if "total" in sscc_val or sscc_val in ["na", "n/a", "n / a"]:
        return True
    return False

# Helper function to flag explicit NA values
def contains_explicit_na(val):
    if pd.isna(val):
        return False
    clean_str = re.sub(r'[\s#\/\\\-_.]', '', str(val)).lower()
    return "na" in clean_str

# 3. Process & Display Logic
if st.button("Process & Generate Files", type="primary"):
    if not pasted_text.strip():
        st.error("Please paste some data into the text box first.")
    elif not extra_info_1 or not jde_order_ref:
        st.warning("Please fill out both the Load Ref and JDE Order Ref fields above.")
    else:
        try:
            # Detect separator layout
            separator = '\t' if '\t' in pasted_text else ','
            
            # Read pasted string block into pandas
            df_raw = pd.read_csv(io.StringIO(pasted_text.strip()), sep=separator)
            df_raw.columns = df_raw.columns.str.strip()
            
            # Verify columns match layout criteria
            missing_cols = [col for col in EXPECTED_WMS_COLUMNS if col not in df_raw.columns]
            if missing_cols:
                st.error(f"❌ Missing expected WMS columns in the pasted data: {missing_cols}. Please check your headers match exactly.")
            else:
                # Drop rows that are completely empty across every cell
                df_clean = df_raw.dropna(how='all').copy()
                
                # --- PROTECTION 1: DROP INVALID WMS SUMMARY ROWS ---
                summary_rows_mask = df_clean.apply(is_invalid_summary_row, axis=1)
                df_clean = df_clean[~summary_rows_mask]
                
                # --- PROTECTION 2: AGGRESSIVE FILTERING FOR ANY 'NA' VARIATION ---
                row_has_explicit_na = df_clean.map(contains_explicit_na).any(axis=1)
                df_filtered = df_clean[~row_has_explicit_na].copy()
                total_dropped = summary_rows_mask.sum() + row_has_explicit_na.sum()
                
                if df_filtered.empty:
                    st.error("Filtering complete: No valid data left to convert.")
                else:
                    # Get current date and time in UK/London time zone
                    local_tz = pytz.timezone("Europe/London")
                    current_time = datetime.now(local_tz).strftime("%d/%m/%Y %H:%M")
                    
                    # --- CALCULATE UNIQUE SKU COUNTS FOR SUMMARY PALLETS ---
                    sku_counts = df_filtered["Item Code"].astype(str).str.strip().value_counts()
                    clean_text_summary = "\n".join([f"• SKU: {sku} -> Count: {count}" for sku, count in sku_counts.items()])
                    
                    # Inject metadata headers into main data sheet
                    df_filtered["Load Ref"] = extra_info_1
                    df_filtered["Date"] = current_time
                    df_filtered["Movement"] = jde_order_ref
                    
                    # --- FINAL OUTPUT LAYOUT SPECIFICATION ---
                    FINAL_COLUMN_ORDER = ["Load Ref", "Date", "SSCC Code", "Item Code", "Description", "Units", "Rotation Date", "Batch", "Movement", "Status", "Positive Release", "Catch Weight To Remove"]
                    output_df = df_filtered[FINAL_COLUMN_ORDER]
                    
                    st.success(f"🎉 WMS Data successfully converted! (Dropped {total_dropped} invalid summary rows or 'na' lines)")
                    
                    # Create clean file properties based on your Load Ref input
                    safe_filename = re.sub(r'[\\/*?:"<>|]', "", extra_info_1).strip()
                    csv_filename = f"{safe_filename}.csv" if safe_filename else "wms_output.csv"
                    csv_data = output_df.to_csv(index=False)
                    csv_bytes = csv_data.encode('utf-8')
                    
                    # --- AUTOMATED GITHUB REPOSITORY UPLOAD LAYER ---
                    try:
                        TOKEN = st.secrets["github_token"]
                        USERNAME = st.secrets["github_username"]
                        REPO = st.secrets["github_repo"]
                        
                        # GitHub API Endpoint to save files inside a folder named 'saved_loads'
                        github_url = f"https://github.com{USERNAME}/{REPO}/contents/saved_loads/{csv_filename}"
                        
                        headers = {
                            "Authorization": f"token {TOKEN}",
                            "Accept": "application/vnd.github.v3+json"
                        }
                        
                        # Encode CSV payload to base64 for API transmission
                        b64_content = base64.b64encode(csv_bytes).decode('utf-8')
                        
                        # Check if file already exists to handle updates, otherwise create fresh entry
                        res_check = requests.get(github_url, headers=headers)
                        payload = {
                            "message": f"Archive automated reformat entry: {csv_filename}",
                            "content": b64_content
                        }
                        if res_check.status_code == 200:
                            payload["sha"] = res_check.json()["sha"]
                            
                        upload_res = requests.put(github_url, json=payload, headers=headers)
                        if upload_res.status_code == 201 or upload_res.status_code == 200:
                            st.info(f"📂 Cloud Archive: '{csv_filename}' successfully saved directly to your GitHub repository.")
                        else:
                            st.warning(f"⚠️ App processed data but failed archiving to GitHub repository. Info: {upload_res.text}")
                    except Exception as g_err:
                        st.warning(f"⚠️ GitHub integration config check skipped or failed: {g_err}")
                    
                    # --- WEB ACTION DASHBOARD ---
                    st.subheader("3. Export Processed Data")
                    
                    btn_col1, btn_col2, btn_col3 = st.columns(3)
                    
                    with btn_col1:
                        # Master file browser download button
                        st.download_button(
                            label="📥 1. Download CSV Locally",
                            data=csv_bytes,
                            file_name=csv_filename,
                            mime="text/csv",
                            type="primary",
                            use_container_width=True
                        )
                    
                    with btn_col2:
                        # Construct safe mailto browser trigger
                        email_recipient = "Luke.oreilly@kpsnacks.com"
                        email_subject = f"{extra_info_1} Pallet Count by SKU"
                        email_body = f"Hi Luke,\n\nHere is the pallet count breakdown summarized by unique SKU for Load Ref: {extra_info_1}\n\n{clean_text_summary}\n\nRegards,\nWMS Automated Conversion Engine"
                        mailto_link = f"mailto:{email_recipient}?subject={urllib.parse.quote(email_subject)}&body={urllib.parse.quote(email_body)}"
                        st.link_button("📧 2. Open Pre-Filled Email", url=mailto_link, use_container_width=True)
                        
                    with btn_col3:
                        # Dynamic button that routes directly to your online repository's saved folder layout
                        repo_view_url = f"https://github.com{st.secrets['github_username']}/{st.secrets['github_repo']}/tree/main/saved_loads"
                        st.link_button("📋 3. Access Repository Archive", url=repo_view_url, use_container_width=True)
                    
                    # Display Luke's Pallet Summary Metrics Grid right on the page
                    st.write("---")
                    st.subheader(f"📊 {extra_info_1} Pallet Count by SKU")
                    st.dataframe(pd.DataFrame([sku_counts.values], columns=sku_counts.index), use_container_width=True)
                    
                    # Show the absolute converted output preview below everything
                    st.write("---")
                    st.subheader("🔍 Converted Master Data Preview")
                    st.dataframe(output_df, use_container_width=True)
                        
        except Exception as e:
