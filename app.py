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
import socket

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

# 3. Process & Email Logic
if st.button("Process & Email CSV", type="primary"):
    if not pasted_text.strip():
        st.error("Please paste some data into the text box first.")
    elif not extra_info_1 or not jde_order_ref or not recipient_email:
        st.warning("Please fill out the Load Ref, JDE Order Ref, and the recipient email.")
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
                st.error(f"❌ Missing expected WMS columns: {missing_cols}")
                st.stop()
                
            # Filter structural rows
            df_clean = df_raw.dropna(how='all').copy()
            summary_rows_mask = df_clean.apply(is_invalid_summary_row, axis=1)
            df_clean = df_clean[~summary_rows_mask]
            
            # Filter explicit text strings
            row_has_explicit_na = df_clean.map(contains_explicit_na).any(axis=1)
            df_filtered = df_clean[~row_has_explicit_na].copy()
            total_dropped = summary_rows_mask.sum() + row_has_explicit_na.sum()
            
            if df_filtered.empty:
                st.error("Filtering complete: No valid data left to dispatch.")
                st.stop()
                
            # Time zone tracking
            local_tz = pytz.timezone("Europe/London")
            current_time = datetime.now(local_tz).strftime("%d/%m/%Y %H:%M")
            
            # Generate SKU summary row segments
            sku_counts = df_filtered["Item Code"].astype(str).str.strip().value_counts()
            headers_html = "".join([f'<th style="border: 1px solid #dddddd; padding: 12px; background-color: #f2f2f2; font-weight: bold; text-align: center;">{sku}</th>' for sku in sku_counts.index])
            values_html = "".join([f'<td style="border: 1px solid #dddddd; padding: 12px; text-align: center;">{count}</td>' for count in sku_counts.values])
            html_table_string = '<table style="border-collapse: collapse; width: 100%; font-family: sans-serif; margin-top: 15px;"><thead><tr>' + headers_html + '</tr></thead><tbody><tr>' + values_html + '</tr></tbody></table>'
            
            # Compile main output layout data sheet
            df_filtered["Load Ref"] = extra_info_1
            df_filtered["Date"] = current_time
            df_filtered["Movement"] = jde_order_ref
            
            FINAL_COLUMN_ORDER = ["Load Ref", "Date", "SSCC Code", "Item Code", "Description", "Units", "Rotation Date", "Batch", "Movement", "Status", "Positive Release", "Catch Weight To Remove"]
            output_df = df_filtered[FINAL_COLUMN_ORDER]
            
            st.success(f"🎉 Data successfully processed! (Dropped {total_dropped} rows)")
            st.dataframe(output_df, use_container_width=True)
            
            # Save data sheet properties
            safe_filename = re.sub(r'[\\/*?:"<>|]', "", extra_info_1).strip()
            csv_filename = f"{safe_filename}.csv" if safe_filename else "wms_output.csv"
            csv_data = output_df.to_csv(index=False)
            
            # Fetch background secrets tokens
            SMTP_SERVER = st.secrets["smtp"]["server"]
            SMTP_PORT = int(st.secrets["smtp"]["port"])
            SENDER_EMAIL = st.secrets["smtp"]["sender"]
            SENDER_PASSWORD = st.secrets["smtp"]["password"]
            
            # Direct network wrapper setup for handling IP strings safely over SSL
            # By overriding server hostname checks, Python connects directly to Google's hardware
            context = smtplib.ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = smtplib.ssl.CERT_NONE
            
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                
                # Email 1: Master CSV Document
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
                st.success("📧 Master CSV dispatched successfully!")
                
                # Email 2: Inline HTML Metric Table
                msg2 = MIMEMultipart()
                msg2['From'] = SENDER_EMAIL
                msg2['To'] = "Luke.oreilly@kpsnacks.com"
                msg2['Subject'] = f"{extra_info_1} Pallet Count by SKU"
                
                email_body = "<html><body><p>Hi Luke,</p><p>Here is the pallet count breakdown summarized by unique SKU for <strong>Load Ref: " + extra_info_1 + "</strong>:</p>" + html_table_string + "<p><br>Regards,<br>WMS Automated Conversion Engine</p></body></html>"
                msg2.attach(MIMEText(email_body, 'html'))
                server.sendmail(SENDER_EMAIL, "Luke.oreilly@kpsnacks.com", msg2.as_string())
                st.success("📊 Summary matrix tables delivered directly to Luke!")
                
        except Exception as e:
            st.error(f"An execution issue occurred with the email system: {e}")
