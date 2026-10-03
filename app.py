import base64
import io
import re
import urllib.parse
from datetime import datetime

import pandas as pd
import pytz
import requests
import streamlit as st


# ============================================================
# CONFIGURATION
# ============================================================

EXPECTED_COLUMNS = [
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

FINAL_COLUMNS = [
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

GITHUB_OWNER = "lukeoreillykp"
GITHUB_REPO = "Kp-to-campeys-sscc-conversion"
GITHUB_BRANCH = "main"
GITHUB_FOLDER = "saved_loads"

SKU_HISTORY_PATH = "sku_counts_history.csv"
CONTACT_LIST_PATH = "campeys contact list.txt"

EMAIL_TO = "kpsnacks@campeys.co.uk"

EMAIL_CC = [
    "Luke.oreilly@kpsnacks.com",
    "grayson.swan@kpsnacks.com",
]

AUTOSTORE_URL = (
    "https://autostore-live.snacks.local/app"
)

CAMPEYS_LOAD_PLANNER_URL = (
    "https://intersnackgroup-my.sharepoint.com/:x:/r/personal/"
    "luke_oreilly_kpsnacks_com/_layouts/15/Doc.aspx?"
    "sourcedoc=%7B62A0E065-B812-45BE-9585-4DC4CCE5B70D%7D"
    "&file=Campey%27s%20collection%20Request%20Form%20(002).xlsx"
    "&action=default"
    "&mobileredirect=true"
    "&wdOrigin=APPHOME-WEB.DIRECT%2CAPPHOME-WEB.JUMPBACKIN"
    "&wdPreviousSession=1da539b6-e1ab-4c9c-9d8f-9cfdf123d44f"
    "&wdPreviousSessionSrc=AppHomeWeb"
    "&ct=1790975232806"
)


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="KP to Campeys",
    page_icon="📦",
    layout="wide",
)


# ============================================================
# STYLING
# ============================================================

st.markdown(
    """
    <style>

        .main-title {
            text-align: center;
            font-size: 42px;
            font-weight: 700;
            margin-top: 10px;
            margin-bottom: 5px;
        }

        .sub-title {
            text-align: center;
            font-size: 19px;
            margin-bottom: 30px;
            color: #555555;
        }

        .tool-icon {
            text-align: center;
            font-size: 48px;
            line-height: 1;
            margin-bottom: 8px;
        }

        .tool-title {
            text-align: center;
            font-size: 21px;
            font-weight: 700;
            margin-bottom: 8px;
        }

        .tool-description {
            text-align: center;
            font-size: 14px;
            color: #555555;
            min-height: 42px;
            margin-bottom: 12px;
        }

        div.stButton > button,
        div.stLinkButton > a {
            width: 100%;
            border-radius: 8px;
            min-height: 42px;
            font-weight: 600;
        }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# SESSION STATE / NAVIGATION
# ============================================================

if "page" not in st.session_state:
    st.session_state.page = "home"


def go_to(page_name):
    st.session_state.page = page_name


# ============================================================
# GITHUB FUNCTIONS
# ============================================================

def get_github_settings():
    """Read GitHub settings from Streamlit Secrets."""

    try:
        token = st.secrets["github_token"]

        username = st.secrets.get(
            "github_username",
            GITHUB_OWNER,
        )

        repo = st.secrets.get(
            "github_repo",
            GITHUB_REPO,
        )

        return token, username, repo

    except Exception:
        return None, None, None


def get_github_connection():
    """Validate GitHub token and repository."""

    token, username, repo = get_github_settings()

    if not token:
        raise RuntimeError(
            "GitHub token is not configured in Streamlit Secrets."
        )

    if not username:
        username = GITHUB_OWNER

    if not repo:
        repo = GITHUB_REPO

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    repo_url = (
        f"https://api.github.com/repos/"
        f"{username}/{repo}"
    )

    response = requests.get(
        repo_url,
        headers=headers,
        timeout=20,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"GitHub repository check failed "
            f"({response.status_code}): "
            f"{response.text}"
        )

    return headers, username, repo


def get_github_file(file_path):
    """Retrieve a file from GitHub."""

    headers, owner, repo = get_github_connection()

    encoded_path = urllib.parse.quote(
        file_path,
        safe="/",
    )

    url = (
        f"https://api.github.com/repos/"
        f"{owner}/{repo}/contents/{encoded_path}"
        f"?ref={GITHUB_BRANCH}"
    )

    response = requests.get(
        url,
        headers=headers,
        timeout=20,
    )

    if response.status_code == 404:
        return None, None

    if response.status_code != 200:
        raise RuntimeError(
            f"GitHub file lookup failed "
            f"({response.status_code}): "
            f"{response.text}"
        )

    data = response.json()

    if data.get("encoding") == "base64":

        content = base64.b64decode(
            data["content"].replace("\n", "")
        ).decode("utf-8-sig")

    else:

        download_url = data.get(
            "download_url"
        )

        if not download_url:
            raise RuntimeError(
                "GitHub file has no downloadable content."
            )

        file_response = requests.get(
            download_url,
            timeout=20,
        )

        if file_response.status_code != 200:
            raise RuntimeError(
                f"Unable to download GitHub file "
                f"({file_response.status_code})."
            )

        content = file_response.text

    return content, data


def list_saved_load_files():
    """List archived CSV files in the saved_loads GitHub folder."""
    try:
        headers, owner, repo = get_github_connection()
        url = (
            f"https://api.github.com/repos/"
            f"{owner}/{repo}/contents/{GITHUB_FOLDER}"
        )

        response = requests.get(
            url,
            headers=headers,
            timeout=20,
        )

        if response.status_code != 200:
            return []

        items = response.json()
        if not isinstance(items, list):
            return []

        return [
            item["name"]
            for item in items
            if item.get("type") == "file"
            and str(item.get("name", "")).lower().endswith(".csv")
        ]

    except Exception:
        return []


def find_saved_load_file_for_load_ref(load_ref, saved_files=None):
    """Find the archived CSV file for a given load reference."""
    if load_ref is None:
        return None

    raw_load_ref = str(load_ref).strip()
    if not raw_load_ref or raw_load_ref.lower() in ["nan", "none"]:
        return None

    lookup_name = clean_filename(raw_load_ref).lower()
    if not lookup_name:
        return None

    file_list = saved_files if saved_files is not None else list_saved_load_files()

    for file_name in file_list:
        lower_name = file_name.lower()
        stem = lower_name[:-4] if lower_name.endswith(".csv") else lower_name

        if stem.startswith(f"{lookup_name}_"):
            return file_name

        if lower_name == f"{lookup_name}.csv":
            return file_name

    return None


def upload_github_file(
    file_path,
    file_content,
    commit_message,
):
    """Create or update a file in GitHub."""

    headers, owner, repo = get_github_connection()

    encoded_path = urllib.parse.quote(
        file_path,
        safe="/",
    )

    url = (
        f"https://api.github.com/repos/"
        f"{owner}/{repo}/contents/{encoded_path}"
    )

    existing_response = requests.get(
        f"{url}?ref={GITHUB_BRANCH}",
        headers=headers,
        timeout=20,
    )

    sha = None

    if existing_response.status_code == 200:

        sha = existing_response.json().get(
            "sha"
        )

    elif existing_response.status_code != 404:

        raise RuntimeError(
            f"GitHub file path check failed "
            f"({existing_response.status_code}): "
            f"{existing_response.text}"
        )

    encoded_content = base64.b64encode(
        file_content.encode("utf-8")
    ).decode("ascii")

    payload = {
        "message": commit_message,
        "content": encoded_content,
        "branch": GITHUB_BRANCH,
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(
        url,
        headers=headers,
        json=payload,
        timeout=30,
    )

    if response.status_code not in (200, 201):

        raise RuntimeError(
            f"GitHub upload failed "
            f"({response.status_code}): "
            f"{response.text}"
        )

    result = response.json()

    return {
        "file_url": result.get(
            "content",
            {},
        ).get("html_url"),

        "download_url": result.get(
            "content",
            {},
        ).get("download_url"),

        "commit_url": result.get(
            "commit",
            {},
        ).get("html_url"),
    }


def upload_to_github(
    csv_text,
    filename,
):
    """Upload processed CSV into saved_loads."""

    file_path = (
        f"{GITHUB_FOLDER}/{filename}"
    )

    return upload_github_file(
        file_path=file_path,
        file_content=csv_text,
        commit_message=(
            f"Archive load CSV: {filename}"
        ),
    )


# ============================================================
# SKU HISTORY
# ============================================================

def update_sku_history(
    load_ref,
    sku_counts,
    submitted_date=None,
):
    """Add current load to SKU history."""

    existing_content, _ = get_github_file(
        SKU_HISTORY_PATH
    )

    if existing_content:

        try:

            history_df = pd.read_csv(
                io.StringIO(existing_content),
                dtype=str,
            )

        except Exception:

            history_df = pd.DataFrame()

    else:

        history_df = pd.DataFrame()

    if history_df.empty:

        history_df = pd.DataFrame(
            columns=[
                "Date Submitted",
                "Load Ref",
            ]
        )

    if "Date Submitted" not in history_df.columns:

        history_df.insert(
            0,
            "Date Submitted",
            "",
        )

    if "Load Ref" not in history_df.columns:

        history_df.insert(
            1,
            "Load Ref",
            "",
        )

    other_columns = [
        c
        for c in history_df.columns
        if c not in [
            "Date Submitted",
            "Load Ref",
        ]
    ]

    history_df = history_df[
        [
            "Date Submitted",
            "Load Ref",
        ]
        + other_columns
    ]

    # Add newly encountered SKUs.
    for sku in sku_counts.keys():

        if sku not in history_df.columns:

            history_df[sku] = 0

    sku_columns = [
        c
        for c in history_df.columns
        if c not in [
            "Date Submitted",
            "Load Ref",
        ]
    ]

    if sku_columns and not history_df.empty:

        history_df[sku_columns] = (
            history_df[sku_columns]
            .fillna(0)
            .apply(
                pd.to_numeric,
                errors="coerce",
            )
            .fillna(0)
            .astype(int)
        )

    london = pytz.timezone(
        "Europe/London"
    )

    if submitted_date:

        date_value = str(
            submitted_date
        ).strip()

    else:

        date_value = datetime.now(
            london
        ).strftime(
            "%d/%m/%Y %H:%M"
        )

    new_row = {
        "Date Submitted": date_value,
        "Load Ref": load_ref,
    }

    for sku in sku_columns:

        new_row[sku] = int(
            sku_counts.get(
                sku,
                0,
            )
        )

    history_df = pd.concat(
        [
            history_df,
            pd.DataFrame([new_row]),
        ],
        ignore_index=True,
    )

    if sku_columns:

        history_df[sku_columns] = (
            history_df[sku_columns]
            .fillna(0)
            .astype(int)
        )

    history_csv = history_df.to_csv(
        index=False,
        encoding="utf-8-sig",
    )

    upload_github_file(
        file_path=SKU_HISTORY_PATH,
        file_content=history_csv,
        commit_message=(
            f"Update SKU history for load "
            f"{load_ref}"
        ),
    )

    return history_df


# ============================================================
# HISTORIC CSV IMPORT
# ============================================================

def extract_historic_csv_data(
    uploaded_file
):
    """
    Read a historic SSCC CSV and extract:
    - Load Ref
    - Date
    - SKU counts
    """

    try:

        file_bytes = uploaded_file.getvalue()

        try:

            df = pd.read_csv(
                io.BytesIO(file_bytes),
                dtype=str,
            )

        except Exception:

            df = pd.read_csv(
                io.BytesIO(file_bytes),
                dtype=str,
                encoding="latin-1",
            )

    except Exception as exc:

        raise ValueError(
            f"Unable to read {uploaded_file.name}: {exc}"
        )

    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    # --------------------------------------------------------
    # Check required fields
    # --------------------------------------------------------

    if "Item Code" not in df.columns:

        raise ValueError(
            f"{uploaded_file.name} does not contain "
            "an 'Item Code' column."
        )

    if "Load Ref" not in df.columns:

        raise ValueError(
            f"{uploaded_file.name} does not contain "
            "a 'Load Ref' column."
        )

    # --------------------------------------------------------
    # Get Load Ref
    # --------------------------------------------------------

    load_refs = (
        df["Load Ref"]
        .dropna()
        .astype(str)
        .str.strip()
    )

    load_refs = [
        value
        for value in load_refs
        if value
        and value.lower()
        not in [
            "nan",
            "none",
        ]
    ]

    if not load_refs:

        raise ValueError(
            f"{uploaded_file.name} does not contain "
            "a valid Load Ref."
        )

    load_ref = load_refs[0]

    # --------------------------------------------------------
    # Get submitted date
    # --------------------------------------------------------

    submitted_date = None

    if "Date" in df.columns:

        date_values = (
            df["Date"]
            .dropna()
            .astype(str)
            .str.strip()
        )

        date_values = [
            value
            for value in date_values
            if value
            and value.lower()
            not in [
                "nan",
                "none",
            ]
        ]

        if date_values:

            submitted_date = date_values[0]

    # If no Date column exists, try Date Submitted.
    if not submitted_date and "Date Submitted" in df.columns:

        date_values = (
            df["Date Submitted"]
            .dropna()
            .astype(str)
            .str.strip()
        )

        date_values = [
            value
            for value in date_values
            if value
            and value.lower()
            not in [
                "nan",
                "none",
            ]
        ]

        if date_values:

            submitted_date = date_values[0]

    if not submitted_date:

        raise ValueError(
            f"{uploaded_file.name} does not contain "
            "a usable Date or Date Submitted column."
        )

    # --------------------------------------------------------
    # Clean rows
    # --------------------------------------------------------

    df = df.dropna(
        how="all"
    )

    if "SSCC Code" in df.columns:

        df = df[
            ~df["SSCC Code"].apply(
                is_summary_row
            )
        ]

    # Remove explicit NA rows.
    na_mask = df.map(
        is_explicit_na
    ).any(axis=1)

    df = df[
        ~na_mask
    ]

    # --------------------------------------------------------
    # Calculate SKU counts
    # --------------------------------------------------------

    item_codes = (
        df["Item Code"]
        .dropna()
        .astype(str)
        .str.strip()
    )

    item_codes = item_codes[
        ~item_codes.str.lower().isin(
            [
                "",
                "nan",
                "none",
            ]
        )
    ]

    if item_codes.empty:

        raise ValueError(
            f"{uploaded_file.name} contains no "
            "usable Item Code values."
        )

    sku_counts = (
        item_codes
        .value_counts()
        .sort_index()
        .to_dict()
    )

    return {
        "filename": uploaded_file.name,
        "load_ref": load_ref,
        "date_submitted": submitted_date,
        "sku_counts": sku_counts,
        "row_count": len(df),
    }


def normalise_history_date(value):
    """
    Convert a history date into a consistent comparison string.
    """

    if pd.isna(value):
        return ""

    text = str(value).strip()

    if not text:
        return ""

    parsed = pd.to_datetime(
        text,
        dayfirst=True,
        errors="coerce",
    )

    if pd.isna(parsed):
        return text

    return parsed.strftime(
        "%d/%m/%Y %H:%M"
    )


def import_historic_csvs(
    imported_records
):
    """
    Merge historic CSV records into the existing
    GitHub SKU history.
    """

    existing_content, _ = get_github_file(
        SKU_HISTORY_PATH
    )

    if existing_content:

        try:

            history_df = pd.read_csv(
                io.StringIO(existing_content),
                dtype=str,
            )

        except Exception:

            history_df = pd.DataFrame()

    else:

        history_df = pd.DataFrame()

    if history_df.empty:

        history_df = pd.DataFrame(
            columns=[
                "Date Submitted",
                "Load Ref",
            ]
        )

    if "Date Submitted" not in history_df.columns:

        history_df.insert(
            0,
            "Date Submitted",
            "",
        )

    if "Load Ref" not in history_df.columns:

        history_df.insert(
            1,
            "Load Ref",
            "",
        )

    # --------------------------------------------------------
    # Ensure all new SKU columns exist
    # --------------------------------------------------------

    for record in imported_records:

        for sku in record["sku_counts"].keys():

            if sku not in history_df.columns:

                history_df[sku] = 0

    sku_columns = [
        column
        for column in history_df.columns
        if column not in [
            "Date Submitted",
            "Load Ref",
        ]
    ]

    # --------------------------------------------------------
    # Normalise existing numeric columns
    # ------------------------------------------