import base64
import io
import json
import re
import smtplib
import urllib.parse
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
import pytz
import requests
import streamlit as st

from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="KP to Campeys SSCC Sender",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# CONSTANTS
# ============================================================

EXPECTED_COLUMNS = [
    "Load Ref",
    "SSCC",
    "Item Code",
    "Item Description",
    "Quantity",
]

FINAL_COLUMNS = [
    "Load Ref",
    "Date",
    "SSCC",
    "Item Code",
    "Item Description",
    "Quantity",
    "Movement/JDE Order Ref",
]

GITHUB_OWNER = "lukeoreillykp"
GITHUB_REPO = "Kp-to-campeys-sscc-conversion"
GITHUB_BRANCH = "main"
GITHUB_FOLDER = "saved_loads"

SKU_HISTORY_PATH = "sku_counts_history.csv"
CONTACT_LIST_PATH = "campeys contact list.txt"
PLANNER_PATH = "load_planner_requests.json"

# New lightweight index of archived loads.
ARCHIVE_INDEX_PATH = "archive_index.json"

EMAIL_TO = "kpsnacks@campeys.co.uk"
LUKE_EMAIL = "luke.oreilly@kpsnacks.com"
GRAYSON_EMAIL = "grayson.swan@kpsnacks.com"

EMAIL_CC = [
    LUKE_EMAIL,
    GRAYSON_EMAIL,
]

GMAIL_ADDRESS = "kp.ponte.csv@gmail.com"

AUTOSTORE_URL = "https://autostore-live.snacks.local/app"

GITHUB_API_URL = "https://api.github.com"

LONDON_TZ = pytz.timezone("Europe/London")

SUMMARY_PATTERN = (
    r"^\s*(total|totals|summary|grand total|sub[- ]?total)\s*$"
)


# ============================================================
# SESSION STATE
# ============================================================

DEFAULT_SESSION_STATE = {
    "page": "home",
    "process_complete": False,
    "csv_text": None,
    "filename": None,
    "sku_counts": None,
    "load_ref": None,
    "output_df": None,
    "github_result": None,
    "history_df": None,
    "planner_week": None,
    "planner_selected_slot_id": None,
}

for key, value in DEFAULT_SESSION_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# CSS
# ============================================================

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }

    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
    }

    .planner-day-header {
        text-align: center;
        font-weight: 700;
        padding: 8px 3px;
        background-color: #eeeeee;
        border-radius: 6px;
        margin-bottom: 8px;
    }

    .planner-empty {
        min-height: 72px;
    }

    [class*="st-key-planner_cell_pending_"] button,
    [class*="st-key-planner_cell_assigned_"] button,
    [class*="st-key-planner_cell_cancelled_"] button {
        min-height: 76px;
        height: 76px;
        width: 100%;
        font-size: 1.25rem;
        font-weight: 800;
        border-radius: 8px;
        margin-bottom: 4px;
    }

    [class*="st-key-planner_cell_pending_"] button {
        background: #f2f2f2;
        color: #222;
        border: 1px solid #cfcfcf;
    }

    [class*="st-key-planner_cell_assigned_"] button {
        background: #d9ead3;
        color: #274e13;
        border: 2px solid #70ad47;
    }

    [class*="st-key-planner_cell_cancelled_"] button {
        background: #f4cccc;
        color: #990000;
        border: 2px solid #cc0000;
    }

    [class*="st-key-planner_cell_pending_"] button:hover,
    [class*="st-key-planner_cell_assigned_"] button:hover,
    [class*="st-key-planner_cell_cancelled_"] button:hover {
        filter: brightness(0.97);
    }

    .planner-selected-title {
        font-size: 1.05rem;
        font-weight: 700;
        margin-bottom: 0.35rem;
    }

    div[data-testid="stExpander"] {
        border-radius: 8px;
    }

    .st-key-history_back button,
    .st-key-import_back button,
    .st-key-contacts_back button,
    .st-key-sender_back button,
    .st-key-planner_back button {
        position: fixed;
        top: 15px;
        left: 15px;
        z-index: 999999;
        width: auto;
        min-width: 120px;
    }

    @media (max-width: 800px) {
        .st-key-history_back button,
        .st-key-import_back button,
        .st-key-contacts_back button,
        .st-key-sender_back button,
        .st-key-planner_back button {
            position: static;
            margin-bottom: 10px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# GENERAL HELPERS
# ============================================================

def london_now():
    return datetime.now(LONDON_TZ)


def london_now_iso():
    return london_now().isoformat()


def go_to(page):
    st.session_state.page = page

    if page != "sender":
        st.session_state.process_complete = False
        st.session_state.csv_text = None
        st.session_state.filename = None
        st.session_state.sku_counts = None
        st.session_state.load_ref = None
        st.session_state.output_df = None
        st.session_state.github_result = None


# ============================================================
# GITHUB CONNECTION
# ============================================================

@st.cache_resource
def get_github_session():
    """
    Reuse one HTTP session for all GitHub requests.
    This avoids repeatedly establishing HTTP connections.
    """
    session = requests.Session()

    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "User-Agent": "KP-Campeys-SSCC-Sender",
        }
    )

    return session


def get_github_settings():
    token = st.secrets.get(
        "github_token",
        "",
    )

    username = st.secrets.get(
        "github_username",
        GITHUB_OWNER,
    )

    repo = st.secrets.get(
        "github_repo",
        GITHUB_REPO,
    )

    return token, username, repo


def get_github_headers():
    token, _, _ = get_github_settings()

    if not token:
        raise RuntimeError(
            "GitHub token is not configured in Streamlit Secrets."
        )

    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


def get_github_url(file_path=""):
    _, username, repo = get_github_settings()

    encoded_path = urllib.parse.quote(
        file_path,
        safe="/",
    )

    return (
        f"{GITHUB_API_URL}/repos/"
        f"{username}/{repo}/contents/"
        f"{encoded_path}"
    )


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def get_github_file(file_path):
    """
    Cached GitHub file download.

    Most GitHub reads are safe to cache because these files are
    only changed by this application.
    """
    session = get_github_session()

    response = session.get(
        get_github_url(file_path),
        headers=get_github_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=30,
    )

    if response.status_code == 404:
        return None

    response.raise_for_status()

    data = response.json()

    if "content" not in data:
        return None

    content = base64.b64decode(
        data["content"]
    ).decode("utf-8-sig")

    return {
        "content": content,
        "sha": data.get("sha"),
        "name": data.get("name"),
        "path": data.get("path"),
    }


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def list_saved_load_files():
    session = get_github_session()

    response = session.get(
        get_github_url(GITHUB_FOLDER),
        headers=get_github_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=30,
    )

    if response.status_code == 404:
        return []

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):
        return []

    return sorted(
        item["name"]
        for item in data
        if (
            item.get("type") == "file"
            and item.get("name", "").lower().endswith(".csv")
        )
    )


def invalidate_github_caches():
    """
    Clear caches after a GitHub write.
    """
    get_github_file.clear()
    list_saved_load_files.clear()
    load_archive_index.clear()
    load_archived_loads.clear()
    load_history.clear()
    load_planner_data.clear()


def upload_github_file(
    file_path,
    file_content,
    commit_message,
):
    """
    Upload or update a GitHub file.
    """
    session = get_github_session()

    existing = get_github_file(file_path)

    payload = {
        "message": commit_message,
        "content": base64.b64encode(
            file_content.encode("utf-8")
        ).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }

    if existing and existing.get("sha"):
        payload["sha"] = existing["sha"]

    response = session.put(
        get_github_url(file_path),
        headers=get_github_headers(),
        json=payload,
        timeout=30,
    )

    if response.status_code not in (200, 201):
        return False, response.text

    invalidate_github_caches()

    return True, response.json()


# ============================================================
# ARCHIVE INDEX
# ============================================================

def empty_archive_index():
    return {
        "version": 1,
        "updated_at": "",
        "loads": [],
    }


@st.cache_data(
    ttl=120,
    show_spinner=False,
)
def load_archive_index():
    """
    Load the lightweight archive index.

    This avoids downloading every archived CSV merely to find
    out which loads exist.
    """
    result = get_github_file(
        ARCHIVE_INDEX_PATH
    )

    if not result:
        return empty_archive_index()

    try:
        data = json.loads(
            result["content"]
        )

        if not isinstance(data, dict):
            return empty_archive_index()

        if "loads" not in data:
            data["loads"] = []

        return data

    except Exception:
        return empty_archive_index()


def save_archive_index(index_data):
    data = dict(index_data)

    data["updated_at"] = london_now_iso()

    content = json.dumps(
        data,
        indent=2,
        ensure_ascii=False,
    )

    return upload_github_file(
        ARCHIVE_INDEX_PATH,
        content,
        "Update archived load index",
    )


def add_archive_to_index(
    filename,
    load_ref,
    archived_date,
):
    """
    Add a newly archived load to the lightweight index.
    """
    index_data = load_archive_index()

    loads = index_data.setdefault(
        "loads",
        [],
    )

    load_ref = str(load_ref).strip()

    # Avoid duplicate index entries.
    existing = next(
        (
            item
            for item in loads
            if (
                str(item.get("load_ref", "")).strip()
                == load_ref
                and item.get("filename") == filename
            )
        ),
        None,
    )

    if existing:
        return True, "Archive index already contains this load."

    loads.append(
        {
            "load_ref": load_ref,
            "date": archived_date,
            "filename": filename,
            "path": f"{GITHUB_FOLDER}/{filename}",
        }
    )

    loads.sort(
        key=lambda item: (
            item.get("date", ""),
            item.get("filename", ""),
        )
    )

    return save_archive_index(index_data)


def rebuild_archive_index():
    """
    Rebuild the archive index from the existing CSV archive.

    This is useful if the index does not exist yet or if historic
    CSVs were added manually.
    """
    files = list_saved_load_files()

    loads = []

    for filename in files:
        result = get_github_file(
            f"{GITHUB_FOLDER}/{filename}"
        )

        if not result:
            continue

        try:
            df = pd.read_csv(
                io.StringIO(result["content"]),
                dtype=str,
                usecols=lambda column: column in {
                    "Load Ref",
                    "Date",
                    "Date Submitted",
                    "date",
                },
            )

            if df.empty:
                continue

            load_ref = ""

            if "Load Ref" in df.columns:
                values = (
                    df["Load Ref"]
                    .dropna()
                    .astype(str)
                    .str.strip()
                )

                if not values.empty:
                    load_ref = values.iloc[0]

            if not load_ref:
                continue

            date_value = None

            for column in (
                "Date",
                "Date Submitted",
                "date",
            ):
                if column not in df.columns:
                    continue

                parsed = pd.to_datetime(
                    df[column],
                    errors="coerce",
                    dayfirst=True,
                )

                valid = parsed.dropna()

                if not valid.empty:
                    date_value = valid.iloc[0]
                    break

            if date_value is None:
                continue

            loads.append(
                {
                    "load_ref": load_ref,
                    "date": date_value.date().isoformat(),
                    "filename": filename,
                    "path": f"{GITHUB_FOLDER}/{filename}",
                }
            )

        except Exception:
            continue

    loads.sort(
        key=lambda item: (
            item["date"],
            item["filename"],
        )
    )

    return save_archive_index(
        {
            "version": 1,
            "updated_at": london_now_iso(),
            "loads": loads,
        }
    )


# ============================================================
# ARCHIVED LOADS
# ============================================================

@st.cache_data(
    ttl=120,
    show_spinner=False,
)
def load_archived_loads():
    """
    Load archived load metadata from archive_index.json.

    IMPORTANT:
    This no longer downloads every archived CSV.

    That is the biggest performance improvement in the planner.
    """
    index_data = load_archive_index()

    archived = []

    for item in index_data.get(
        "loads",
        [],
    ):
        load_ref = str(
            item.get(
                "load_ref",
                "",
            )
        ).strip()

        filename = str(
            item.get(
                "filename",
                "",
            )
        ).strip()

        date_value = str(
            item.get(
                "date",
                "",
            )
        ).strip()

        if not load_ref or not filename:
            continue

        try:
            parsed_date = pd.to_datetime(
                date_value,
                errors="coerce",
            )

            if pd.isna(parsed_date):
                continue

            parsed_datetime = parsed_date.to_pydatetime()

        except Exception:
            continue

        archived.append(
            {
                "load_ref": load_ref,
                "date": parsed_date.date().isoformat(),
                "datetime": parsed_datetime,
                "filename": filename,
                "path": item.get(
                    "path",
                    f"{GITHUB_FOLDER}/{filename}",
                ),
            }
        )

    return sorted(
        archived,
        key=lambda item: (
            item["date"],
            item["datetime"],
            item["filename"],
        ),
    )


def find_saved_load_file_for_load_ref(
    load_ref,
    saved_files=None,
):
    if not load_ref:
        return None

    if saved_files is None:
        saved_files = list_saved_load_files()

    clean_ref = str(
        load_ref
    ).strip().lower()

    for filename in saved_files:
        stem = filename.rsplit(
            ".",
            1,
        )[0].lower()

        if (
            stem == clean_ref
            or stem.startswith(
                clean_ref + "_"
            )
        ):
            return filename

    return None


def upload_to_github(
    csv_text,
    filename,
    load_ref=None,
    archived_date=None,
):
    file_path = (
        f"{GITHUB_FOLDER}/{filename}"
    )

    success, result = upload_github_file(
        file_path,
        csv_text,
        f"Archive sender load {filename}",
    )

    if not success:
        return False, result

    # Update the lightweight archive index.
    if load_ref and archived_date:
        index_ok, index_result = (
            add_archive_to_index(
                filename,
                load_ref,
                archived_date,
            )
        )

        if not index_ok:
            return False, (
                "CSV archived successfully, but the "
                f"archive index could not be updated: "
                f"{index_result}"
            )

    return True, result


# ============================================================
# HISTORY
# ============================================================

@st.cache_data(
    ttl=120,
    show_spinner=False,
)
def load_history():
    result = get_github_file(
        SKU_HISTORY_PATH
    )

    if not result:
        return pd.DataFrame(
            columns=[
                "Date",
                "Load Ref",
                "Item Code",
                "Quantity",
            ]
        )

    try:
        return pd.read_csv(
            io.StringIO(result["content"]),
            dtype=str,
        )

    except Exception:
        return pd.DataFrame(
            columns=[
                "Date",
                "Load Ref",
                "Item Code",
                "Quantity",
            ]
        )


def save_history(history_df):
    csv_text = history_df.to_csv(
        index=False
    )

    return upload_github_file(
        SKU_HISTORY_PATH,
        csv_text,
        "Update SKU counts history",
    )


def update_sku_history(
    load_ref,
    sku_counts,
):
    history = load_history()

    if not sku_counts:
        return True, "No SKU history changes were required."

    timestamp = london_now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    new_rows = pd.DataFrame(
        {
            "Date": timestamp,
            "Load Ref": load_ref,
            "Item Code": list(
                sku_counts.keys()
            ),
            "Quantity": [
                int(value)
                for value in sku_counts.values()
            ],
        }
    )

    history = pd.concat(
        [
            history,
            new_rows,
        ],
        ignore_index=True,
    )

    return save_history(
        history
    )


# ============================================================
# SENDER HELPERS
# ============================================================

def clean_column_names(df):
    df = df.copy()

    df.columns = (
        pd.Index(df.columns)
        .map(str)
        .str.strip()
    )

    return df


def find_column(
    df,
    possible_names,
):
    normalised = {
        re.sub(
            r"\s+",
            " ",
            str(column).strip().lower(),
        ): column
        for column in df.columns
    }

    for name in possible_names:
        key = re.sub(
            r"\s+",
            " ",
            str(name).strip().lower(),
        )

        if key in normalised:
            return normalised[key]

    return None


def read_wms_file(uploaded_file):
    raw = uploaded_file.getvalue()

    try:
        df = pd.read_csv(
            io.BytesIO(raw),
            sep="\t",
            dtype=str,
            encoding="utf-8-sig",
        )

        if len(df.columns) <= 1:
            raise ValueError

    except Exception:
        df = pd.read_csv(
            io.BytesIO(raw),
            dtype=str,
            encoding="utf-8-sig",
        )

    return clean_column_names(df)


def process_wms_dataframe(df):
    df = clean_column_names(df)

    missing = [
        column
        for column in EXPECTED_COLUMNS
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            "Missing required columns: "
            + ", ".join(missing)
        )

    df = df.copy()

    # Vectorised cleaning.
    for column in EXPECTED_COLUMNS:
        df[column] = (
            df[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    for column in (
        "Load Ref",
        "SSCC",
    ):
        df[column] = (
            df[column]
            .str.replace(
                r"\.0$",
                "",
                regex=True,
            )
        )

    # Remove empty rows.
    df = df.loc[
        df["SSCC"].ne("")
        & df["Item Code"].ne("")
    ].copy()

    # Remove summary rows using one combined mask.
    summary_mask = pd.Series(
        False,
        index=df.index,
    )

    for column in (
        "SSCC",
        "Item Code",
        "Item Description",
    ):
        if column in df.columns:
            summary_mask |= df[column].str.contains(
                SUMMARY_PATTERN,
                case=False,
                regex=True,
                na=False,
            )

    df = df.loc[
        ~summary_mask
    ].copy()

    if df.empty:
        raise ValueError(
            "No valid SSCC / Item Code rows were found."
        )

    load_refs = (
        df.loc[
            df["Load Ref"].ne(""),
            "Load Ref",
        ]
       