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
# CONFIGURATION
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
# HELPER FUNCTIONS
# =========================================================

def is_invalid_summary_row(row):
    """
    Removes obvious WMS summary/footer rows.
    """

    value = row.get("SSCC Code", "")

    if pd.isna(value):
        return True

    value = str(value).strip().lower()

    if not value:
        return True

    if "total" in value:
        return True

    if value in {
        "na",
        "n/a",
        "n / a",
        "n.a.",
        "n.a",
    }:
        return True

    return False


def contains_explicit_na(value):
    """
    Returns True only when a cell explicitly contains
    an NA marker.

    Examples:

        NA       -> True
        N/A      -> True
        N-A      -> True
        Banana   -> False
        NAT123   -> False
    """

    if pd.isna(value):
        return False

    cleaned = str(value).strip().lower()

    normalised = re.sub(
        r"[\s#\/\\\-_.]+",
        "",
        cleaned,
    )

    return normalised == "na"


def sanitise_filename(filename):
    """
    Creates a safe filename.
    """

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

    if filename in {
        "",
        ".",
        "..",
    }:
        return "wms_output"

    return filename


def get_github_settings():
    """
    Reads GitHub settings from Streamlit Secrets.

    Required secrets:

        github_token
        github_username
        github_repo
    """

    try:
        token = st.secrets["github_token"]
        username = st.secrets["github_username"]
        repo = st.secrets["github_repo"]

    except Exception as exc:

        raise RuntimeError(
            "GitHub settings are missing from Streamlit Secrets. "
            "Required secrets are: github_token, "
            "github_username and github_repo."
        ) from exc

    token = str(token).strip()
    username = str(username).strip().strip("/")
    repo = str(repo).strip().strip("/")

    if not token:
        raise RuntimeError(
            "github_token is empty."
        )

    if not username:
        raise RuntimeError(
            "github_username is empty."
        )

    if not repo:
        raise RuntimeError(
            "github_repo is empty."
        )

    return token, username, repo


# =========================================================
# GITHUB UPLOAD
# =========================================================

def upload_to_github_archive(
    csv_bytes,
    csv_filename,
):
    """
    Uploads the processed CSV to:

        saved_loads/<filename>.csv

    Handles both:

        - creating a new file
        - updating an existing file
    """

    try:

        token, username, repo = get_github_settings()

        # -------------------------------------------------
        # GITHUB CONTENTS API URL
        # -------------------------------------------------

        api_url = (
            "https://api.github.com/repos/"
            f"{urllib.parse.quote(username, safe='')}/"
            f"{urllib.parse.quote(repo, safe='')}/"
            "contents/saved_loads/"
            f"{urllib.parse.quote(csv_filename, safe='')}"
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        encoded_content = base64.b64encode(
            csv_bytes
        ).decode("utf-8")

        # -------------------------------------------------
        # CHECK WHETHER FILE ALREADY EXISTS
        # -------------------------------------------------

        check_response = requests.get(
            api_url,
            headers=headers,
            timeout=20,
        )

        payload = {
            "message": (
                f"Archive automated reformat entry: "
                f"{csv_filename}"
            ),
            "content": encoded_content,
        }

        # -------------------------------------------------
        # EXISTING FILE
        # -------------------------------------------------

        if check_response.status_code == 200:

            existing_file = check_response.json()

            existing_sha = existing_file.get(
                "sha"
            )

            if not existing_sha:

                st.error(
                    "❌ GitHub found the archive file, "
                    "but no file SHA was returned."
                )

                return False

            # GitHub requires the SHA when updating
            # an existing file.
            payload["sha"] = existing_sha

        # -------------------------------------------------
        # FILE DOES NOT EXIST
        # -------------------------------------------------

        elif check_response.status_code == 404:

            # No SHA is required when creating a new file.
            pass

        # -------------------------------------------------
        # ERROR CHECKING EXISTING FILE
        # -------------------------------------------------

        else:

            try:
                github_error = check_response.json()

            except ValueError:
                github_error = check_response.text

            st.error(
                "❌ GitHub rejected the archive check.\n\n"
                f"HTTP status: "
                f"{check_response.status_code}\n\n"
                f"GitHub response:\n"
                f"{github_error}"
            )

            return False

        # -------------------------------------------------
        # UPLOAD / UPDATE FILE
        # -------------------------------------------------

        upload_response = requests.put(
            api_url,
            headers=headers,
            json=payload,
            timeout=30,
        )

        # -------------------------------------------------
        # SUCCESS
        # -------------------------------------------------

        if upload_response.status_code in {
            200,
            201,
        }:

            st.success(
                f"📂 Cloud Archive: "
                f"'{csv_filename}' successfully "
                "saved to your GitHub repository."
            )

            return True

        # -------------------------------------------------
        # DETAILED GITHUB ERROR
        # -------------------------------------------------

        try:
            github_error = upload_response.json()

        except ValueError:
            github_error = upload_response.text

        st.error(
            "❌ GitHub rejected the archive upload.\n\n"
            f"HTTP status: "
            f"{upload_response.status_code}\n\n"
            f"GitHub response:\n"
            f"{github_error}"
        )

        return False

    # -----------------------------------------------------
    # NETWORK ERROR
    # -----------------------------------------------------

    except requests.RequestException as exc:

        st.error(
            "❌ The app could not connect to GitHub.\n\n"
            f"Connection error: {exc}"
        )

        return False

    # -----------------------------------------------------
    # OTHER GITHUB ERROR
    # -----------------------------------------------------

    except Exception as exc:

        st.error(
            "❌ GitHub integration error.\n\n"
            f"{exc}"
        )

        return False


# =========================================================
# PARSE WMS DATA
# =========================================================

def parse_wms_data(pasted_text):
    """
    Reads pasted WMS data.

    Supports:

        - tab-separated data
        - comma-separated CSV
    """

    text = pasted_text.strip()

    if not text:

        raise ValueError(
            "Please paste some WMS data first."
        )

    separator = (
        "\t"
        if "\t" in text
        else ","
    )

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
# INPUT SECTION
# =========================================================

st.subheader(
    "1. Additional Information"
)

col1, col2 = st.columns(2)


with col1:

    extra_info_1 = st.text_input(
        "Enter Load Ref "
        "(Names your file and repeats in "
        "Load Ref column):"
    )


with col2:

    jde_order_ref = st.text_input(
        "Enter JDE Order Ref "
        "(Populates the Movement column):"
    )


# =========================================================
# WMS DATA INPUT
# =========================================================

st.subheader(
    "2. Paste WMS Data Below"
)

st.caption(
    "Include your header row! Copy the entire "
    "grid from your WMS "
    "(Ctrl+A → Ctrl+C) and paste it below "
    "(Ctrl+V). Column order does not matter."
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

if st.button(
    "Process & Generate Files",
    type="primary",
):

    # -----------------------------------------------------
    # BASIC VALIDATION
    # -----------------------------------------------------

    if not pasted_text.strip():

        st.error(
            "Please paste some data into the "
            "text box first."
        )

        st.stop()

    if (
        not extra_info_1.strip()
        or not jde_order_ref.strip()
    ):

        st.warning(
            "Please fill out both the "
            "Load Ref and JDE Order Ref "
            "fields above."
        )

        st.stop()

    # =====================================================
    # MAIN PROCESSING TRY BLOCK
    # =====================================================

    try:

        # -------------------------------------------------
        # READ WMS DATA
        # -------------------------------------------------

        df_raw = parse_wms_data(
            pasted_text
        )

        # -------------------------------------------------
        # CHECK REQUIRED COLUMNS
        # -------------------------------------------------

        missing_cols = [
            column
            for column in EXPECTED_WMS_COLUMNS
            if column not in df_raw.columns
        ]

        if missing_cols:

            st.error(
                "❌ Missing expected WMS columns:\n\n"
                + "\n".join(
                    f"- {column}"
                    for column in missing_cols
                )
                + "\n\nPlease check that your "
                "WMS header names match."
            )

            st.stop()

        # -------------------------------------------------
        # REMOVE COMPLETELY EMPTY ROWS
        # -------------------------------------------------

        df_clean = (
            df_raw
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

        original_row_count = len(
            df_clean
        )

        # -------------------------------------------------
        # REMOVE SUMMARY / TOTAL ROWS
        # -------------------------------------------------

        summary_rows_mask = (
            df_clean.apply(
                is_invalid_summary_row,
                axis=1,
            )
        )

        summary_rows_removed = int(
            summary_rows_mask.sum()
        )

        df_clean = df_clean[
            ~summary_rows_mask
        ].copy()

        # -------------------------------------------------
        # REMOVE EXPLICIT NA ROWS
        # -------------------------------------------------

        row_has_explicit_na = (
            df_clean.apply(
                lambda row: row.map(
                    contains_explicit_na
                ).any(),
                axis=1,
            )
        )

        na_rows_removed = int(
            row_has_explicit_na.sum()
        )

        df_filtered = df_clean[
            ~row_has_explicit_na
        ].copy()

        total_d