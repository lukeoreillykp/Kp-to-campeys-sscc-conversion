import base64
import io
import re
import urllib.parse
from datetime import datetime

import pandas as pd
import pytz
import requests
import streamlit as st


# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="KP to Campeys SSCC Sender",
    layout="wide",
)

st.title("📦 KP to Campeys SSCC Sender")


# =========================================================
# COLUMN CONFIGURATION
# =========================================================

EXPECTED_WMS_COLUMNS = [
    "SSCC Code",
    "Item Code",
    "Description",
    "Units",
    "Rotation Date",
    "Batch",
    "Status",
    "Positive Release",
    "Catch Weight To Remove",
]

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
    "Catch Weight To Remove",
]


# =========================================================
# FUNCTIONS
# =========================================================

def get_github_settings():
    """Get GitHub settings from Streamlit secrets."""

    token = st.secrets.get("github_token")
    username = st.secrets.get("github_username")
    repo = st.secrets.get("github_repo")

    if not token:
        raise ValueError(
            "Missing github_token in Streamlit Secrets."
        )

    if not username:
        raise ValueError(
            "Missing github_username in Streamlit Secrets."
        )

    if not repo:
        raise ValueError(
            "Missing github_repo in Streamlit Secrets."
        )

    return (
        str(token).strip(),
        str(username).strip().strip("/"),
        str(repo).strip().strip("/"),
    )


def clean_filename(filename):
    """Create a safe filename."""

    filename = str(filename).strip()

    filename = re.sub(
        r'[\\/*?:"<>|]',
        "",
        filename,
    )

    filename = re.sub(
        r"\s+",
        " ",
        filename,
    )

    if not filename:
        filename = "wms_output"

    if not filename.lower().endswith(".csv"):
        filename += ".csv"

    return filename


def is_summary_row(value):
    """Identify obvious summary/footer rows."""

    if pd.isna(value):
        return True

    value = str(value).strip().lower()

    if value == "":
        return True

    if "total" in value:
        return True

    if value in (
        "na",
        "n/a",
        "n-a",
        "n.a.",
        "n.a",
    ):
        return True

    return False


def is_explicit_na(value):
    """
    Only identify actual NA values.

    Does NOT incorrectly remove words such as Banana.
    """

    if pd.isna(value):
        return False

    value = str(value).strip().lower()

    cleaned = re.sub(
        r"[\s./\\#_-]+",
        "",
        value,
    )

    return cleaned == "na"


def read_wms_data(text):
    """Read pasted WMS data."""

    if not text or not text.strip():
        raise ValueError(
            "No WMS data was supplied."
        )

    text = text.strip()

    if "\t" in text:
        separator = "\t"
    else:
        separator = ","

    df = pd.read_csv(
        io.StringIO(text),
        sep=separator,
        dtype=str,
        keep_default_na=False,
    )

    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
    )

    return df


def upload_to_github(csv_bytes, filename):
    """
    Upload CSV to:

    saved_loads/<filename>

    Returns:
        True  = successful
        False = unsuccessful
    """

    token, username, repo = get_github_settings()

    encoded_username = urllib.parse.quote(
        username,
        safe="",
    )

    encoded_repo = urllib.parse.quote(
        repo,
        safe="",
    )

    encoded_filename = urllib.parse.quote(
        filename,
        safe="",
    )

    url = (
        "https://api.github.com/repos/"
        f"{encoded_username}/"
        f"{encoded_repo}/"
        "/contents/saved_loads/"
        f"{encoded_filename}"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    encoded_file = base64.b64encode(
        csv_bytes
    ).decode("utf-8")

    # -----------------------------------------------------
    # CHECK IF FILE ALREADY EXISTS
    # -----------------------------------------------------

    try:
        check = requests.get(
            url,
            headers=headers,
            timeout=20,
        )
    except requests.RequestException as error:
        st.error(
            "❌ Could not connect to GitHub.\n\n"
            f"{error}"
        )
        return False

    # -----------------------------------------------------
    # PREPARE GITHUB REQUEST
    # -----------------------------------------------------

    payload = {
        "message": (
            f"Archive automated reformat entry: "
            f"{filename}"
        ),
        "content": encoded_file,
    }

    # Existing file.
    if check.status_code == 200:

        try:
            existing = check.json()
        except ValueError:
            st.error(
                "❌ GitHub returned an invalid response "
                "when checking the existing file."
            )
            return False

        sha = existing.get("sha")

        if not sha:
            st.error(
                "❌ GitHub found the file but did not "
                "return its SHA."
            )
            return False

        payload["sha"] = sha

    # File doesn't exist.
    elif check.status_code == 404:
        pass

    # Any other response.
    else:

        try:
            error_details = check.json()
        except ValueError:
            error_details = check.text

        st.error(
            "❌ GitHub rejected the archive check.\n\n"
            f"HTTP status: {check.status_code}\n\n"
            f"GitHub response:\n{error_details}"
        )

        return False

    # -----------------------------------------------------
    # UPLOAD FILE
    # -----------------------------------------------------

    try:
        response = requests.put(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.RequestException as error:
        st.error(
            "❌ Could not connect to GitHub while "
            "uploading the archive.\n\n"
            f"{error}"
        )
        return False

    # -----------------------------------------------------
    # SUCCESS
    # -----------------------------------------------------

    if response.status_code in (200, 201):

        st.success(
            f"📂 Cloud Archive: {filename} "
            "successfully saved to GitHub."
        )

        return True

    # -----------------------------------------------------
    # DETAILED FAILURE
    # -----------------------------------------------------

    try:
        error_details = response.json()
    except ValueError:
        error_details = response.text

    st.error(
        "❌ GitHub rejected the archive upload.\n\n"
        f"HTTP status: {response.status_code}\n\n"
        f"GitHub response:\n{error_details}"
    )

    return False


# =========================================================
# INPUTS
# =========================================================

st.subheader(
    "1. Additional Information"
)

col1, col2 = st.columns(2)

with col1:
    load_ref = st.text_input(
        "Enter Load Ref "
        "(Names your file and repeats in Load Ref column):"
    )

with col2:
    jde_order_ref = st.text_input(
        "Enter JDE Order Ref "
        "(Populates the Movement column):"
    )


# =========================================================
# WMS INPUT
# =========================================================

st.subheader(
    "2. Paste WMS Data Below"
)

st.caption(
    "Include your header row. Copy the entire "
    "grid from your WMS and paste it below."
)

pasted_text = st.text_area(
    "Paste data here:",
    height=250,
    placeholder=(
        "SSCC Code\tItem Code\tDescription\tUnits..."
    ),
)


# =========================================================
# PROCESS BUTTON
# =========================================================

process_button = st.button(
    "Process & Generate Files",
    type="primary",
)


if process_button:

    # -----------------------------------------------------
    # VALIDATE INPUT
    # -----------------------------------------------------

    if not load_ref.strip():

        st.error(
            "Please enter a Load Ref."
        )

        st.stop()

    if not jde_order_ref.strip():

        st.error(
            "Please enter a JDE Order Ref."
        )

        st.stop()

    if not pasted_text.strip():

        st.error(
            "Please paste the WMS data."
        )

        st.stop()

    # -----------------------------------------------------
    # READ DATA
    # -----------------------------------------------------

    try:
        df = read_wms_data(
            pasted_text
        )
    except Exception as error:
        st.error(
            "❌ Could not read the WMS data.\n\n"
            f"{error}"
        )
        st.stop()

    # -----------------------------------------------------
    # CHECK COLUMNS
    # -----------------------------------------------------

    missing_columns = []

    for column in EXPECTED_WMS_COLUMNS:

        if column not in df.columns:
            missing_columns.append(column)

    if missing_columns:

        st.error(
            "❌ The following WMS columns are missing:\n\n"
            + "\n".join(
                f"- {column}"
                for column in missing_columns
            )
        )

        st.stop()

    # -----------------------------------------------------
    # REMOVE COMPLETELY EMPTY ROWS
    # -----------------------------------------------------

    df = (
        df
        .replace(
            r"^\s*$",
            pd.NA,
            regex=True,
        )
        .dropna(
            how="all"
        )
        .copy()
    )

    original_count = len(df)

    # -----------------------------------------------------
    # REMOVE SUMMARY ROWS
    # -----------------------------------------------------

    summary_mask = df[
        "SSCC Code"
    ].apply(
        is_summary_row
    )

    summary_removed = int(
        summary_mask.sum()
    )

    df = df[
        ~summary_mask
    ].copy()

    # -----------------------------------------------------
    # REMOVE ROWS CONTAINING EXPLICIT NA
    # -----------------------------------------------------

    na_mask = df.apply(
        lambda row: any(
            is_explicit_na(value)
            for value in row
        ),
        axis=1,
    )

    na_removed = int(
        na_mask.sum()
    )

    df = df[
        ~na_mask
    ].copy()

    # -----------------------------------------------------
    # CHECK REMAINING DATA
    # -----------------------------------------------------

    if df.empty:

        st.error(
            "❌ No valid rows remain after filtering."
        )

        st.stop()

    # -----------------------------------------------------
    # DATE / TIME
    # -----------------------------------------------------

    timezone = pytz.timezone(
        "Europe/London"
    )

    current_time = datetime.now(
        timezone
    ).strftime(
        "%d/%m/%Y %H:%M"
    )

    # -----------------------------------------------------
    # ADD OUTPUT COLUMNS
    # -----------------------------------------------------

    df["Load Ref"] = load_ref.strip()

    df["Date"] = current_time

    df["Movement"] = jde_order_ref.strip()

    # -----------------------------------------------------
    # CHECK OUTPUT COLUMNS
    # -----------------------------------------------------

    missing_output = []

    for column in FINAL_COLUMN_ORDER:

        if column not in df.columns:
            missing_output.append(column)

    if missing_output:

        st.error(
            "❌ Output columns are missing:\n\n"
            + "\n".join(
                f"- {column}"
                for column in missing_output
            )
        )

        st.stop()

    # -----------------------------------------------------
    # FINAL DATAFRAME
    # -----------------------------------------------------

    output_df = df[
        FINAL_COLUMN_ORDER
    ].copy()

    # -----------------------------------------------------
    # SKU COUNTS
    # -----------------------------------------------------

    sku_counts = (
        df["Item Code"]
        .astype(str)
        .str.strip()
        .replace(
            "",
            pd.NA,
        )
        .dropna()
        .value_counts()
    )

    # -----------------------------------------------------
    # DISPLAY RESULT
    # -----------------------------------------------------

    rows_removed = (
        summary_removed
        + na_removed
    )

    st.success(
        "🎉 WMS data successfully converted!"
    )

    st.caption(
        f"Input rows: {original_count} | "
        f"Rows removed: {rows_removed} | "
        f"Output rows: {len(output_df)}"
    )

    st.dataframe(
        output_df,
        use_container_width=True,
    )

    # -----------------------------------------------------
    # CREATE CSV
    # -----------------------------------------------------

    filename = clean_filename(
        load_ref
    )

    csv_text = output_df.to_csv(
        index=False
    )

    csv_bytes = csv_text.encode(
        "utf-8-sig"
    )

    # -----------------------------------------------------
    # GITHUB ARCHIVE
    # -----------------------------------------------------

    upload_to_github(
        csv_bytes,
        filename,
    )

    # =====================================================
    # EXPORT BUTTONS
    # =====================================================

    st.subheader(
        "3. Export Processed Data"
    )

    button1, button2, button3 = (
        st.columns(3)
    )

    # -----------------------------------------------------
    # DOWNLOAD
    # -----------------------------------------------------

    with button1:

        st.download_button(
            label=(
                "📥 1. Download CSV Locally"
            ),
            data=csv_bytes,
            file_name=filename,
            mime="text/csv",
            type="primary",
            use_container_width=True,
        )

    # -----------------------------------------------------
    # EMAIL
    # -----------------------------------------------------

    with button2:

        email_recipient = (
            "Luke.oreilly@kpsnacks.com"
        )

        email_subject = (
            f"{load_ref} Pallet Count by SKU"
        )

        summary_lines = []

        for sku, count in sku_counts.items():

            summary_lines.append(
                f"• SKU: {sku} -> Count: {count}"
            )

        sku_summary = "\n".join(
            summary_lines
        )

        email_body = (
            "Hi Luke,\n\n"
            "Here is the pallet count breakdown "
            "summarized by unique SKU for Load Ref: "
            f"{load_ref}\n\n"
            f"{sku_summary}\n\n"
            "Regards,\n"
            "WMS Automated Conversion Engine"
        )

        mailto_url = (
            f"mailto:{email_recipient}"
            f"?subject="
            f"{urllib.parse.quote(email_subject)}"
            f"&body="
            f"{urllib.parse.quote(email_body)}"
        )

        st.link_button(
            "📧 2. Open Pre-Filled Email",
            url=mailto_url,
            use_container_width=True,
        )

    # -----------------------------------------------------
    # REPOSITORY LINK
    # -----------------------------------------------------

    with button3:

        try:
            (
                _token,
                github_username,
                github_repo,
            ) = get_github_settings()

            repository_url = (
                "https://github.com/"
                f"{github_username}/"
                f"{github_repo}/tree/main/saved_loads"
            )

            st.link_button(
                "📋 3. Access Repository Archive",
                url=repository_url,
                use_container_width=True,
            )

        except Exception:

            st.info(
                "GitHub repository link unavailable."
            )

    # =====================================================
    # SKU SUMMARY
    # =====================================================

    st.write("---")

    st.subheader(
        f"📊 {load_ref} Pallet Count by SKU"
    )

    if not sku_counts.empty:

        summary_df = (
            sku_counts
            .rename(
                "Pallet Count"
            )
            .reset_index()
        )

        summary_df.columns = [
            "SKU",
            "Pallet Count",
        ]

        st.dataframe(
            summary_df,
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "No SKU counts were available."
        )

This version deliberately avoids the complicated nested structure that was causing the syntax problem.

One important thing: after replacing the file, make sure you delete everything currently in "app.py" first, then paste the code above. Don't paste it underneath the existing code.

Your Streamlit Secrets should remain:

github_token = "YOUR_GITHUB_TOKEN"
github_username = "lukeoreillykp"
github_repo = "Kp-to-campeys-sscc-conversion"

Once this version starts successfully, the GitHub section will give us the actual HTTP status and GitHub response if the upload is still rejected. That is the next thing we need to diagnose.