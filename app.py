import base64
import io
import re
import urllib.parse
from datetime import datetime

import pandas as pd
import pytz
import requests
import streamlit as st


st.set_page_config(
    page_title="KP to Campeys SSCC Sender",
    layout="wide",
)

st.title("📦 KP to Campeys SSCC Sender")


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


def get_github_settings():
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
    try:
        (
            token,
            username,
            repo,
        ) = get_github_settings()

    except ValueError as error:
        st.error(
            "❌ GitHub configuration error:\n\n"
            + str(error)
        )
        return False

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
        + encoded_username
        + "/"
        + encoded_repo
        + "/contents/saved_loads/"
        + encoded_filename
    )

    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    encoded_file = base64.b64encode(
        csv_bytes
    ).decode("utf-8")

    try:
        check = requests.get(
            url,
            headers=headers,
            timeout=20,
        )

    except requests.RequestException as error:
        st.error(
            "❌ Could not connect to GitHub.\n\n"
            + str(error)
        )
        return False

    payload = {
        "message": (
            "Archive automated reformat entry: "
            + filename
        ),
        "content": encoded_file,
    }

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

    elif check.status_code == 404:
        pass

    else:
        try:
            error_details = check.json()

        except ValueError:
            error_details = check.text

        st.error(
            "❌ GitHub rejected the archive check.\n\n"
            + "HTTP status: "
            + str(check.status_code)
            + "\n\nGitHub response:\n"
            + str(error_details)
        )

        return False

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
            + str(error)
        )
        return False

    if response.status_code in (200, 201):
        st.success(
            "📂 Cloud Archive: "
            + filename
            + " successfully saved to GitHub."
        )
        return True

    try:
        error_details = response.json()

    except ValueError:
        error_details = response.text

    st.error(
        "❌ GitHub rejected the archive upload.\n\n"
        + "HTTP status: "
        + str(response.status_code)
        + "\n\nGitHub response:\n"
        + str(error_details)
    )

    return False


# ---------------------------------------------------------
# 1. ADDITIONAL INFORMATION
# ---------------------------------------------------------

st.subheader("1. Additional Information")

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


# ---------------------------------------------------------
# 2. WMS DATA INPUT
# ---------------------------------------------------------

st.subheader("2. Paste WMS Data Below")

st.caption(
    "Include your header row. Copy the entire grid "
    "from your WMS and paste it below."
)

pasted_text = st.text_area(
    "Paste data here:",
    height=250,
    placeholder=(
        "SSCC Code\tItem Code\tDescription\tUnits\t"
        "Rotation Date\tBatch\tStatus\tPositive Release\t"
        "Catch Weight To Remove"
    ),
)

process_button = st.button(
    "Process & Generate Files",
    type="primary",
)


# ---------------------------------------------------------
# 3. PROCESS DATA
# ---------------------------------------------------------

if process_button:

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

    try:
        df = read_wms_data(
            pasted_text
        )

    except Exception as error:
        st.error(
            "❌ Could not read the WMS data.\n\n"
            + str(error)
        )
        st.stop()

    # -----------------------------------------------------
    # Check required WMS columns
    # -----------------------------------------------------

    missing_columns = [
        column
        for column in EXPECTED_WMS_COLUMNS
        if column not in df.columns
    ]

    if missing_columns:
        st.error(
            "❌ The following WMS columns are missing:\n\n"
            + "\n".join(
                "- " + column
                for column in missing_columns
            )
        )
        st.stop()

    # -----------------------------------------------------
    # Remove completely blank rows
    # -----------------------------------------------------

    df = df.replace(
        r"^\s*$",
        pd.NA,
        regex=True,
    )

    df = df.dropna(
        how="all"
    ).copy()

    original_count = len(df)

    # -----------------------------------------------------
    # Remove summary / total rows
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
    # Remove rows containing explicit NA values
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
    # Check that valid rows remain
    # -----------------------------------------------------

    if df.empty:
        st.error(
            "❌ No valid rows remain after filtering."
        )
        st.stop()

    # -----------------------------------------------------
    # Add Load Ref, Date and Movement
    # -----------------------------------------------------

    timezone = pytz.timezone(
        "Europe/London"
    )

    current_time = datetime.now(
        timezone
    ).strftime(
        "%d/%m/%Y %H:%M"
    )

    df["Load Ref"] = load_ref.strip()
    df["Date"] = current_time
    df["Movement"] = jde_order_ref.strip()

    # -----------------------------------------------------
    # Check output columns
    # -----------------------------------------------------

    missing_output = [
        column
        for column in FINAL_COLUMN_ORDER
        if column not in df.columns
    ]

    if missing_output:
        st.error(
            "❌ Output columns are missing:\n\n"
            + "\n".join(
                "- " + column
                for column in missing_output
            )
        )
        st.stop()

    # -----------------------------------------------------
    # Create final output dataframe
    # -----------------------------------------------------

    output_df = df[
        FINAL_COLUMN_ORDER
    ].copy()

    # -----------------------------------------------------
    # Calculate SKU counts
    # -----------------------------------------------------

    sku_counts = (
        output_df["Item Code"]
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .value_counts()
    )

    rows_removed = (
        summary_removed
        + na_removed
    )

    # -----------------------------------------------------
    # Success message
    # -----------------------------------------------------

    st.success(
        "🎉 WMS data successfully converted!"
    )

    st.caption(
        "Input rows: "
        + str(original_count)
        + " | Rows removed: "
        + str(rows_removed)
        + " | Output rows: "
        + str(len(output_df))
    )

    # -----------------------------------------------------
    # Display processed data
    # -----------------------------------------------------

    st.dataframe(
        output_df,
        use_container_width=True,
    )

    # -----------------------------------------------------
    # Create CSV
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
    # Upload archive to GitHub
    # -----------------------------------------------------

    upload_to_github(
        csv_bytes,
        filename,
    )

    # -----------------------------------------------------
    # 4. EXPORT PROCESSED DATA
    # -----------------------------------------------------

    st.subheader(
        "3. Export Processed Data"
    )

    button1, button2, button3 = st.columns(3)

    # -----------------------------------------------------
    # Button 1 - Download CSV
    # -----------------------------------------------------

    with button1:
        st.download_button(
            label="📥 1. Download CSV Locally",
            data=csv_bytes,
            file_name=filename,
            mime="text/csv",
            type="primary",
            use_container_width=True,
        )

    # -----------------------------------------------------
    # Button 2 - Pre-filled Email
    # -----------------------------------------------------

    with button2:

        email_recipient = (
            "Luke.oreilly@kpsnacks.com"
        )

        email_subject = (
            str(load_ref)
            + " Pallet Count by SKU"
        )

        summary_lines = []

        for sku, count in sku_counts.items():
            summary_lines.append(
                "• SKU: "
                + str(sku)
                + " -> Count: "
                + str(count)
            )

        sku_summary = "\n".join(
            summary_lines
        )

        email_body = (
            "Hi Luke,\n\n"
            "Here is the pallet count breakdown "
            "summarized by unique SKU for Load Ref: "
            + str(load_ref)
            + "\n\n"
            + sku_summary
            + "\n\n"
            "Regards,\n"
            "WMS Automated Conversion Engine"
        )

        mailto_url = (
            "mailto:"
            + email_recipient
            + "?subject="
            + urllib.parse.quote(
                email_subject
            )
            + "&body="
            + urllib.parse.quote(
                email_body
            )
        )

        st.link_button(
            "📧 2. Open Pre-Filled Email",
            url=mailto_url,
            use_container_width=True,
        )

    # -----------------------------------------------------
    # Button 3 - GitHub Archive
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
                + github_username
                + "/"
                + github_repo
                + "/tree/main/saved_loads"
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

    # -----------------------------------------------------
    # 5. SKU SUMMARY
    # -----------------------------------------------------

    st.write("---")

    st.subheader(
        "📊 "
        + str(load_ref)
        + " Pallet Count by SKU"
    )

    if not sku_counts.empty:

        summary_df = (
            sku_counts
            .rename("Pallet Count")
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

