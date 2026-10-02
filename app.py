import streamlit as st
import pandas as pd
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import re

st.set_page_config(page_title="WMS Web Reformatter", layout="wide")
st.title("📦 kp ponte to campeys sscc sender")

# 1. Inputs for the 2 pieces of information
st.subheader("1. load header ")
col1, col2 = st.columns(2)
with col1:
    extra_info_1 = st.text_input("Enter Field 1 (e.g., Batch ID / File Name):")
with col2:
    extra_info_2 = st.text_input("Enter Field 2:")

# Email Input Field
st.subheader("2. Recipient Email")
recipient_email = st.text_input("Send final CSV to:")

# 2. Direct copy-paste grid
st.subheader("3. Paste WMS Data Below")
st.caption("Click the first cell and press Ctrl+V to paste directly from your WMS grid.")

# Change these to match your exact WMS headers
EXPECTED_INPUT_COLUMNS = ["WMS_ID", "SKU", "Qty", "Customer"] 
df_template = pd.DataFrame(columns=EXPECTED_INPUT_COLUMNS)

pasted_data = st.data_editor(
    df_template, 
    num_rows="dynamic", 
    use_container_width=True,
    key="wms_grid"
)

# 3. Process & Email Logic
if st.button("Process & Email CSV", type="primary"):
    if pasted_data.empty or pasted_data.dropna(how='all').empty:
        st.error("Please paste some data into the grid first.")
    elif not extra_info_1 or not extra_info_2 or not recipient_email:
        st.warning("Please fill out all input fields and the recipient email.")
    else:
        # Drop completely blank rows
        df_clean = pasted_data.dropna(how='all').copy()
        
        # --- IGNORE N/A VALUES ---
        # Convert all grid data to strings, strip whitespace, and check for text matching 'n/a' or 'N/A'
        na_mask = df_clean.astype(str).map(lambda x: x.strip().lower() in ['n/a', 'na'])
        
        # Also catch natural empty values/NaNs that pandas detects
        nan_mask = df_clean.isna()
        
        # Combine masks: Row is removed if ANY cell contains 'n/a' or is completely empty
        row_has_na = (na_mask | nan_mask).any(axis=1)
        
        # Keep only rows that DO NOT have an n/a or blank
        df_filtered = df_clean[~row_has_na].copy()
        
        if df_filtered.empty:
            st.error("Filtering complete: All pasted rows contained 'n/a' or missing data. Nothing to send.")
        else:
            # Inject the data into every line item
            df_filtered["Extra_Field_1"] = extra_info_1
            df_filtered["Extra_Field_2"] = extra_info_2
            
            # Change this list to your exact required final layout
            FINAL_COLUMN_ORDER = ["Extra_Field_1", "WMS_ID", "Extra_Field_2", "SKU", "Qty"]
            
            try:
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
                msg['Subject'] = f"Processed WMS Report - {extra_info_1}"
                msg.attach(MIMEText("Please find attached the reformatted WMS CSV data (n/a items removed).", 'plain'))
                
                # Attach CSV data with the new dynamic filename
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
                
            except KeyError as e:
                st.error(f"Mapping error. Check your WMS headers. Missing: {e}")
            except Exception as e:
                st.error(f"Email failed to send. Check your email credentials. Error: {e}")
