import streamlit as st
import pandas as pd
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import re
from datetime import datetime
import pytz
import io

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

# Email Input Field (Pre-filled with default recipient)
st.subheader("2. Recipient Email")
recipient_email = st.text_input("Send final CSV to:", value="Luke.oreilly@kpsnacks.com")

# 2. Raw Text Paste Area
st.subheader("3. Paste WMS Data Below")
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

# 3. Process & Email Logic
if st.button("Process & Email CSV", type="primary"):
    if not pasted_text.strip():
        st.error("Please paste some data into the text box first.")
    elif not extra_info_1 or not jde_order_ref or not recipient_email:
        st.warning("Please fill out the Load Ref, JDE Order Ref, and the recipient email.")
    else:
        try:
            # Detect whether data is tab-separated or comma-separated
            separator = '\t' if '\t' in pasted_text else ','
            
            # Read the pasted text dynamically into a DataFrame
            df_raw = pd.read_csv(io.StringIO(pasted_text.strip()), sep=separator)
            
            # Clean up column names from any accidental trailing whitespace
            df_raw.columns = df_raw.columns.str.strip()
            
            # Verify all 9 required columns are present in the pasted text
            missing_cols = [col for col in EXPECTED_WMS_COLUMNS if col not in df_raw.columns]
            
            if missing_cols:
                st.error(f"❌ Missing expected WMS columns in the pasted data: {missing_cols}. Please check your headers match exactly.")
            else:
                # Drop rows that are completely empty across every cell
                df_clean = df_raw.dropna(how='all').copy()
                
                # --- PROTECTION 1: DROP INVALID WMS SUMMARY ROWS ---
                def is_invalid_summary_row(row):
                    sscc_val = str(row.get("SSCC Code", "")).strip().lower()
                    if not sscc_val or pd.isna(row.get("SSCC Code")):
                        return True
                    if "total" in sscc_val or sscc_val in ["na", "n/a", "n / a"]:
                        return True
                    return False

                summary_rows_mask = df_clean.apply(is_invalid_summary_row, axis=1)
                df_clean = df_clean[~summary_rows_mask]
                
                # --- PROTECTION 2: AGGRESSIVE FILTERING FOR ANY 'NA' VARIATION ---
                def contains_explicit_na(val):
                    if pd.isna(val):
                        return False  # Leave natural empty/blank cells alone
                    
                    # Convert to a clean lowercase string with stripped punctuation
                    clean_str = re.sub(r'[\s#\/\\\-_.]', '', str(val)).lower()
                    return "na" in clean_str

                # Identify rows containing written 'na' labels
                row_has_explicit_na = df_clean.map(contains_explicit_na).any(axis=1)
                
                # Deletes the whole row if any cell contains an explicit 'na' text fragment
                df_filtered = df_clean[~row_has_explicit_na].copy()
                
                # Total dropped tracking count
                total_dropped = summary_rows_mask.sum() + row_has_explicit_na.sum()
                
                if df_filtered.empty:
                    st.error("Filtering complete: All pasted rows contained explicit 'na' values, summary blocks, or were entirely empty. Nothing to send.")
                else:
                    # Get current date and time in UK/London time zone
                    local_tz = pytz.timezone("Europe/London")
                    current_time = datetime.now(local_tz).strftime("%d/%m/%Y %H:%M")
                    
                    # --- CALCULATE UNIQUE SKU COUNTS FOR SUMMARY EMAIL ---
                    # Safely convert column to string and count occurrences of each SKU
                    sku_counts = df_filtered["Item Code"].astype(str).str.strip().value_counts()
                    
                    # Transform the counts series into a single-row matrix for a horizontal table look
                    summary_df = pd.DataFrame([sku_counts.values], columns=sku_counts.index)
                    
                    # Inject metadata headers into main data sheet
                    df_filtered["Load Ref"] = extra_info_1
                    df_filtered["Date"] = current_time
                    df_filtered["Movement"] = jde_order_ref
                    
                    # --- FINAL OUTPUT LAYOUT SPECIFICATION ---
                    FINAL_COLUMN_ORDER = [
                        "Load Ref",            
                        "Date",                
                        "SSCC Code",
                        "Item Code",
                        "Description",
                        "Units",
                        "Rotation Date",
                        "Batch",
                        "Movement",            
                        "Status",
                        "Positive Release",
                        "Catch Weight To Remove"
                    ]
                    
                    output_df = df_filtered[FINAL_COLUMN_ORDER]
                    
                    st.success(f"🎉 Data successfully processed! (Safely removed {total_dropped} invalid summary rows or 'na' lines)")
                    st.dataframe(output_df, use_container_width=True)
                    
                    # Create a clean, safe filename from the Load Ref field
                    safe_filename = re.sub(r'[\\/*?:"<>|]', "", extra_info_1).strip()
                    if not safe_filename:
                        safe_filename = "wms_output"
                    csv_filename = f"{safe_filename}.csv"
                    
                    # Save to temporary CSV string
                    csv_data = output_df.to_csv(index=False)
                    
                    # Fetch credentials from Streamlit secrets background
                    SMTP_SERVER = st.secrets["smtp"]["server"]
                    SMTP_PORT = int(st.secrets["smtp"]["port"])
                    SENDER_EMAIL = st.secrets["smtp"]["sender"]
                    SENDER_PASSWORD = st.secrets["smtp"]["password"]
                    
                    # Open connection server session
                    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                        server.starttls()
                        server.login(SENDER_EMAIL, SENDER_PASSWORD)
                        
                        # --- EMAIL 1: MASTER DATA CSV DISPATCH ---
                        msg1 = MIMEMultipart()
                        msg1['From'] = SENDER_EMAIL
                        msg1['To'] = recipient_email
                        msg1['Subject'] = f"Campeys SSCC Report - {extra_info_1}"
                        msg1.attach(MIMEText(f"Please find attached the reformatted KP to Campeys SSCC data for Load Ref: {extra_info_1}.", 'plain'))
                        
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(csv_data.encode('utf-8'))
                        encoders.encode_base64(part)
                        part.add_header('Content-Disposition', f"attachment; filename={csv_filename}")
                        msg1.attach(part)
                        
                        server.sendmail(SENDER_EMAIL, recipient_email, msg1.as_string())
                        st.success(f"📧 Master CSV file dispatched to {recipient_email}!")
                        
                        # --- EMAIL 2: HORIZONTAL SUMMARY SKU PALLET TABLE ---
                        msg2 = MIMEMultipart()
                        msg2['From'] = SENDER_EMAIL
                        msg2['To'] = "Luke.oreilly@kpsnacks.com"
                        msg2['Subject'] = f"{extra_info_1} Pallet Count by SKU"
                        
                        # Generate HTML table strings without conflicting curly braces
                        html_table = summary_df.to_html(index=False, border=1)
                        
                        # Inline styling safely introduced without CSS block curly syntax conflicts
                        html_table = html_table.replace('class="dataframe"', 'style="border-collapse: collapse; width: 100%; font-family: sans-serif; text-align: center;"')
                        html_table = html_table.replace('<th>', '<th style="border: 1px solid #dddddd; padding: 12px; background-color: #f2f2f2; font-weight: bold;">')
                        html_table = html_table.replace('<td>', '<td style="border: 1px solid #dddddd; padding: 12px;">')
                        
                        email_body = f"""
                        <html>
                          <body>
                            <p>Hi Luke,</p>
