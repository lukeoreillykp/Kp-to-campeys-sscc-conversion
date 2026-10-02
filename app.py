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

# Title configuration
st.set_page_config(page_title="KP to Campeys SSCC Sender", layout="wide")
st.title("📦 KP to Campeys SSCC Sender")

# 1. Inputs for the 1 piece of additional information
st.subheader("1. Additional Information")
extra_info_1 = st.text_input("Enter Field 1 (e.g., Batch ID / File Name):")

# Email Input Field
st.subheader("2. Recipient Email")
recipient_email = st.text_input("Send final CSV to:")

# 2. Raw Text Paste Area
st.subheader("3. Paste WMS Data Below")
st.caption("Include your header row! Copy the entire grid from your WMS (Ctrl+A -> Ctrl+C) and paste it below (Ctrl+V). Column order does not matter.")

# Using a text area so headers are correctly read as structural data instead of data rows
pasted_text = st.text_area("Paste data here:", height=250, placeholder="WMS_ID\tSKU\tQty\tCustomer\n12345\tSKU-A\t10\tClient X")

# Define the exact column names your WMS uses (Update these if they change)
EXPECTED_WMS_COLUMNS = ["WMS_ID", "SKU", "Qty", "Customer"]

# 3. Process & Email Logic
if st.button("Process & Email CSV", type="primary"):
    if not pasted_text.strip():
        st.error("Please paste some data into the text box first.")
    elif not extra_info_1 or not recipient_email:
        st.warning("Please fill out the additional information field and the recipient email.")
    else:
        try:
            # Detect whether data is tab-separated (copied from Excel/WMS grids) or comma-separated
            separator = '\t' if '\t' in pasted_text else ','
            
            # Read the pasted text dynamically into a DataFrame
            # This automatically maps data rows to their corresponding header, regardless of column order
            df_raw = pd.read_csv(io.StringIO(pasted_text.strip()), sep=separator)
            
            # Clean up column names from any accidental trailing spaces
            df_raw.columns = df_raw.columns.str.strip()
            
            # Verify all required columns are present in the pasted text
            missing_cols = [col for col in EXPECTED_WMS_COLUMNS if col not in df_raw.columns]
            
            if missing_cols:
                st.error(f"❌ Missing expected WMS columns in the pasted data: {missing_cols}. Please check your headers.")
            else:
                # Drop completely blank rows
                df_clean = df_raw.dropna(how='all').copy()
                
                # --- IGNORE ANY CELL SAYING 'NA' ---
                na_mask = df_clean.astype(str).map(lambda x: x.strip().lower() in ['n/a', 'na'])
                nan_mask = df_clean.isna()
                row_has_na = (na_mask | nan_mask).any(axis=1)
                df_filtered = df_clean[~row_has_na].copy()
                
                if df_filtered.empty:
                    st.error("Filtering complete: All pasted rows contained 'n/a' or missing data. Nothing to send.")
                else:
                    # Get current date and time in UK/London time zone
                    local_tz = pytz.timezone("Europe/London")
                    current_time = datetime.now(local_tz).strftime("%d/%m/%Y %H:%M")
                    
                    # Inject new data into columns (using clean target headers)
                    df_filtered["Batch_ID"] = extra_info_1
                    df_filtered["Processed_Timestamp"] = current_time
                    
                    # --- FINAL OUTPUT LAYOUT SPECIFICATION ---
                    # Forces the output into this precise order, no matter how it was pasted
                    FINAL_COLUMN_ORDER = [
                        "Batch_ID",            # 1st Column
                        "Processed_Timestamp",  # 2nd Column
                        "WMS_ID", 
                        "SKU", 
                        "Qty", 
                        "Customer"
                    ]
                    
                    output_df = df_filtered[FINAL_COLUMN_ORDER]
                    
                    st.success(f"🎉 Data successfully processed! (Filtered out {row_has_na.sum()} rows containing 'n/a' or blanks)")
                    st.dataframe(output_df, use_container_width=True)
                    
                    # Create a clean, safe filename from the first field
                    safe_filename = re.sub(r'[\\/*?:"<>|]', "", extra_info_1).strip()
                    if not safe_filename:
                        safe_filename = "wms_output"
                    csv_filename = f"{safe_filename}.csv"
                    
                    # Save to temporary CSV string
                    csv_data = output_df.to_csv(index=False)
                    
                    # --- EMAIL AUTOMATION SECURE SETUP ---
                    SMTP_SERVER = st.secrets["smtp"]["server"]
                    SMTP_PORT = int(st.secrets["smtp"]["port"])
                    SENDER_EMAIL = st.secrets["smtp"]["sender"]
                    SENDER_PASSWORD = st.secrets["smtp"]["password"]
                    
                    # Build Email
                    msg = MIMEMultipart()
                    msg['From'] = SENDER_EMAIL
                    msg['To'] = recipient_email
                    msg['Subject'] = f"Campeys SSCC Report - {extra_info_1}"
                    msg.attach(MIMEText("Please find attached the reformatted KP to Campeys SSCC data.", 'plain'))
                    
                    # Attach CSV
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(csv_data.encode('utf-8'))
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f"attachment; filename={csv_filename}")
                    msg.attach(part)
                    
                    # Send via Cloud
                    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                        server.starttls()
                        server.login(SENDER_EMAIL, SENDER_PASSWORD)
                        server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
                        
                    st.success(f"📧 Email successfully sent with attachment '{csv_filename}' to {recipient_email}!")
                    
        except Exception as e:
            st.error(f"An error occurred during processing: {e}")
