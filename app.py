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


# =========================================================
# GITHUB SETTINGS
# =========================================================

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


# =========================================================
# CLEAN FILENAME
# =========================================================

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


# =========================================================
# SUMMARY ROW CHECK
# =========================================================

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


# =========================================================
# EXPLICIT NA CHECK
# =========================================================

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


# =========================================================
# READ WMS DATA
# =========================================================

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


# =========================================================
# UPLOAD TO GITHUB
# =========================================================

def upload_to_github(csv_bytes, filename):

    # -----------------------------------------------------
    # Get GitHub settings
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Clean GitHub settings
    # -----------------------------------------------------

    username = username.strip().strip("/")
    repo = repo.strip().strip("/")
    filename = filename.strip().lstrip("/")

    # -----------------------------------------------------
    # GitHub file path
    # -----------------------------------------------------

    file_path = (
        "saved_loads/"
        + filename
    )

    encoded_username = urllib.parse.quote(
        username,
        safe="",
    )

    encoded_repo = urllib.parse.quote(
        repo,
        safe="",
    )

    encoded_file_path = urllib.parse.quote(
        file_path,
        safe="/",
    )

    url = (
        "https://api.github.com/repos/"
        + encoded_username
        + "/"
        + encoded_repo
        + "/contents/"
        + encoded_file_path
    )

    # -----------------------------------------------------
    # GitHub headers
    # -----------------------------------------------------

    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    encoded_file = base64.b64encode(
        csv_bytes
    ).decode("utf-8")

    # -----------------------------------------------------
    # Check whether file already exists
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
            + str(error)
        )
        return False

    # =====================================================
    # FILE ALREADY EXISTS
    # =====================================================

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
                "❌ GitHub found the existing file but "
                "did not return its SHA."
            )
            return False

        payload = {
            "message": (
                "Archive automated reformat entry: "
                + filename
            ),
            "content": encoded_file,
            "sha": sha,
        }

    # =====================================================
    # FILE DOES NOT EXIST
    # =====================================================

    elif check.status_code == 404:

        # A 404 can mean either:
        #
        # 1. The file does not exist yet.
        #    This is OK.
        #
        # 2. The repository cannot be found.
        #    This needs fixing.
        #
        # We therefore check the repository itself.

        repository_url = (
            "https://api.github.com/repos/"
            + encoded_username
            + "/"
            + encoded_repo
        )

        try:
            repository_check = requests.get(
                repository_url,
                headers=headers,
                timeout=20,
            )

        except requests.RequestException as error:
            st.error(
                "❌ Could not verify the GitHub repository.\n\n"
                + str(error)
            )
            return False

        # -------------------------------------------------
        # Repository could not be found
        # -------------------------------------------------

        if repository_check.status_code != 200:

            try:
                repository_error = (
                    repository_check.json()
                )

            except ValueError:
                repository_error = (
                    repository_check.text
                )

            st.error(
                "❌ GitHub repository could not be found.\n\n"
                + "Repository: "
                + username
                + "/"
                + repo
                + "\n\n"
                + "HTTP status: "
                + str(
                    repository_check.status_code
                )
                + "\n\nGitHub response:\n"
                + str(repository_error)
            )

            st.info(
                "Check your Streamlit Secrets. "
                "github_username must be the GitHub account "
                "or organisation that owns the repository, "
                "and github_repo must be the repository name."
            )

            return False

        # -------------------------------------------------
        # Repository exists, so create the file
        # -------------------------------------------------

        payload = {
            "message": (
                "Archive automated reformat entry: "
                + filename
            ),
            "content": encoded_file,
        }

    # =====================================================
    # OTHER GITHUB ERROR
    # =====================================================

    else:

        try:
            error_details = check.json()

        except ValueError:
            error_details = check.text

        st.error(
            "❌ GitHub rejected the archive check.\n\n"
            + "Repository: "
            + username
            + "/"
            + repo
            + "\n\n"
            + "Path: "
            + file_path
            + "\n\n"
            + "HTTP status: "
            + str(check.status_code)
            + "\n\nGitHub response:\n"
            + str(error_details)
        )

        return False

    # =====================================================
    # UPLOAD / UPDATE FILE
    # =====================================================

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

    # =====================================================
    # SUCCESS
    # =====================================================

    if response.status_code in (200, 201):

        st.success(
            "📂 Cloud Archive: "
            + filename
            + " successfully saved to GitHub."
        )

        return True

    # =====================================================
    # UPLOAD ERROR
    # =====================================================

    try:
        error_details = response.json()

    except ValueError:
        error_details = response.text

    st.error(
        "❌ GitHub rejected the archive upload.\n\n"
        + "Repository: "
        + username
        + "/"
        + repo
        + "\n\n"
        + "Path: "
        + file_path
        + "\n\n"
        + "HTTP status: "
        + str(response.status_code)
        + "\n\nGitHub response:\n"
        + str(error_details)
    )

    return False


# =========================================================
# 1. ADDITIONAL INFORMATION
# =========================================================

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


# =========================================================
# 2. WMS DATA INPUT
# =========================================================

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


# =========================================================
# 3. PROCESS DATA
# =========================================================

if process_button:

    # -----------------------------------------------------
    # Validate Load Ref
    # -----------------------------------------------------

    if not load_ref.strip():
        st.error(
            "Please enter a Load Ref."
        )
        st.stop()

    # -----------------------------------------------------
    # Validate JDE Order Ref
    # -----------------------------------------------------

    if not jde_order_ref.strip():
        st.error(
            "Please enter a JDE Order Ref."
        )
        st.stop()

    # -----------------------------------------------------
    # Validate WMS data
    # -----------------------------------------------------

    if not pasted_text.strip():
        st.error(
            "Please paste the WMS data."
        )
        st.stop()

    # -----------------------------------------------------
    # Read WMS data
    # -----------------------------------------------------

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
    # Check required columns
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
    # Remove blank rows
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
    # Remove explicit NA rows
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
    # Check valid rows
    # -----------------------------------------------------

    if df.empty:
        st.error(
            "❌ No valid rows remain after filtering."
        )
        st.stop()

    # -----------------------------------------------------
    # UK date/time
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
    # Add output fields
    # -----------------------------------------------------

    df["Load Ref"] = load_ref.strip()
    df["Date"] = current_time
    df["Movement"] = jde_order_ref.strip()

    # -----------------------------------------------------
    # Check final columns
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
    # Create final output
    # -----------------------------------------------------

    output_df = df[
        FINAL_COLUMN_ORDER
    ].copy()

    # -----------------------------------------------------
    # SKU counts
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
    # Success
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
    # Upload to GitHub
    # -----------------------------------------------------

    upload_to_github(
        csv_bytes,
        filename,
    )

    # =====================================================
    # 4. EXPORT PROCESSED DATA
    # =====================================================

    st.subheader(
        "3. Export Processed Data"
    )

    button1, button2, button3 = st.columns(3)

    # -----------------------------------------------------
    # Download CSV
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
    # Pre-filled email
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
    # GitHub archive link
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

    # =====================================================
    # 5. SKU SUMMARY
    # =====================================================

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
