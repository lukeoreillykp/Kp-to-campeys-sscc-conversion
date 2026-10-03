import base64
import io
import re
import urllib.parse
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders

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

GMAIL_ADDRESS = "kp.ponte.csv@gmail.com"

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
# GMAIL SMTP FUNCTIONS
# ============================================================

def send_email_with_smtp(recipients, subject, body, csv_content, csv_filename):
    """Send email with CSV attachment using Gmail SMTP."""
    
    try:
        gmail_password = st.secrets.get("gmail_password")

        if not gmail_password:
            st.error(
                "❌ Gmail password not configured in Streamlit Secrets. "
                "Add 'gmail_password' to your secrets."
            )
            return False

        # Create email message
        msg = MIMEMultipart()
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject

        # Attach body
        msg.attach(MIMEText(body, "plain"))

        # Attach CSV file
        csv_attachment = MIMEBase("application", "octet-stream")
        csv_attachment.set_payload(csv_content.encode("utf-8-sig"))
        encoders.encode_base64(csv_attachment)
        csv_attachment.add_header(
            "Content-Disposition",
            f"attachment; filename= {csv_filename}",
        )
        msg.attach(csv_attachment)

        # Send email via Gmail SMTP
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_ADDRESS, gmail_password)
        server.send_message(msg)
        server.quit()

        return True

    except Exception as exc:
        st.error(f"Failed to send email: {exc}")
        return False


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
    # --------------------------------------------------------

    if sku_columns:

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

    # --------------------------------------------------------
    # Existing load/date combinations
    # --------------------------------------------------------

    existing_keys = set()

    for _, row in history_df.iterrows():

        existing_load = str(
            row.get(
                "Load Ref",
                "",
            )
        ).strip()

        existing_date = (
            normalise_history_date(
                row.get(
                    "Date Submitted",
                    "",
                )
            )
        )

        if existing_load and existing_date:

            existing_keys.add(
                (
                    existing_load.lower(),
                    existing_date,
                )
            )

    # --------------------------------------------------------
    # Add imported records
    # --------------------------------------------------------

    added_records = []
    skipped_records = []

    for record in imported_records:

        load_ref = str(
            record["load_ref"]
        ).strip()

        submitted_date = normalise_history_date(
            record["date_submitted"]
        )

        key = (
            load_ref.lower(),
            submitted_date,
        )

        if key in existing_keys:

            skipped_records.append(
                {
                    "Filename": record["filename"],
                    "Load Ref": load_ref,
                    "Date Submitted": submitted_date,
                    "Reason": "Already exists",
                }
            )

            continue

        new_row = {
            "Date Submitted": submitted_date,
            "Load Ref": load_ref,
        }

        for sku in sku_columns:

            new_row[sku] = int(
                record["sku_counts"].get(
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

        existing_keys.add(
            key
        )

        added_records.append(
            record
        )

    # --------------------------------------------------------
    # Keep history numeric
    # --------------------------------------------------------

    if sku_columns:

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

    # --------------------------------------------------------
    # Upload updated history
    # --------------------------------------------------------

    if added_records:

        history_csv = history_df.to_csv(
            index=False,
            encoding="utf-8-sig",
        )

        upload_github_file(
            file_path=SKU_HISTORY_PATH,
            file_content=history_csv,
            commit_message=(
                "Import historic CSV loads into "
                "SKU history"
            ),
        )

    return (
        history_df,
        added_records,
        skipped_records,
    )


# ============================================================
# DATA CLEANING
# ============================================================

def clean_filename(value):

    value = str(value).strip()

    value = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        value,
    )

    return (
        value.strip("_")
        or "load"
    )


def is_summary_row(value):

    if pd.isna(value):
        return False

    text = str(value).strip().lower()

    summary_terms = [
        "total",
        "subtotal",
        "summary",
    ]

    return any(
        term in text
        for term in summary_terms
    )


def is_explicit_na(value):

    if pd.isna(value):
        return False

    text = str(value).strip().lower()

    return text in [
        "na",
        "n/a",
        "#n/a",
        "null",
        "none",
    ]


def read_wms_data(raw_text):

    raw_text = raw_text.strip()

    if not raw_text:

        raise ValueError(
            "No WMS data was entered."
        )

    try:

        df = pd.read_csv(
            io.StringIO(raw_text),
            sep="\t",
            dtype=str,
        )

        if len(df.columns) == 1:
            raise ValueError

    except Exception:

        df = pd.read_csv(
            io.StringIO(raw_text),
            sep=",",
            dtype=str,
        )

    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    return df


# ============================================================
# HOME SCREEN
# ============================================================

def show_home():

    st.markdown(
        '<div class="main-title">'
        'KP to Campeys'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="sub-title">'
        'Campeys Operations Tools'
        '</div>',
        unsafe_allow_html=True,
    )

    # ========================================================
    # FIRST ROW
    # ========================================================

    col1, col2, col3 = st.columns(3)

    # --------------------------------------------------------
    # SSCC SENDER
    # --------------------------------------------------------

    with col1:

        st.markdown(
            '<div class="tool-icon">📦</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-title">'
            'KP to Campeys SSCC Sender'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-description">'
            'Convert WMS data into the Campeys SSCC '
            'CSV format and archive the load.'
            '</div>',
            unsafe_allow_html=True,
        )

        if st.button(
            "Open SSCC Sender",
            key="open_sender",
            use_container_width=True,
        ):

            go_to("sender")
            st.rerun()

    # --------------------------------------------------------
    # LOAD HISTORY
    # --------------------------------------------------------

    with col2:

        st.markdown(
            '<div class="tool-icon">📊</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-title">'
            'Load History'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-description">'
            'View historical SKU quantities submitted '
            'for each Campeys load.'
            '</div>',
            unsafe_allow_html=True,
        )

        if st.button(
            "Open Load History",
            key="open_history",
            use_container_width=True,
        ):

            go_to("history")
            st.rerun()

    # --------------------------------------------------------
    # AUTOSTORE
    # --------------------------------------------------------

    with col3:

        st.markdown(
            '<div class="tool-icon">🏭</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-title">'
            'AutoStore'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-description">'
            'Open the live AutoStore application.'
            '</div>',
            unsafe_allow_html=True,
        )

        st.link_button(
            "Open AutoStore",
            AUTOSTORE_URL,
            use_container_width=True,
        )

    # ========================================================
    # SECOND ROW
    # ========================================================

    st.markdown(
        "<br>",
        unsafe_allow_html=True,
    )

    col4, col5, col6 = st.columns(3)

    # --------------------------------------------------------
    # CONTACT LIST
    # --------------------------------------------------------

    with col4:

        st.markdown(
            '<div class="tool-icon">👥</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-title">'
            'Campeys Contact List'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-description">'
            'View the Campeys contact list stored '
            'in the GitHub repository.'
            '</div>',
            unsafe_allow_html=True,
        )

        if st.button(
            "Open Contact List",
            key="open_contacts",
            use_container_width=True,
        ):

            go_to("contacts")
            st.rerun()

    # --------------------------------------------------------
    # LOAD PLANNER
    # --------------------------------------------------------

    with col5:

        st.markdown(
            '<div class="tool-icon">📋</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-title">'
            'Campeys Load Planner'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-description">'
            'Open the Campeys collection request '
            'and load planner workbook.'
            '</div>',
            unsafe_allow_html=True,
        )

        st.link_button(
            "Open Load Planner",
            CAMPEYS_LOAD_PLANNER_URL,
            use_container_width=True,
        )

    # --------------------------------------------------------
    # HISTORIC IMPORT
    # --------------------------------------------------------

    with col6:

        st.markdown(
            '<div class="tool-icon">📥</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-title">'
            'Import Historic CSVs'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-description">'
            'Import previous SSCC CSVs into the '
            'load history.'
            '</div>',
            unsafe_allow_html=True,
        )

        if st.button(
            "Import Historic CSVs",
            key="open_import",
            use_container_width=True,
        ):

            go_to("import")
            st.rerun()


# ============================================================
# LOAD HISTORY SCREEN
# ============================================================

def show_history():

    st.button(
        "← Back to Home",
        key="history_back",
        on_click=go_to,
        args=("home",),
    )

    st.title(
        "📊 Load History"
    )

    st.caption(
        "Explore SKU quantities across all submitted loads."
    )

    try:

        history_content, _ = get_github_file(
            SKU_HISTORY_PATH
        )

        if not history_content:

            st.info(
                "No load history has been created yet."
            )

            return

        history_df = pd.read_csv(
            io.StringIO(
                history_content
            )
        )

        if history_df.empty:

            st.info(
                "No load history has been created yet."
            )

            return

        non_sku_columns = [
            "Date Submitted",
            "Load Ref",
        ]

        sku_columns = [
            column
            for column in history_df.columns
            if column not in non_sku_columns
        ]

        if not sku_columns:

            st.info(
                "No SKU history data is available yet."
            )

            return

        for sku in sku_columns:

            history_df[sku] = (
                pd.to_numeric(
                    history_df[sku],
                    errors="coerce",
                )
                .fillna(0)
            )

        st.subheader(
            "SKU Quantity Chart"
        )

        chart_view = st.radio(
            "View",
            options=[
                "Historic Totals",
                "By Load",
                "By Date Sent",
            ],
            horizontal=True,
            key="history_chart_view",
        )

        # ----------------------------------------------------
        # HISTORIC TOTALS
        # ----------------------------------------------------

        if chart_view == "Historic Totals":

            st.caption(
                "Total quantity sent for each SKU across "
                "all historical loads."
            )

            historic_totals = (
                history_df[sku_columns]
                .sum()
                .sort_values(
                    ascending=False
                )
            )

            historic_totals = historic_totals[
                historic_totals > 0
            ]

            if historic_totals.empty:

                st.info(
                    "There are no SKU quantities "
                    "available to chart."
                )

            else:

                historic_chart_df = (
                    pd.DataFrame(
                        {
                            "SKU": historic_totals.index,
                            "Quantity": historic_totals.values,
                        }
                    )
                    .set_index("SKU")
                )

                st.bar_chart(
                    historic_chart_df,
                    use_container_width=True,
                )

        # ----------------------------------------------------
        # BY LOAD
        # ----------------------------------------------------

        elif chart_view == "By Load":

            st.caption(
                "Select a load to see its SKU quantities."
            )

            load_options = (
                history_df["Load Ref"]
                .dropna()
                .astype(str)
                .drop_duplicates()
                .tolist()
            )

            if not load_options:

                st.info(
                    "No load references are available."
                )

            else:

                selected_load = st.selectbox(
                    "Select Load",
                    options=load_options,
                    key="history_load_selector",
                )

                selected_rows = history_df[
                    history_df["Load Ref"].astype(str)
                    == selected_load
                ]

                selected_totals = (
                    selected_rows[sku_columns]
                    .sum()
                    .sort_values(
                        ascending=False
                    )
                )

                selected_totals = selected_totals[
                    selected_totals > 0
                ]

                if selected_totals.empty:

                    st.info(
                        "There are no SKU quantities "
                        "available for this load."
                    )

                else:

                    selected_chart_df = (
                        pd.DataFrame(
                            {
                                "SKU": selected_totals.index,
                                "Quantity": selected_totals.values,
                            }
                        )
                        .set_index("SKU")
                    )

                    st.bar_chart(
                        selected_chart_df,
                        use_container_width=True,
                    )

        # ----------------------------------------------------
        # BY DATE SENT
        # ----------------------------------------------------

        elif chart_view == "By Date Sent":

            st.caption(
                "Select a date to see the combined SKU "
                "quantities from all loads submitted that day."
            )

            history_df["_Submitted Date"] = (
                pd.to_datetime(
                    history_df["Date Submitted"],
                    dayfirst=True,
                    errors="coerce",
                )
            )

            history_df["_Date Only"] = (
                history_df["_Submitted Date"]
                .dt.strftime("%d/%m/%Y")
            )

            date_options = (
                history_df["_Date Only"]
                .dropna()
                .drop_duplicates()
                .tolist()
            )

            date_options = sorted(
                date_options,
                key=lambda value: datetime.strptime(
                    value,
                    "%d/%m/%Y",
                ),
                reverse=True,
            )

            if not date_options:

                st.info(
                    "No submission dates are available."
                )

            else:

                selected_date = st.selectbox(
                    "Select Date Sent",
                    options=date_options,
                    key="history_date_selector",
                )

                selected_date_rows = history_df[
                    history_df["_Date Only"]
                    == selected_date
                ]

                date_totals = (
                    selected_date_rows[sku_columns]
                    .sum()
                    .sort_values(
                        ascending=False
                    )
                )

                date_totals = date_totals[
                    date_totals > 0
                ]

                if date_totals.empty:

                    st.info(
                        "There are no SKU quantities "
                        "available for this date."
                    )

                else:

                    date_chart_df = (
                        pd.DataFrame(
                            {
                                "SKU": date_totals.index,
                                "Quantity": date_totals.values,
                            }
                        )
                        .set_index("SKU")
                    )

                    st.bar_chart(
                        date_chart_df,
                        use_container_width=True,
                    )

        # ----------------------------------------------------
        # HISTORICAL DATA TABLE WITH ROW DOWNLOAD BUTTONS
        # ----------------------------------------------------

        st.divider()

        st.subheader(
            "Historical Data"
        )

        display_history_df = history_df.drop(
            columns=[
                "_Submitted Date",
                "_Date Only",
            ],
            errors="ignore",
        )

        saved_files = list_saved_load_files()

        if display_history_df.empty:
            st.info("No history rows are available to display.")
            return

        st.write(
            "Use the button on the right of each row to download the matching archived CSV."
        )

        header_cols = st.columns([1.8, 2.2, 4.2, 1.4])
        header_cols[0].markdown("**Date Submitted**")
        header_cols[1].markdown("**Load Ref**")
        header_cols[2].markdown("**SKU Summary**")
        header_cols[3].markdown("**CSV**")

        for index, row in display_history_df.iterrows():

            date_value = str(row.get("Date Submitted", "")).strip()
            load_ref = str(row.get("Load Ref", "")).strip()

            summary_parts = []
            for col in display_history_df.columns:
                if col in ["Date Submitted", "Load Ref"]:
                    continue
                val = row.get(col, 0)
                try:
                    qty = int(float(val))
                except Exception:
                    qty = 0
                if qty > 0:
                    summary_parts.append(f"{col}: {qty}")

            sku_summary = ", ".join(summary_parts) if summary_parts else "No SKU data"

            cols = st.columns([1.8, 2.2, 4.2, 1.4])

            with cols[0]:
                st.write(date_value or "N/A")

            with cols[1]:
                st.write(load_ref or "N/A")

            with cols[2]:
                st.write(sku_summary)

            with cols[3]:
                file_name = find_saved_load_file_for_load_ref(load_ref, saved_files)

                if file_name:
                    file_path = f"{GITHUB_FOLDER}/{file_name}"
                    csv_content, _ = get_github_file(file_path)

                    if csv_content:
                        key_name = (
                            f"download_row_{index}_{re.sub(r'[^A-Za-z0-9_]+', '_', load_ref)}"
                        )
                        st.download_button(
                            label="Download CSV",
                            data=csv_content.encode("utf-8-sig"),
                            file_name=file_name,
                            mime="text/csv",
                            key=key_name,
                            use_container_width=True,
                        )
                    else:
                        st.caption("No file")
                else:
                    st.caption("No file")

            st.markdown(
                "<hr style='margin: 0.35rem 0 0.7rem 0;'>",
                unsafe_allow_html=True,
            )

        st.download_button(
            "Download Full Load History CSV",
            data=history_content.encode("utf-8-sig"),
            file_name=SKU_HISTORY_PATH,
            mime="text/csv",
            use_container_width=True,
        )

    except Exception as exc:

        st.error(
            f"Unable to load the history table: {exc}"
        )


# ============================================================
# HISTORIC CSV IMPORT SCREEN
# ============================================================

def show_import():

    st.button(
        "← Back to Home",
        key="import_back",
        on_click=go_to,
        args=("home",),
    )

    st.title(
        "📥 Import Historic CSVs"
    )

    st.caption(
        "Import previous SSCC CSV files into the "
        "Campeys SKU load history."
    )

    st.info(
        "Select one or more historic SSCC CSV files. "
        "The importer will read the Load Ref, Date and "
        "Item Code values and add the SKU counts to the "
        "GitHub load history."
    )

    uploaded_files = st.file_uploader(
        "Select Historic CSV Files",
        type=["csv"],
        accept_multiple_files=True,
        key="historic_csv_uploader",
    )

    if not uploaded_files:

        st.markdown(
            """
            **Expected CSV format**

            The historic files should contain at least:

            - `Load Ref`
            - `Date`
            - `Item Code`

            The importer will count the Item Code entries
            to create the SKU quantities for each load.
            """
        )

        return

    st.subheader(
        "Files Selected"
    )

    import_records = []
    import_errors = []

    # --------------------------------------------------------
    # Read selected files
    # --------------------------------------------------------

    for uploaded_file in uploaded_files:

        try:

            record = extract_historic_csv_data(
                uploaded_file
            )

            import_records.append(
                record
            )

        except Exception as exc:

            import_errors.append(
                {
                    "Filename": uploaded_file.name,
                    "Error": str(exc),
                }
            )

    # --------------------------------------------------------
    # Show errors
    # --------------------------------------------------------

    if import_errors:

        st.error(
            f"{len(import_errors)} file(s) could not "
            "be read."
        )

        st.dataframe(
            pd.DataFrame(
                import_errors
            ),
            use_container_width=True,
            hide_index=True,
        )

    if not import_records:

        st.warning(
            "There are no valid historic CSVs to import."
        )

        return

    # --------------------------------------------------------
    # Build preview
    # --------------------------------------------------------

    preview_rows = []

    for record in import_records:

        preview_rows.append(
            {
                "Filename": record["filename"],
                "Load Ref": record["load_ref"],
                "Date Submitted": record[
                    "date_submitted"
                ],
                "SKU Count": len(
                    record["sku_counts"]
                ),
                "Rows Processed": record[
                    "row_count"
                ],
            }
        )

    st.dataframe(
        pd.DataFrame(
            preview_rows
        ),
        use_container_width=True,
        hide_index=True,
    )

    # --------------------------------------------------------
    # Show SKU preview
    # --------------------------------------------------------

    st.subheader(
        "SKU Preview"
    )

    sku_preview_rows = []

    for record in import_records:

        for sku, quantity in record[
            "sku_counts"
        ].items():

            sku_preview_rows.append(
                {
                    "Load Ref": record[
                        "load_ref"
                    ],
                    "Date Submitted": record[
                        "date_submitted"
                    ],
                    "SKU": sku,
                    "Quantity": quantity,
                }
            )

    if sku_preview_rows:

        sku_preview_df = pd.DataFrame(
            sku_preview_rows
        )

        st.dataframe(
            sku_preview_df,
            use_container_width=True,
            hide_index=True,
        )

    # --------------------------------------------------------
    # Import button
    # --------------------------------------------------------

    st.divider()

    st.warning(
        "Importing will update the GitHub "
        "sku_counts_history.csv file."
    )

    confirm_import = st.checkbox(
        "I have checked the files above and want "
        "to add them to the load history.",
        key="confirm_historic_import",
    )

    if not confirm_import:

        st.info(
            "Tick the confirmation box to enable "
            "the import."
        )

        return

    if st.button(
        "📥 Import Historic Loads",
        type="primary",
        use_container_width=True,
        key="import_historic_button",
    ):

        try:

            with st.spinner(
                "Checking existing load history..."
            ):

                history_df_before, _, _ = (
                    import_historic_csvs(
                        []
                    )
                )

            existing_keys = set()

            for _, row in history_df_before.iterrows():

                existing_load = str(
                    row.get(
                        "Load Ref",
                        "",
                    )
                ).strip()

                existing_date = (
                    normalise_history_date(
                        row.get(
                            "Date Submitted",
                            "",
                        )
                    )
                )

                if existing_load and existing_date:

                    existing_keys.add(
                        (
                            existing_load.lower(),
                            existing_date,
                        )
                    )

            records_to_import = []
            already_exists = []

            for record in import_records:

                record_key = (
                    str(
                        record["load_ref"]
                    ).strip().lower(),
                    normalise_history_date(
                        record[
                            "date_submitted"
                        ]
                    ),
                )

                if record_key in existing_keys:

                    already_exists.append(
                        record
                    )

                else:

                    records_to_import.append(
                        record
                    )

                    existing_keys.add(
                        record_key
                    )

            if not records_to_import:

                st.info(
                    "All selected historic loads already "
                    "exist in the load history. Nothing "
                    "was imported."
                )

                return

            with st.spinner(
                "Adding historic loads to GitHub..."
            ):

                (
                    updated_history,
                    added_records,
                    skipped_records,
                ) = import_historic_csvs(
                    records_to_import
                )

            st.success(
                f"Successfully imported "
                f"{len(added_records)} historic load(s)."
            )

            if already_exists:

                st.warning(
                    f"{len(already_exists)} selected "
                    "load(s) were skipped because they "
                    "already exist in the history."
                )

                skipped_display = pd.DataFrame(
                    [
                        {
                            "Filename": record[
                                "filename"
                            ],
                            "Load Ref": record[
                                "load_ref"
                            ],
                            "Date Submitted": record[
                                "date_submitted"
                            ],
                            "Reason": "Already exists",
                        }
                        for record in already_exists
                    ]
                )

                st.dataframe(
                    skipped_display,
                    use_container_width=True,
                    hide_index=True,
                )

            st.subheader(
                "Updated Load History"
            )

            st.dataframe(
                updated_history,
                use_container_width=True,
                hide_index=True,
            )

            updated_history_csv = (
                updated_history.to_csv(
                    index=False,
                    encoding="utf-8-sig",
                )
            )

            st.download_button(
                "Download Updated Load History",
                data=updated_history_csv.encode(
                    "utf-8-sig"
                ),
                file_name=SKU_HISTORY_PATH,
                mime="text/csv",
                use_container_width=True,
            )

        except Exception as exc:

            st.error(
                f"Historic import failed: {exc}"
            )


# ============================================================
# CONTACT LIST SCREEN
# ============================================================

def show_contacts():

    st.button(
        "← Back to Home",
        key="contacts_back",
        on_click=go_to,
        args=("home",),
    )

    st.title(
        "👥 Campeys Contact List"
    )

    st.caption(
        "Contact information retrieved from the "
        "GitHub repository."
    )

    try:

        contact_content, contact_metadata = (
            get_github_file(
                CONTACT_LIST_PATH
            )
        )

        if not contact_content:

            st.warning(
                "The Campeys contact list could not "
                "be found in the GitHub repository."
            )

            return

        st.text_area(
            "Contact List",
            value=contact_content,
            height=500,
        )

        st.download_button(
            "Download Contact List",
            data=contact_content.encode(
                "utf-8"
            ),
            file_name=CONTACT_LIST_PATH,
            mime="text/plain",
            use_container_width=True,
        )

        if contact_metadata:

            download_url = (
                contact_metadata.get(
                    "download_url"
                )
            )

            if download_url:

                st.link_button(
                    "Open Contact List from GitHub",
                    download_url,
                    use_container_width=True,
                )

    except Exception as exc:

        st.error(
            f"Unable to load the Campeys contact list: {exc}"
        )


# ============================================================
# SSCC SENDER SCREEN
# ============================================================

def show_sender():

    st.button(
        "← Back to Home",
        key="sender_back",
        on_click=go_to,
        args=("home",),
    )

    st.title(
        "📦 KP to Campeys SSCC Sender"
    )

    st.caption(
        "Convert WMS data, archive the CSV and "
        "maintain the SKU load history."
    )

    load_ref = st.text_input(
        "Load Ref",
        placeholder="Enter load reference",
    )

    jde_order_ref = st.text_input(
        "JDE Order Ref",
        placeholder="Enter JDE order reference",
    )

    wms_data = st.text_area(
        "Paste WMS Data",
        height=350,
        placeholder="Paste the WMS export here...",
    )

    process_button = st.button(
        "Process & Archive",
        type="primary",
        use_container_width=True,
    )

    if not process_button:
        return

    if not load_ref.strip():

        st.error(
            "Please enter a Load Ref."
        )

        return

    if not jde_order_ref.strip():

        st.error(
            "Please enter a JDE Order Ref."
        )

        return

    if not wms_data.strip():

        st.error(
            "Please paste the WMS data."
        )

        return

    try:

        df = read_wms_data(
            wms_data
        )

        missing_columns = [
            column
            for column in EXPECTED_COLUMNS
            if column not in df.columns
        ]

        if missing_columns:

            st.error(
                "The WMS data is missing the "
                "following columns:"
            )

            st.write(
                missing_columns
            )

            return

        df = df.copy()

        df = df.dropna(
            how="all"
        )

        df = df[
            ~df["SSCC Code"].apply(
                is_summary_row
            )
        ]

        # Pandas 2.1+ / 3.x compatibility:
        # DataFrame.applymap() was deprecated and
        # removed in newer pandas versions.
        na_mask = df.map(
            is_explicit_na
        ).any(axis=1)

        df = df[
            ~na_mask
        ]

        london = pytz.timezone(
            "Europe/London"
        )

        current_datetime = datetime.now(
            london
        ).strftime(
            "%d/%m/%Y %H:%M"
        )

        df["Load Ref"] = (
            load_ref.strip()
        )

        df["Date"] = (
            current_datetime
        )

        df["Movement"] = (
            jde_order_ref.strip()
        )

        output_df = df[
            FINAL_COLUMNS
        ].copy()

        sku_counts = (
            output_df["Item Code"]
            .astype(str)
            .str.strip()
            .value_counts()
            .sort_index()
            .to_dict()
        )

        csv_buffer = io.StringIO()

        output_df.to_csv(
            csv_buffer,
            index=False,
            encoding="utf-8-sig",
        )

        csv_text = (
            csv_buffer.getvalue()
        )

        timestamp = datetime.now(
            london
        ).strftime(
            "%Y%m%d_%H%M%S"
        )

        safe_load_ref = clean_filename(
            load_ref
        )

        filename = (
            f"{safe_load_ref}_"
            f"{timestamp}.csv"
        )

        with st.spinner(
            "Uploading CSV to GitHub..."
        ):

            github_result = (
                upload_to_github(
                    csv_text,
                    filename,
                )
            )

        with st.spinner(
            "Updating SKU history..."
        ):

            history_df = (
                update_sku_history(
                    load_ref=load_ref.strip(),
                    sku_counts=sku_counts,
                )
            )

        st.success(
            "CSV archived and SKU history "
            "updated successfully."
        )

        st.subheader(
            "Archived CSV"
        )

        if github_result.get(
            "file_url"
        ):

            st.link_button(
                "Open Archived CSV on GitHub",
                github_result[
                    "file_url"
                ],
                use_container_width=True,
            )

        if github_result.get(
            "download_url"
        ):

            st.link_button(
                "Download Archived CSV",
                github_result[
                    "download_url"
                ],
                use_container_width=True,
            )

        st.subheader(
            "SKU Counts"
        )

        sku_display = pd.DataFrame(
            [sku_counts]
        )

        st.dataframe(
            sku_display,
            use_container_width=True,
            hide_index=True,
        )

        st.subheader(
            "Load History"
        )

        st.dataframe(
            history_df,
            use_container_width=True,
            hide_index=True,
        )

        st.download_button(
            "Download CSV",
            data=csv_text.encode(
                "utf-8-sig"
            ),
            file_name=filename,
            mime="text/csv",
            use_container_width=True,
        )

        # ========================================================
        # EMAIL SECTION WITH RECIPIENT SELECTION
        # ========================================================

        st.divider()

        st.subheader(
            "📧 Send Email with CSV"
        )

        st.markdown(
            "Send the CSV to the Campeys team via Gmail."
        )

        # --------------------------------------------------------
        # EMAIL RECIPIENT SELECTION
        # --------------------------------------------------------

        st.write("**Select Recipients:**")

        col_email1, col_email2, col_email3 = st.columns(3)

        with col_email1:
            send_to_kpsnacks = st.checkbox(
                "KP Snacks (kpsnacks@campeys.co.uk)",
                value=True,
                key="send_to_kpsnacks",
            )

        with col_email2:
            send_to_luke = st.checkbox(
                "Luke Oreilly",
                value=True,
                key="send_to_luke",
            )

        with col_email3:
            send_to_grayson = st.checkbox(
                "Grayson Swan",
                value=True,
                key="send_to_grayson",
            )

        recipients = []

        if send_to_kpsnacks:
            recipients.append(EMAIL_TO)

        if send_to_luke:
            recipients.append(EMAIL_CC[0])

        if send_to_grayson:
            recipients.append(EMAIL_CC[1])

        if not recipients:
            st.warning("Please select at least one recipient.")
        else:
            if st.button(
                "📧 Send Email with CSV",
                type="primary",
                use_container_width=True,
                key="send_email_button",
            ):

                email_subject = (
                    f"CSV File - Load Ref {load_ref.strip()}"
                )

                email_body = (
                    "Hi,\n\n"
                    f"Please find attached the CSV file for load ref {load_ref.strip()}.\n\n"
                    "SKU Counts:\n\n"
                )

                for sku, count in sku_counts.items():
                    email_body += f"{sku}: {count}\n"

                email_body += "\n\nThanks"

                with st.spinner("Sending email..."):
                    success = send_email_with_smtp(
                        recipients,
                        email_subject,
                        email_body,
                        csv_text,
                        filename,
                    )

                if success:
                    st.success(
                        f"✅ Email sent successfully to {len(recipients)} recipient(s)."
                    )
                else:
                    st.error("❌ Failed to send email. Check your secrets configuration.")

    except Exception as exc:

        st.error(
            f"Processing failed: {exc}"
        )


# ============================================================
# MAIN NAVIGATION
# ============================================================

if st.session_state.page == "home":

    show_home()

elif st.session_state.page == "sender":

    show_sender()

elif st.session_state.page == "history":

    show_history()

elif st.session_state.page == "import":

    show_import()

elif st.session_state.page == "contacts":

    show_contacts()

else:

    st.session_state.page = "home"
    st.rerun()