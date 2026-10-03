import base64
import io
import re
import urllib.parse
import uuid
import smtplib

from datetime import datetime, timedelta, date, time

from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart

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

# New planner storage file
PLANNER_PATH = "load_planner.json"

# Default email addresses
EMAIL_TO = "kpsnacks@campeys.co.uk"

LUKE_EMAIL = "luke.oreilly@kpsnacks.com"

GRAYSON_EMAIL = "grayson.swan@kpsnacks.com"

EMAIL_CC = [
    LUKE_EMAIL,
    GRAYSON_EMAIL,
]

# Gmail account used to send the emails
GMAIL_ADDRESS = "kp.ponte.csv@gmail.com"

AUTOSTORE_URL = "https://autostore-live.snacks.local/app"


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

        .st-key-history_back,
        .st-key-import_back,
        .st-key-contacts_back,
        .st-key-sender_back,
        .st-key-planner_back {

            position: fixed !important;
            top: 78px !important;
            left: 18px !important;
            z-index: 999999 !important;

            width: auto !important;

            background: rgba(255, 255, 255, 0.96);
            padding: 5px !important;
            border-radius: 10px;

            box-shadow:
                0 2px 10px rgba(0, 0, 0, 0.18);

            backdrop-filter: blur(5px);
        }

        .st-key-history_back div.stButton > button,
        .st-key-import_back div.stButton > button,
        .st-key-contacts_back div.stButton > button,
        .st-key-sender_back div.stButton > button,
        .st-key-planner_back div.stButton > button {

            width: auto !important;
            min-width: 145px !important;

            min-height: 42px !important;

            padding-left: 14px !important;
            padding-right: 14px !important;

            white-space: nowrap;
        }

        @media (max-width: 768px) {

            .st-key-history_back,
            .st-key-import_back,
            .st-key-contacts_back,
            .st-key-sender_back,
            .st-key-planner_back {

                top: 65px !important;
                left: 10px !important;
            }

            .st-key-history_back div.stButton > button,
            .st-key-import_back div.stButton > button,
            .st-key-contacts_back div.stButton > button,
            .st-key-sender_back div.stButton > button,
            .st-key-planner_back div.stButton > button {

                min-width: 135px !important;
                font-size: 14px !important;
            }
        }

        .block-container {
            padding-top: 2.5rem;
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

if "process_complete" not in st.session_state:
    st.session_state.process_complete = False

if "csv_text" not in st.session_state:
    st.session_state.csv_text = ""

if "filename" not in st.session_state:
    st.session_state.filename = ""

if "sku_counts" not in st.session_state:
    st.session_state.sku_counts = {}

if "load_ref" not in st.session_state:
    st.session_state.load_ref = ""

if "output_df" not in st.session_state:
    st.session_state.output_df = pd.DataFrame()

if "github_result" not in st.session_state:
    st.session_state.github_result = {}

if "history_df" not in st.session_state:
    st.session_state.history_df = pd.DataFrame()

if "planner_week" not in st.session_state:
    today = date.today()
    st.session_state.planner_week = (
        today - timedelta(
            days=today.weekday()
        )
    )


def go_to(page_name):

    st.session_state.page = page_name

    if page_name != "sender":
        st.session_state.process_complete = False
        st.session_state.csv_text = ""
        st.session_state.filename = ""
        st.session_state.sku_counts = {}
        st.session_state.load_ref = ""
        st.session_state.output_df = pd.DataFrame()
        st.session_state.github_result = {}
        st.session_state.history_df = pd.DataFrame()


# ============================================================
# GMAIL SMTP FUNCTIONS
# ============================================================

def send_email_with_smtp(
    to_recipients,
    cc_recipients,
    subject,
    body,
    csv_content,
    csv_filename,
):

    try:

        gmail_password = st.secrets.get(
            "gmail_password"
        )

        if not gmail_password:

            return (
                False,
                "Gmail password/app password is not configured "
                "in Streamlit Secrets.",
            )

        if not to_recipients and not cc_recipients:

            return (
                False,
                "No email recipients were selected.",
            )

        clean_to = []
        clean_cc = []

        for recipient in to_recipients:

            recipient = str(
                recipient
            ).strip()

            if (
                recipient
                and recipient.lower()
                not in [
                    existing.lower()
                    for existing in clean_to
                ]
            ):

                clean_to.append(
                    recipient
                )

        for recipient in cc_recipients:

            recipient = str(
                recipient
            ).strip()

            if not recipient:
                continue

            all_existing = [
                existing.lower()
                for existing in (
                    clean_to + clean_cc
                )
            ]

            if recipient.lower() not in all_existing:

                clean_cc.append(
                    recipient
                )

        all_recipients = (
            clean_to + clean_cc
        )

        if not all_recipients:

            return (
                False,
                "No valid email recipients were selected.",
            )

        msg = MIMEMultipart()

        msg["From"] = GMAIL_ADDRESS

        if clean_to:

            msg["To"] = ", ".join(
                clean_to
            )

        if clean_cc:

            msg["Cc"] = ", ".join(
                clean_cc
            )

        msg["Subject"] = subject

        msg.attach(
            MIMEText(
                body,
                "plain",
                "utf-8",
            )
        )

        csv_bytes = csv_content.encode(
            "utf-8-sig"
        )

        attachment = MIMEApplication(
            csv_bytes,
            _subtype="csv",
        )

        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=csv_filename,
        )

        msg.attach(
            attachment
        )

        with smtplib.SMTP(
            "smtp.gmail.com",
            587,
            timeout=30,
        ) as server:

            server.ehlo()

            server.starttls()

            server.ehlo()

            server.login(
                GMAIL_ADDRESS,
                gmail_password,
            )

            refused = server.sendmail(
                GMAIL_ADDRESS,
                all_recipients,
                msg.as_string(),
            )

        if refused:

            refused_lower = {
                str(recipient).lower()
                for recipient in refused.keys()
            }

            accepted = [
                recipient
                for recipient in all_recipients
                if recipient.lower()
                not in refused_lower
            ]

            refused_details = []

            for recipient, error in refused.items():

                if isinstance(
                    error,
                    bytes,
                ):

                    error = error.decode(
                        "utf-8",
                        errors="replace",
                    )

                refused_details.append(
                    f"{recipient}: {error}"
                )

            result_lines = []

            if accepted:

                result_lines.append(
                    "Gmail accepted the email for: "
                    + ", ".join(accepted)
                )

            if refused_details:

                result_lines.append(
                    "Gmail refused:"
                )

                result_lines.extend(
                    refused_details
                )

            return (
                False,
                "\n".join(
                    result_lines
                ),
            )

        return (
            True,
            (
                "Gmail accepted the email for delivery to: "
                + ", ".join(
                    all_recipients
                )
                + "."
            ),
        )

    except smtplib.SMTPAuthenticationError as exc:

        return (
            False,
            (
                "Gmail authentication failed. "
                "Check that gmail_password in Streamlit "
                "Secrets is a valid Google App Password."
                f"\n\nSMTP error: {exc}"
            ),
        )

    except smtplib.SMTPRecipientsRefused as exc:

        refused_details = []

        for recipient, error in exc.recipients.items():

            if isinstance(
                error,
                bytes,
            ):

                error = error.decode(
                    "utf-8",
                    errors="replace",
                )

            refused_details.append(
                f"{recipient}: {error}"
            )

        return (
            False,
            (
                "Gmail refused the following recipients:\n"
                + "\n".join(
                    refused_details
                )
            ),
        )

    except smtplib.SMTPException as exc:

        return (
            False,
            f"SMTP error while sending email: {exc}",
        )

    except Exception as exc:

        return (
            False,
            (
                "Unexpected email error: "
                f"{type(exc).__name__}: {exc}"
            ),
        )


# ============================================================
# GITHUB FUNCTIONS
# ============================================================

def get_github_settings():

    try:

        token = st.secrets[
            "github_token"
        ]

        username = st.secrets.get(
            "github_username",
            GITHUB_OWNER,
        )

        repo = st.secrets.get(
            "github_repo",
            GITHUB_REPO,
        )

        return (
            token,
            username,
            repo,
        )

    except Exception:

        return (
            None,
            None,
            None,
        )


def get_github_connection():

    token, username, repo = (
        get_github_settings()
    )

    if not token:

        raise RuntimeError(
            "GitHub token is not configured in "
            "Streamlit Secrets."
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
            "GitHub repository check failed "
            f"({response.status_code}): "
            f"{response.text}"
        )

    return (
        headers,
        username,
        repo,
    )


def get_github_file(
    file_path
):

    headers, owner, repo = (
        get_github_connection()
    )

    encoded_path = urllib.parse.quote(
        file_path,
        safe="/",
    )

    url = (
        f"https://api.github.com/repos/"
        f"{owner}/{repo}/contents/"
        f"{encoded_path}"
        f"?ref={GITHUB_BRANCH}"
    )

    response = requests.get(
        url,
        headers=headers,
        timeout=20,
    )

    if response.status_code == 404:

        return (
            None,
            None,
        )

    if response.status_code != 200:

        raise RuntimeError(
            "GitHub file lookup failed "
            f"({response.status_code}): "
            f"{response.text}"
        )

    data = response.json()

    if data.get("encoding") == "base64":

        content = (
            base64.b64decode(
                data["content"].replace(
                    "\n",
                    "",
                )
            )
            .decode(
                "utf-8-sig"
            )
        )

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
                "Unable to download GitHub file "
                f"({file_response.status_code})."
            )

        content = file_response.text

    return (
        content,
        data,
    )


def list_saved_load_files():

    try:

        headers, owner, repo = (
            get_github_connection()
        )

        url = (
            f"https://api.github.com/repos/"
            f"{owner}/{repo}/contents/"
            f"{GITHUB_FOLDER}"
        )

        response = requests.get(
            url,
            headers=headers,
            timeout=20,
        )

        if response.status_code != 200:

            return []

        items = response.json()

        if not isinstance(
            items,
            list,
        ):

            return []

        return [
            item["name"]
            for item in items
            if item.get("type") == "file"
            and str(
                item.get(
                    "name",
                    "",
                )
            ).lower().endswith(
                ".csv"
            )
        ]

    except Exception:

        return []


def upload_github_file(
    file_path,
    file_content,
    commit_message,
):

    headers, owner, repo = (
        get_github_connection()
    )

    encoded_path = urllib.parse.quote(
        file_path,
        safe="/",
    )

    url = (
        f"https://api.github.com/repos/"
        f"{owner}/{repo}/contents/"
        f"{encoded_path}"
    )

    existing_response = requests.get(
        f"{url}?ref={GITHUB_BRANCH}",
        headers=headers,
        timeout=20,
    )

    sha = None

    if existing_response.status_code == 200:

        sha = (
            existing_response
            .json()
            .get("sha")
        )

    elif existing_response.status_code != 404:

        raise RuntimeError(
            "GitHub file path check failed "
            f"({existing_response.status_code}): "
            f"{existing_response.text}"
        )

    encoded_content = (
        base64.b64encode(
            file_content.encode(
                "utf-8"
            )
        )
        .decode(
            "ascii"
        )
    )

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

    if response.status_code not in (
        200,
        201,
    ):

        raise RuntimeError(
            "GitHub upload failed "
            f"({response.status_code}): "
            f"{response.text}"
        )

    result = response.json()

    return {
        "file_url": result.get(
            "content",
            {},
        ).get(
            "html_url"
        ),

        "download_url": result.get(
            "content",
            {},
        ).get(
            "download_url"
        ),

        "commit_url": result.get(
            "commit",
            {},
        ).get(
            "html_url"
        ),
    }


def upload_to_github(
    csv_text,
    filename,
):

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
# DATA CLEANING
# ============================================================

def clean_filename(
    value
):

    value = str(
        value
    ).strip()

    value = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        value,
    )

    return (
        value.strip("_")
        or "load"
    )


def is_summary_row(
    value
):

    if pd.isna(value):

        return False

    text = str(
        value
    ).strip().lower()

    return bool(
        re.search(
            r"\b(total|subtotal|summary)\b",
            text,
        )
    )


def is_blank_or_na(
    value
):

    if pd.isna(value):

        return True

    text = str(
        value
    ).strip().lower()

    return text in [
        "",
        "na",
        "n/a",
        "#n/a",
        "nan",
        "null",
        "none",
    ]


def is_valid_data_value(
    value
):

    return not is_blank_or_na(
        value
    )


def is_valid_wms_load_row(
    row
):

    sscc = row.get(
        "SSCC Code",
        "",
    )

    item_code = row.get(
        "Item Code",
        "",
    )

    if not is_valid_data_value(
        sscc
    ):

        return False

    if not is_valid_data_value(
        item_code
    ):

        return False

    if is_summary_row(
        sscc
    ):

        return False

    if is_summary_row(
        item_code
    ):

        return False

    return True


def read_wms_data(
    raw_text
):

    raw_text = raw_text.strip()

    if not raw_text:

        raise ValueError(
            "No WMS data was entered."
        )

    try:

        df = pd.read_csv(
            io.StringIO(
                raw_text
            ),
            sep="\t",
            dtype=str,
        )

        if len(df.columns) == 1:

            raise ValueError

    except Exception:

        df = pd.read_csv(
            io.StringIO(
                raw_text
            ),
            sep=",",
            dtype=str,
        )

    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    return df


# ============================================================
# SKU HISTORY
# ============================================================

def update_sku_history(
    load_ref,
    sku_counts,
    submitted_date=None,
):

    existing_content, _ = (
        get_github_file(
            SKU_HISTORY_PATH
        )
    )

    if existing_content:

        try:

            history_df = pd.read_csv(
                io.StringIO(
                    existing_content
                ),
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

    if (
        "Date Submitted"
        not in history_df.columns
    ):

        history_df.insert(
            0,
            "Date Submitted",
            "",
        )

    if (
        "Load Ref"
        not in history_df.columns
    ):

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

    if (
        sku_columns
        and not history_df.empty
    ):

        history_df[
            sku_columns
        ] = (
            history_df[
                sku_columns
            ]
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
            pd.DataFrame(
                [new_row]
            ),
        ],
        ignore_index=True,
    )

    if sku_columns:

        history_df[
            sku_columns
        ] = (
            history_df[
                sku_columns
            ]
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
    uploaded_file,
):

    try:

        file_bytes = (
            uploaded_file.getvalue()
        )

        try:

            df = pd.read_csv(
                io.BytesIO(
                    file_bytes
                ),
                dtype=str,
            )

        except Exception:

            df = pd.read_csv(
                io.BytesIO(
                    file_bytes
                ),
                dtype=str,
                encoding="latin-1",
            )

    except Exception as exc:

        raise ValueError(
            f"Unable to read "
            f"{uploaded_file.name}: {exc}"
        )

    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    if "Item Code" not in df.columns:

        raise ValueError(
            f"{uploaded_file.name} does not contain "
            "'Item Code'."
        )

    if "Load Ref" not in df.columns:

        raise ValueError(
            f"{uploaded_file.name} does not contain "
            "'Load Ref'."
        )

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

    submitted_date = None

    for date_column in [
        "Date",
        "Date Submitted",
    ]:

        if date_column not in df.columns:
            continue

        date_values = (
            df[date_column]
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

            submitted_date = (
                date_values[0]
            )

            break

    if not submitted_date:

        raise ValueError(
            f"{uploaded_file.name} does not contain "
            "a usable Date or Date Submitted."
        )

    df = df.dropna(
        how="all"
    ).copy()

    for column in df.columns:

        df[column] = df[column].apply(
            lambda value:
            value.strip()
            if isinstance(
                value,
                str,
            )
            else value
        )

    item_valid_mask = df[
        "Item Code"
    ].apply(
        is_valid_data_value
    )

    df = df.loc[
        item_valid_mask
    ].copy()

    df = df[
        ~df[
            "Item Code"
        ].apply(
            is_summary_row
        )
    ].copy()

    if df.empty:

        raise ValueError(
            f"{uploaded_file.name} contains no usable "
            "Item Code rows after filtering."
        )

    item_codes = (
        df["Item Code"]
        .astype(str)
        .str.strip()
    )

    item_codes = item_codes[
        item_codes != ""
    ]

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


def normalise_history_date(
    value
):

    if pd.isna(value):

        return ""

    text = str(
        value
    ).strip()

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
    imported_records,
):

    existing_content, _ = (
        get_github_file(
            SKU_HISTORY_PATH
        )
    )

    if existing_content:

        try:

            history_df = pd.read_csv(
                io.StringIO(
                    existing_content
                ),
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

    if (
        "Date Submitted"
        not in history_df.columns
    ):

        history_df.insert(
            0,
            "Date Submitted",
            "",
        )

    if (
        "Load Ref"
        not in history_df.columns
    ):

        history_df.insert(
            1,
            "Load Ref",
            "",
        )

    for record in imported_records:

        for sku in record[
            "sku_counts"
        ].keys():

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

    if sku_columns:

        history_df[
            sku_columns
        ] = (
            history_df[
                sku_columns
            ]
            .fillna(0)
            .apply(
                pd.to_numeric,
                errors="coerce",
            )
            .fillna(0)
            .astype(int)
        )

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

        if (
            existing_load
            and existing_date
        ):

            existing_keys.add(
                (
                    existing_load.lower(),
                    existing_date,
                )
            )

    added_records = []
    skipped_records = []

    for record in imported_records:

        load_ref = str(
            record["load_ref"]
        ).strip()

        submitted_date = (
            normalise_history_date(
                record["date_submitted"]
            )
        )

        key = (
            load_ref.lower(),
            submitted_date,
        )

        if key in existing_keys:

            skipped_records.append(
                {
                    "Filename": record[
                        "filename"
                    ],
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
                record[
                    "sku_counts"
                ].get(
                    sku,
                    0,
                )
            )

        history_df = pd.concat(
            [
                history_df,
                pd.DataFrame(
                    [new_row]
                ),
            ],
            ignore_index=True,
        )

        existing_keys.add(
            key
        )

        added_records.append(
            record
        )

    if sku_columns:

        history_df[
            sku_columns
        ] = (
            history_df[
                sku_columns
            ]
            .fillna(0)
            .apply(
                pd.to_numeric,
                errors="coerce",
            )
            .fillna(0)
            .astype(int)
        )

    if added_records:

        history_csv = history_df.to_csv(
            index=False,
            encoding="utf-8-sig",
        )

        upload_github_file(
            file_path=SKU_HISTORY_PATH,
            file_content=history_csv,
            commit_message=(
                "Import historic CSV loads "
                "into SKU history"
            ),
        )

    return (
        history_df,
        added_records,
        skipped_records,
    )


# ============================================================
# PLANNER - BASIC HELPERS
# ============================================================

def planner_week_monday(
    value
):

    if isinstance(
        value,
        datetime,
    ):

        value = value.date()

    if not isinstance(
        value,
        date,
    ):

        value = pd.to_datetime(
            value,
            dayfirst=True,
            errors="coerce",
        )

        if pd.isna(value):

            return date.today() - timedelta(
                days=date.today().weekday()
            )

        value = value.date()

    return (
        value
        - timedelta(
            days=value.weekday()
        )
    )


def planner_date_string(
    value
):

    if isinstance(
        value,
        datetime,
    ):

        value = value.date()

    if isinstance(
        value,
        date,
    ):

        return value.strftime(
            "%Y-%m-%d"
        )

    parsed = pd.to_datetime(
        value,
        dayfirst=True,
        errors="coerce",
    )

    if pd.isna(parsed):

        return ""

    return parsed.strftime(
        "%Y-%m-%d"
    )


def planner_display_date(
    value
):

    parsed = pd.to_datetime(
        value,
        errors="coerce",
    )

    if pd.isna(parsed):

        return str(value)

    return parsed.strftime(
        "%d/%m/%Y"
    )


def parse_planner_time(
    value
):

    if pd.isna(value):

        return None

    if isinstance(
        value,
        time,
    ):

        return value.strftime(
            "%H:%M"
        )

    if isinstance(
        value,
        datetime,
    ):

        return value.strftime(
            "%H:%M"
        )

    if isinstance(
        value,
        pd.Timestamp,
    ):

        return value.strftime(
            "%H:%M"
        )

    # Excel sometimes gives a fractional day.
    if isinstance(
        value,
        (int, float),
    ):

        if 0 <= float(value) < 1:

            total_minutes = round(
                float(value)
                * 24
                * 60
            )

            hours = (
                total_minutes
                // 60
            ) % 24

            minutes = (
                total_minutes
                % 60
            )

            return (
                f"{hours:02d}:"
                f"{minutes:02d}"
            )

    text = str(
        value
    ).strip()

    if not text:

        return None

    match = re.search(
        r"\b(\d{1,2}):(\d{2})\b",
        text,
    )

    if match:

        hour = int(
            match.group(1)
        )

        minute = int(
            match.group(2)
        )

        if (
            0 <= hour <= 23
            and 0 <= minute <= 59
        ):

            return (
                f"{hour:02d}:"
                f"{minute:02d}"
            )

    parsed = pd.to_datetime(
        text,
        errors="coerce",
    )

    if not pd.isna(parsed):

        return parsed.strftime(
            "%H:%M"
        )

    return None


def cell_to_collection_count(
    value
):

    if pd.isna(value):

        return 0

    if isinstance(
        value,
        bool,
    ):

        return 1 if value else 0

    text = str(
        value
    ).strip().lower()

    if text in [
        "",
        "nan",
        "none",
        "-",
    ]:

        return 0

    try:

        numeric = float(
            text
        )

        if numeric > 0:

            return max(
                1,
                int(
                    numeric
                ),
            )

    except Exception:
        pass

    if text in [
        "x",
        "yes",
        "y",
        "true",
        "1",
    ]:

        return 1

    return 0


def find_column(
    columns,
    candidates
):

    normalised = {
        re.sub(
            r"[^a-z0-9]+",
            "",
            str(column).lower(),
        ): column
        for column in columns
    }

    for candidate in candidates:

        key = re.sub(
            r"[^a-z0-9]+",
            "",
            candidate.lower(),
        )

        if key in normalised:

            return normalised[key]

    return None


# ============================================================
# PLANNER - IMPORT COLLECTION REQUEST EXCEL
# ============================================================

def parse_collection_request_workbook(
    uploaded_file
):

    try:

        workbook = pd.ExcelFile(
            uploaded_file
        )

    except Exception as exc:

        raise ValueError(
            f"Unable to open the Excel file: {exc}"
        )

    imported_slots = []

    # --------------------------------------------------------
    # Strategy 1:
    # Look for a normal table with Date + Time columns.
    # --------------------------------------------------------

    for sheet_name in workbook.sheet_names:

        try:

            table_df = pd.read_excel(
                uploaded_file,
                sheet_name=sheet_name,
                dtype=object,
            )

        except Exception:

            continue

        if table_df.empty:

            continue

        table_df.columns = [
            str(column).strip()
            for column in table_df.columns
        ]

        date_column = find_column(
            table_df.columns,
            [
                "Collection Date",
                "Date",
                "Requested Date",
                "Day",
            ],
        )

        time_column = find_column(
            table_df.columns,
            [
                "Collection Time",
                "Time",
                "Requested Time",
                "Planned Time",
            ],
        )

        count_column = find_column(
            table_df.columns,
            [
                "Number of Collections",
                "Collections",
                "Collection Count",
                "Count",
                "Quantity",
                "Requests",
            ],
        )

        if date_column and time_column:

            found_table_rows = False

            for _, row in table_df.iterrows():

                collection_date = (
                    planner_date_string(
                        row.get(
                            date_column
                        )
                    )
                )

                collection_time = (
                    parse_planner_time(
                        row.get(
                            time_column
                        )
                    )
                )

                if (
                    not collection_date
                    or not collection_time
                ):

                    continue

                if count_column:

                    count = cell_to_collection_count(
                        row.get(
                            count_column
                        )
                    )

                else:

                    count = 1

                for _ in range(
                    max(
                        1,
                        count,
                    )
                ):

                    imported_slots.append(
                        {
                            "collection_date":
                                collection_date,

                            "collection_time":
                                collection_time,

                            "notes":
                                "",

                            "source":
                                uploaded_file.name,
                        }
                    )

                    found_table_rows = True

            if found_table_rows:

                continue

    # --------------------------------------------------------
    # Strategy 2:
    # Weekly grid.
    #
    # Typical layout:
    #
    #          Mon 01/09   Tue 02/09   Wed 03/09
    # 08:00        1           1
    # 10:00        1                       1
    #
    # --------------------------------------------------------

    if not imported_slots:

        for sheet_name in workbook.sheet_names:

            try:

                raw_df = pd.read_excel(
                    uploaded_file,
                    sheet_name=sheet_name,
                    header=None,
                    dtype=object,
                )

            except Exception:

                continue

            if raw_df.empty:

                continue

            # Search first 10 rows for date-like headers.
            date_headers = []

            for row_index in range(
                min(
                    10,
                    len(raw_df),
                )
            ):

                for column_index in range(
                    len(raw_df.columns)
                ):

                    value = raw_df.iat[
                        row_index,
                        column_index,
                    ]

                    if pd.isna(value):
                        continue

                    parsed = pd.to_datetime(
                        value,
                        dayfirst=True,
                        errors="coerce",
                    )

                    if (
                        not pd.isna(parsed)
                        and (
                            isinstance(
                                value,
                                (datetime, date, pd.Timestamp)
                            )
                            or re.search(
                                r"\d{1,2}[/\-]\d{1,2}",
                                str(value),
                            )
                        )
                    ):

                        date_headers.append(
                            (
                                row_index,
                                column_index,
                                parsed.date(),
                            )
                        )

            # Remove duplicate columns.
            unique_headers = []

            seen_header_columns = set()

            for (
                header_row,
                column_index,
                header_date,
            ) in date_headers:

                if column_index in seen_header_columns:
                    continue

                seen_header_columns.add(
                    column_index
                )

                unique_headers.append(
                    (
                        header_row,
                        column_index,
                        header_date,
                    )
                )

            if not unique_headers:

                continue

            # Determine the time column.
            time_column_index = 0

            for column_index in range(
                len(raw_df.columns)
            ):

                time_values = 0

                for row_index in range(
                    min(
                        25,
                        len(raw_df),
                    )
                ):

                    if any(
                        header_column == column_index
                        for _, header_column, _
                        in unique_headers
                    ):

                        continue

                    if parse_planner_time(
                        raw_df.iat[
                            row_index,
                            column_index,
                        ]
                    ):

                        time_values += 1

                if time_values >= 1:

                    time_column_index = (
                        column_index
                    )

                    break

            for (
                header_row,
                date_column_index,
                header_date,
            ) in unique_headers:

                for row_index in range(
                    header_row + 1,
                    len(raw_df),
                ):

                    collection_time = (
                        parse_planner_time(
                            raw_df.iat[
                                row_index,
                                time_column_index,
                            ]
                        )
                    )

                    if not collection_time:

                        continue

                    value = raw_df.iat[
                        row_index,
                        date_column_index,
                    ]

                    count = (
                        cell_to_collection_count(
                            value
                        )
                    )

                    for _ in range(
                        count
                    ):

                        imported_slots.append(
                            {
                                "collection_date":
                                    header_date.strftime(
                                        "%Y-%m-%d"
                                    ),

                                "collection_time":
                                    collection_time,

                                "notes":
                                    "",

                                "source":
                                    uploaded_file.name,
                            }
                        )

    if not imported_slots:

        raise ValueError(
            "I could not find any collection dates and "
            "times in the uploaded workbook. "
            "The planner accepts either a normal table "
            "with Date/Time columns or a weekly grid "
            "with dates across the columns and times "
            "down the rows."
        )

    # Remove exact duplicates created by overlapping
    # detection methods.
    unique_slots = []
    seen = set()

    for slot in imported_slots:

        key = (
            slot[
                "collection_date"
            ],
            slot[
                "collection_time"
            ],
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        unique_slots.append(
            slot
        )

    return unique_slots


# ============================================================
# PLANNER - GITHUB STORAGE
# ============================================================

def load_planner_data():

    content, _ = get_github_file(
        PLANNER_PATH
    )

    if not content:

        return {
            "slots": []
        }

    try:

        data = pd.io.json.loads(
            content
        )

    except Exception:

        import json

        try:

            data = json.loads(
                content
            )

        except Exception:

            return {
                "slots": []
            }

    if not isinstance(
        data,
        dict,
    ):

        return {
            "slots": []
        }

    if not isinstance(
        data.get(
            "slots",
            []
        ),
        list,
    ):

        data["slots"] = []

    return data


def save_planner_data(
    data,
    commit_message="Update load planner",
):

    import json

    planner_json = json.dumps(
        data,
        indent=2,
        ensure_ascii=False,
    )

    return upload_github_file(
        file_path=PLANNER_PATH,
        file_content=planner_json,
        commit_message=commit_message,
    )


# ============================================================
# PLANNER - ADD/IMPORT REQUESTS
# ============================================================

def merge_imported_planner_slots(
    existing_data,
    imported_slots,
):

    existing = existing_data.get(
        "slots",
        [],
    )

    # Keep a copy of existing slots.
    new_slots = list(
        existing
    )

    for imported_slot in imported_slots:

        collection_date = (
            imported_slot[
                "collection_date"
            ]
        )

        collection_time = (
            imported_slot[
                "collection_time"
            ]
        )

        matching_slots = [
            slot
            for slot in new_slots
            if slot.get(
                "collection_date"
            ) == collection_date
            and slot.get(
                "collection_time"
            ) == collection_time
        ]

        # Do not duplicate a slot that already exists.
        if matching_slots:

            continue

        new_slots.append(
            {
                "id": uuid.uuid4().hex,

                "collection_date":
                    collection_date,

                "collection_time":
                    collection_time,

                "status":
                    "pending",

                "load_ref":
                    "",

                "notes":
                    imported_slot.get(
                        "notes",
                        "",
                    ),

                "source":
                    imported_slot.get(
                        "source",
                        "",
                    ),
            }
        )

    new_slots.sort(
        key=lambda slot: (
            slot.get(
                "collection_date",
                ""
            ),
            slot.get(
                "collection_time",
                ""
            ),
            slot.get(
                "id",
                ""
            ),
        )
    )

    existing_data["slots"] = (
        new_slots
    )

    return existing_data


# ============================================================
# PLANNER - READ ARCHIVED LOADS
# ============================================================

def get_archived_loads():

    saved_files = (
        list_saved_load_files()
    )

    archived_loads = []

    for file_name in saved_files:

        file_path = (
            f"{GITHUB_FOLDER}/"
            f"{file_name}"
        )

        try:

            content, _ = (
                get_github_file(
                    file_path
                )
            )

            if not content:

                continue

            try:

                df = pd.read_csv(
                    io.StringIO(
                        content
                    ),
                    dtype=str,
                )

            except Exception:

                df = pd.read_csv(
                    io.StringIO(
                        content
                    ),
                    dtype=str,
                    encoding="latin-1",
                )

            if df.empty:

                continue

            df.columns = [
                str(column).strip()
                for column in df.columns
            ]

            load_ref = ""

            if "Load Ref" in df.columns:

                refs = (
                    df["Load Ref"]
                    .dropna()
                    .astype(str)
                    .str.strip()
                )

                refs = [
                    ref
                    for ref in refs
                    if ref
                    and ref.lower()
                    not in [
                        "nan",
                        "none",
                    ]
                ]

                if refs:

                    load_ref = refs[0]

            if not load_ref:

                # Fall back to the filename.
                load_ref = re.sub(
                    r"_\d{8}_\d{6}$",
                    "",
                    file_name.rsplit(
                        ".",
                        1,
                    )[0],
                )

            archived_datetime = None

            if "Date" in df.columns:

                dates = (
                    pd.to_datetime(
                        df["Date"],
                        dayfirst=True,
                        errors="coerce",
                    )
                    .dropna()
                )

                if not dates.empty:

                    archived_datetime = (
                        dates.iloc[0]
                    )

            if archived_datetime is None:

                # Fall back to filename timestamp.
                match = re.search(
                    r"_(\d{8})_(\d{6})\.csv$",
                    file_name,
                    flags=re.IGNORECASE,
                )

                if match:

                    try:

                        archived_datetime = (
                            datetime.strptime(
                                (
                                    match.group(1)
                                    + "_"
                                    + match.group(2)
                                ),
                                "%Y%m%d_%H%M%S",
                            )
                        )

                    except Exception:
                        pass

            if archived_datetime is None:

                continue

            archived_loads.append(
                {
                    "load_ref":
                        load_ref,

                    "date":
                        archived_datetime.strftime(
                            "%Y-%m-%d"
                        ),

                    "datetime":
                        archived_datetime.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),

                    "file":
                        file_name,
                }
            )

        except Exception:

            continue

    archived_loads.sort(
        key=lambda item: (
            item.get(
                "date",
                ""
            ),
            item.get(
                "datetime",
                ""
            ),
            item.get(
                "file",
                ""
            ),
        )
    )

    return archived_loads


# ============================================================
# PLANNER - AUTOMATIC LOAD MATCHING
# ============================================================

def sync_planner_with_archived_loads(
    planner_data,
    archived_loads,
):

    slots = planner_data.get(
        "slots",
        [],
    )

    # Existing assigned load refs.
    already_assigned = set()

    for slot in slots:

        if (
            slot.get(
                "status"
            ) == "assigned"
            and slot.get(
                "load_ref"
            )
        ):

            already_assigned.add(
                str(
                    slot.get(
                        "load_ref"
                    )
                ).strip().lower()
            )

    changed = False

    # --------------------------------------------------------
    # Match loads in archive order.
    #
    # For each day:
    #   first archived load
    #       -> first pending 1
    #   second archived load
    #       -> second pending 1
    #
    # Cancelled slots are skipped.
    # Existing assignments are never changed.
    # --------------------------------------------------------

    for archived_load in archived_loads:

        load_ref = str(
            archived_load.get(
                "load_ref",
                ""
            )
        ).strip()

        if not load_ref:

            continue

        load_key = (
            load_ref.lower()
        )

        if load_key in already_assigned:

            continue

        load_date = (
            archived_load.get(
                "date",
                ""
            )
        )

        if not load_date:

            continue

        matching_slots = [
            slot
            for slot in slots
            if slot.get(
                "collection_date"
            ) == load_date
            and slot.get(
                "status",
                "pending"
            ) == "pending"
            and not slot.get(
                "load_ref"
            )
        ]

        matching_slots.sort(
            key=lambda slot: (
                slot.get(
                    "collection_time",
                    "99:99"
                ),
                slot.get(
                    "id",
                    ""
                ),
            )
        )

        if not matching_slots:

            continue

        selected_slot = (
            matching_slots[0]
        )

        selected_slot[
            "status"
        ] = "assigned"

        selected_slot[
            "load_ref"
        ] = load_ref

        selected_slot[
            "archive_file"
        ] = archived_load.get(
            "file",
            "",
        )

        selected_slot[
            "archived_datetime"
        ] = archived_load.get(
            "datetime",
            "",
        )

        already_assigned.add(
            load_key
        )

        changed = True

    if changed:

        planner_data["slots"] = slots

    return (
        planner_data,
        changed,
    )


# ============================================================
# PLANNER - STATUS HELPERS
# ============================================================

def planner_slot_status_text(
    slot
):

    status = slot.get(
        "status",
        "pending",
    )

    if status == "assigned":

        return str(
            slot.get(
                "load_ref",
                ""
            )
        ).strip() or "1"

    if status == "cancelled":

        return "C"

    return "1"


def planner_slot_style(
    slot
):

    status = slot.get(
        "status",
        "pending",
    )

    if status == "assigned":

        return (
            "background:#d4edda;"
            "border:1px solid #70ad7a;"
            "color:#155724;"
        )

    if status == "cancelled":

        return (
            "background:#f8d7da;"
            "border:1px solid #dc6c6c;"
            "color:#721c24;"
        )

    return (
        "background:#f8f9fa;"
        "border:1px solid #cccccc;"
        "color:#333333;"
    )


# ============================================================
# PLANNER - EXCEL EXPORT
# ============================================================

def create_planner_excel(
    planner_data,
    selected_week,
):

    try:

        from openpyxl import Workbook
        from openpyxl.styles import (
            Font,
            PatternFill,
            Alignment,
            Border,
            Side,
        )

    except ImportError:

        raise RuntimeError(
            "openpyxl is required for the planner "
            "Excel download. Add openpyxl to "
            "requirements.txt."
        )

    slots = [
        slot
        for slot in planner_data.get(
            "slots",
            [],
        )
        if (
            selected_week
            <= datetime.strptime(
                slot.get(
                    "collection_date",
                    "1900-01-01",
                ),
                "%Y-%m-%d",
            ).date()
            < selected_week
            + timedelta(days=7)
        )
    ]

    slots.sort(
        key=lambda slot: (
            slot.get(
                "collection_date",
                ""
            ),
            slot.get(
                "collection_time",
                ""
            ),
        )
    )

    workbook = Workbook()

    tracker = workbook.active
    tracker.title = "Collection Tracker"

    headers = [
        "Collection Date",
        "Day",
        "Collection Time",
        "Status",
        "Load Ref",
        "Notes",
    ]

    tracker.append(
        headers
    )

    header_fill = PatternFill(
        "solid",
        fgColor="D9EAF7",
    )

    green_fill = PatternFill(
        "solid",
        fgColor="C6EFCE",
    )

    red_fill = PatternFill(
        "solid",
        fgColor="FFC7CE",
    )

    pending_fill = PatternFill(
        "solid",
        fgColor="E7E6E6",
    )

    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    for cell in tracker[1]:

        cell.font = Font(
            bold=True
        )

        cell.fill = header_fill

        cell.border = thin_border

        cell.alignment = Alignment(
            horizontal="center"
        )

    for slot in slots:

        parsed_date = datetime.strptime(
            slot[
                "collection_date"
            ],
            "%Y-%m-%d",
        ).date()

        status = slot.get(
            "status",
            "pending",
        )

        if status == "assigned":

            display_status = "Assigned"

        elif status == "cancelled":

            display_status = "Cancelled"

        else:

            display_status = "Pending"

        tracker.append(
            [
                parsed_date.strftime(
                    "%d/%m/%Y"
                ),

                parsed_date.strftime(
                    "%A"
                ),

                slot.get(
                    "collection_time",
                    "",
                ),

                display_status,

                slot.get(
                    "load_ref",
                    "",
                ),

                slot.get(
                    "notes",
                    "",
                ),
            ]
        )

        current_row = (
            tracker.max_row
        )

        if status == "assigned":

            fill = green_fill

        elif status == "cancelled":

            fill = red_fill

        else:

            fill = pending_fill

        for column_index in range(
            1,
            7,
        ):

            cell = tracker.cell(
                current_row,
                column_index,
            )

            cell.fill = fill

            cell.border = thin_border

    for column, width in {
        "A": 18,
        "B": 15,
        "C": 18,
        "D": 15,
        "E": 22,
        "F": 35,
    }.items():

        tracker.column_dimensions[
            column
        ].width = width

    # --------------------------------------------------------
    # Weekly summary
    # --------------------------------------------------------

    summary = workbook.create_sheet(
        "Weekly Summary"
    )

    summary.append(
        [
            "Day",
            "Date",
            "Requested",
            "Assigned",
            "Pending",
            "Cancelled",
        ]
    )

    for column in summary[1]:

        column.font = Font(
            bold=True
        )

        column.fill = header_fill

        column.border = thin_border

    for day_offset in range(7):

        current_date = (
            selected_week
            + timedelta(
                days=day_offset
            )
        )

        day_slots = [
            slot
            for slot in slots
            if slot.get(
                "collection_date"
            ) == current_date.strftime(
                "%Y-%m-%d"
            )
        ]

        requested = len(
            day_slots
        )

        assigned = sum(
            1
            for slot in day_slots
            if slot.get(
                "status"
            ) == "assigned"
        )

        cancelled = sum(
            1
            for slot in day_slots
            if slot.get(
                "status"
            ) == "cancelled"
        )

        pending = sum(
            1
            for slot in day_slots
            if slot.get(
                "status",
                "pending",
            ) == "pending"
        )

        summary.append(
            [
                current_date.strftime(
                    "%A"
                ),

                current_date.strftime(
                    "%d/%m/%Y"
                ),

                requested,

                assigned,

                pending,

                cancelled,
            ]
        )

    for row in summary.iter_rows():

        for cell in row:

            cell.border = thin_border

    for column, width in {
        "A": 18,
        "B": 18,
        "C": 15,
        "D": 15,
        "E": 15,
        "F": 15,
    }.items():

        summary.column_dimensions[
            column
        ].width = width

    # --------------------------------------------------------
    # Daily transport sheets
    # --------------------------------------------------------

    transport_headers = [
        "Planned Time",
        "Load Ref",
        "Pallet Quantity",
        "Bay",
        "Trailer",
        "Seal",
        "Load Number",
        "Collection Time",
        "Trailer Condition",
        "Comments",
    ]

    for day_offset in range(7):

        current_date = (
            selected_week
            + timedelta(
                days=day_offset
            )
        )

        sheet_name = current_date.strftime(
            "%a %d-%m"
        )

        sheet = workbook.create_sheet(
            sheet_name[:31]
        )

        sheet["A1"] = (
            "Campey Transport Requests"
        )

        sheet["A1"].font = Font(
            bold=True,
            size=14,
        )

        sheet["A2"] = (
            current_date.strftime(
                "%A %d/%m/%Y"
            )
        )

        sheet["A2"].font = Font(
            bold=True
        )

        for index, header in enumerate(
            transport_headers,
            start=1,
        ):

            cell = sheet.cell(
                4,
                index,
            )

            cell.value = header

            cell.font = Font(
                bold=True
            )

            cell.fill = header_fill

            cell.border = thin_border

        day_slots = [
            slot
            for slot in slots
            if slot.get(
                "collection_date"
            ) == current_date.strftime(
                "%Y-%m-%d"
            )
        ]

        day_slots.sort(
            key=lambda slot:
            slot.get(
                "collection_time",
                "99:99",
            )
        )

        for row_number, slot in enumerate(
            day_slots,
            start=5,
        ):

            values = [
                slot.get(
                    "collection_time",
                    "",
                ),

                slot.get(
                    "load_ref",
                    "",
                ),

                "",

                "",

                "",

                "",

                "",

                "",

                "",

                (
                    "CANCELLED"
                    if slot.get(
                        "status"
                    ) == "cancelled"
                    else slot.get(
                        "notes",
                        "",
                    )
                ),
            ]

            for column_number, value in enumerate(
                values,
                start=1,
            ):

                cell = sheet.cell(
                    row_number,
                    column_number,
                )

                cell.value = value

                cell.border = thin_border

                status = slot.get(
                    "status",
                    "pending",
                )

                if status == "assigned":

                    cell.fill = green_fill

                elif status == "cancelled":

                    cell.fill = red_fill

                else:

                    cell.fill = pending_fill

        widths = [
            18,
            22,
            18,
            12,
            18,
            15,
            18,
            18,
            22,
            35,
        ]

        for index, width in enumerate(
            widths,
            start=1,
        ):

            sheet.column_dimensions[
                chr(
                    64 + index
                )
            ].width = width

    output = io.BytesIO()

    workbook.save(
        output
    )

    output.seek(0)

    return output.getvalue()


# ============================================================
# LOAD PLANNER SCREEN
# ============================================================

def show_planner():

    st.button(
        "← Back to Home",
        key="planner_back",
        on_click=go_to,
        args=("home",),
    )

    st.title(
        "📋 Campeys Load Planner"
    )

    st.caption(
        "Collection requests are shown as 1 until a "
        "matching archived load is found. Archived loads "
        "turn green and cancelled collections turn red."
    )

    # --------------------------------------------------------
    # Load planner data
    # --------------------------------------------------------

    try:

        planner_data = (
            load_planner_data()
        )

    except Exception as exc:

        st.error(
            f"Unable to load the planner from GitHub: {exc}"
        )

        return

    # --------------------------------------------------------
    # Upload collection request workbook
    # --------------------------------------------------------

    with st.expander(
        "📥 Upload Collection Requests",
        expanded=False,
    ):

        st.write(
            "Upload the collection request Excel file. "
            "The planner accepts either a normal Date/Time "
            "table or the weekly grid format."
        )

        request_file = st.file_uploader(
            "Collection Request Excel File",
            type=[
                "xlsx",
                "xls",
            ],
            key="collection_request_file",
        )

        if request_file:

            try:

                imported_slots = (
                    parse_collection_request_workbook(
                        request_file
                    )
                )

                preview_df = pd.DataFrame(
                    [
                        {
                            "Date":
                                planner_display_date(
                                    slot[
                                        "collection_date"
                                    ]
                                ),

                            "Day":
                                datetime.strptime(
                                    slot[
                                        "collection_date"
                                    ],
                                    "%Y-%m-%d",
                                ).strftime(
                                    "%A"
                                ),

                            "Collection Time":
                                slot[
                                    "collection_time"
                                ],
                        }
                        for slot in imported_slots
                    ]
                )

                st.success(
                    f"Found {len(imported_slots)} "
                    "collection slot(s)."
                )

                st.dataframe(
                    preview_df,
                    use_container_width=True,
                    hide_index=True,
                )

                if st.button(
                    "📥 Add Requests to Planner",
                    type="primary",
                    use_container_width=True,
                    key="import_planner_requests",
                ):

                    planner_data = (
                        merge_imported_planner_slots(
                            planner_data,
                            imported_slots,
                        )
                    )

                    save_planner_data(
                        planner_data,
                        commit_message=(
                            "Import Campeys collection requests "
                            "into load planner"
                        ),
                    )

                    st.success(
                        "Collection requests have been "
                        "added to the planner."
                    )

                    st.rerun()

            except Exception as exc:

                st.error(
                    f"Unable to import the collection "
                    f"request file: {exc}"
                )

    st.divider()

    # --------------------------------------------------------
    # Week navigation
    # --------------------------------------------------------

    current_week = planner_week_monday(
        st.session_state.planner_week
    )

    nav_left, nav_middle, nav_right = st.columns(
        [
            1,
            2,
            1,
        ]
    )

    with nav_left:

        if st.button(
            "⬅ Previous Week",
            use_container_width=True,
            key="planner_previous_week",
        ):

            st.session_state.planner_week = (
                current_week
                - timedelta(
                    days=7
                )
            )

            st.rerun()

    with nav_middle:

        selected_week = st.date_input(
            "Week commencing",
            value=current_week,
            key="planner_week_picker",
        )

        selected_week = planner_week_monday(
            selected_week
        )

        if selected_week != current_week:

            st.session_state.planner_week = (
                selected_week
            )

            st.rerun()

    with nav_right:

        if st.button(
            "Next Week ➡",
            use_container_width=True,
            key="planner_next_week",
        ):

            st.session_state.planner_week = (
                current_week
                + timedelta(
                    days=7
                )
            )

            st.rerun()

    st.markdown(
        f"### Week commencing "
        f"{current_week.strftime('%d/%m/%Y')}"
    )

    # --------------------------------------------------------
    # Find archived CSV loads
    # --------------------------------------------------------

    with st.spinner(
        "Checking archived loads..."
    ):

        archived_loads = (
            get_archived_loads()
        )

    # --------------------------------------------------------
    # Automatically match archived loads
    # --------------------------------------------------------

    try:

        (
            planner_data,
            planner_changed,
        ) = sync_planner_with_archived_loads(
            planner_data,
            archived_loads,
        )

        if planner_changed:

            save_planner_data(
                planner_data,
                commit_message=(
                    "Match archived loads to "
                    "Campeys planner collections"
                ),
            )

    except Exception as exc:

        st.warning(
            f"Planner load matching could not be completed: {exc}"
        )

    # --------------------------------------------------------
    # Get this week's slots
    # --------------------------------------------------------

    week_end = (
        current_week
        + timedelta(
            days=6
        )
    )

    week_slots = []

    for slot in planner_data.get(
        "slots",
        [],
    ):

        try:

            slot_date = datetime.strptime(
                slot.get(
                    "collection_date",
                    "",
                ),
                "%Y-%m-%d",
            ).date()

        except Exception:

            continue

        if (
            current_week
            <= slot_date
            <= week_end
        ):

            week_slots.append(
                slot
            )

    week_slots.sort(
        key=lambda slot: (
            slot.get(
                "collection_date",
                ""
            ),
            slot.get(
                "collection_time",
                ""
            ),
        )
    )

    # --------------------------------------------------------
    # Weekly totals
    # --------------------------------------------------------

    total_slots = len(
        week_slots
    )

    assigned_slots = sum(
        1
        for slot in week_slots
        if slot.get(
            "status"
        ) == "assigned"
    )

    cancelled_slots = sum(
        1
        for slot in week_slots
        if slot.get(
            "status"
        ) == "cancelled"
    )

    pending_slots = sum(
        1
        for slot in week_slots
        if slot.get(
            "status",
            "pending",
        ) == "pending"
    )

    metric1, metric2, metric3, metric4 = st.columns(
        4
    )

    metric1.metric(
        "Collections",
        total_slots,
    )

    metric2.metric(
        "Loads Archived",
        assigned_slots,
    )

    metric3.metric(
        "Waiting",
        pending_slots,
    )

    metric4.metric(
        "Cancelled",
        cancelled_slots,
    )

    st.divider()

    # --------------------------------------------------------
    # Planner display
    # --------------------------------------------------------

    if not week_slots:

        st.info(
            "There are no collection requests in this week. "
            "Upload the collection request workbook above."
        )

    else:

        for day_offset in range(
            7
        ):

            current_date = (
                current_week
                + timedelta(
                    days=day_offset
                )
            )

            date_key = (
                current_date.strftime(
                    "%Y-%m-%d"
                )
            )

            day_slots = [
                slot
                for slot in week_slots
                if slot.get(
                    "collection_date"
                ) == date_key
            ]

            if not day_slots:

                continue

            st.subheader(
                current_date.strftime(
                    "%A %d/%m/%Y"
                )
            )

            day_slots.sort(
                key=lambda slot:
                slot.get(
                    "collection_time",
                    "99:99",
                )
            )

            for slot in day_slots:

                status = slot.get(
                    "status",
                    "pending",
                )

                status_text = (
                    planner_slot_status_text(
                        slot
                    )
                )

                collection_time = slot.get(
                    "collection_time",
                    "",
                )

                if status == "assigned":

                    label = (
                        f"🟩 {collection_time}  "
                        f"—  {status_text}"
                    )

                elif status == "cancelled":

                    label = (
                        f"🟥 {collection_time}  "
                        f"—  C"
                    )

                else:

                    label = (
                        f"⬜ {collection_time}  "
                        f"—  1"
                    )

                with st.expander(
                    label,
                    expanded=False,
                ):

                    status_box = st.empty()

                    status_box.markdown(
                        f"""
                        <div style="
                            {planner_slot_style(slot)}
                            padding:14px;
                            border-radius:8px;
                            text-align:center;
                            font-size:24px;
                            font-weight:700;
                            margin-bottom:12px;
                        ">
                            {status_text}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    if status == "assigned":

                        st.success(
                            f"Archived load: "
                            f"{slot.get('load_ref', '')}"
                        )

                        if slot.get(
                            "archived_datetime"
                        ):

                            st.caption(
                                "Archived: "
                                + str(
                                    slot.get(
                                        "archived_datetime"
                                    )
                                )
                            )

                        if slot.get(
                            "archive_file"
                        ):

                            st.caption(
                                "CSV: "
                                + str(
                                    slot.get(
                                        "archive_file"
                                    )
                                )
                            )

                    elif status == "cancelled":

                        st.error(
                            "This collection has been cancelled."
                        )

                    else:

                        st.info(
                            "Waiting for the Sender tool "
                            "to archive a load for this date."
                        )

                    action_options = [
                        "No change",
                        "Cancel Collection",
                    ]

                    if status == "cancelled":

                        action_options = [
                            "No change",
                            "Re-open Collection",
                        ]

                    selected_action = st.selectbox(
                        "Update collection",
                        options=action_options,
                        key=(
                            "planner_action_"
                            + str(
                                slot.get(
                                    "id"
                                )
                            )
                        ),
                    )

                    if selected_action == (
                        "Cancel Collection"
                    ):

                        if st.button(
                            "Confirm Cancellation",
                            type="primary",
                            key=(
                                "planner_cancel_"
                                + str(
                                    slot.get(
                                        "id"
                                    )
                                )
                            ),
                        ):

                            slot["status"] = (
                                "cancelled"
                            )

                            # Keep the load ref if one was
                            # already assigned. The visible
                            # planner status is still C.
                            save_planner_data(
                                planner_data,
                                commit_message=(
                                    "Cancel collection in "
                                    "Campeys load planner"
                                ),
                            )

                            st.success(
                                "Collection cancelled."
                            )

                            st.rerun()

                    elif selected_action == (
                        "Re-open Collection"
                    ):

                        if st.button(
                            "Re-open Collection",
                            type="primary",
                            key=(
                                "planner_reopen_"
                                + str(
                                    slot.get(
                                        "id"
                                    )
                                )
                            ),
                        ):

                            slot["status"] = (
                                "pending"
                            )

                            slot["load_ref"] = ""

                            slot.pop(
                                "archive_file",
                                None,
                            )

                            slot.pop(
                                "archived_datetime",
                                None,
                            )

                            save_planner_data(
                                planner_data,
                                commit_message=(
                                    "Re-open collection in "
                                    "Campeys load planner"
                                ),
                            )

                            st.success(
                                "Collection re-opened."
                            )

                            st.rerun()

            st.markdown(
                "<br>",
                unsafe_allow_html=True,
            )

    # --------------------------------------------------------
    # Archived loads section
    # --------------------------------------------------------

    st.divider()

    with st.expander(
        "📦 Archived Loads Detected by Sender",
        expanded=False,
    ):

        if not archived_loads:

            st.info(
                "No archived Sender CSVs were found."
            )

        else:

            archived_df = pd.DataFrame(
                archived_loads
            )

            archived_df = archived_df.rename(
                columns={
                    "load_ref": "Load Ref",
                    "date": "Collection Date",
                    "datetime": "Archived",
                    "file": "CSV File",
                }
            )

            st.dataframe(
                archived_df[
                    [
                        "Load Ref",
                        "Collection Date",
                        "Archived",
                        "CSV File",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

    # --------------------------------------------------------
    # Download planner
    # --------------------------------------------------------

    st.divider()

    st.subheader(
        "📊 Download Planner"
    )

    try:

        excel_bytes = (
            create_planner_excel(
                planner_data,
                current_week,
            )
        )

        st.download_button(
            "Download This Week's Planner",
            data=excel_bytes,
            file_name=(
                "Campeys_Planner_"
                f"{current_week.strftime('%Y%m%d')}.xlsx"
            ),
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            use_container_width=True,
        )

    except Exception as exc:

        st.warning(
            f"Planner Excel export unavailable: {exc}"
        )


# ============================================================
# LOAD HISTORY SCREEN
# ============================================================

def find_saved_load_file_for_load_ref(
    load_ref,
    saved_files=None,
):

    if load_ref is None:

        return None

    raw_load_ref = str(
        load_ref
    ).strip()

    if (
        not raw_load_ref
        or raw_load_ref.lower()
        in [
            "nan",
            "none",
        ]
    ):

        return None

    lookup_name = clean_filename(
        raw_load_ref
    ).lower()

    if not lookup_name:

        return None

    file_list = (
        saved_files
        if saved_files is not None
        else list_saved_load_files()
    )

    for file_name in file_list:

        lower_name = (
            file_name.lower()
        )

        stem = (
            lower_name[:-4]
            if lower_name.endswith(
                ".csv"
            )
            else lower_name
        )

        if stem.startswith(
            f"{lookup_name}_"
        ):

            return file_name

        if lower_name == (
            f"{lookup_name}.csv"
        ):

            return file_name

    return None


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

        history_content, _ = (
            get_github_file(
                SKU_HISTORY_PATH
            )
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

            history_df[sku] = pd.to_numeric(
                history_df[sku],
                errors="coerce",
            ).fillna(0)

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

        if chart_view == "Historic Totals":

            historic_totals = (
                history_df[
                    sku_columns
                ]
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

                historic_chart_df = pd.DataFrame(
                    {
                        "SKU": historic_totals.index,
                        "Quantity": historic_totals.values,
                    }
                ).set_index(
                    "SKU"
                )

                st.bar_chart(
                    historic_chart_df,
                    use_container_width=True,
                )

        elif chart_view == "By Load":

            load_options = (
                history_df[
                    "Load Ref"
                ]
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
                    history_df[
                        "Load Ref"
                    ].astype(str)
                    == selected_load
                ]

                selected_totals = (
                    selected_rows[
                        sku_columns
                    ]
                    .sum()
                    .sort_values(
                        ascending=False
                    )
                )

                selected_totals = selected_totals[
                    selected_totals > 0
                ]

                if not selected_totals.empty:

                    selected_chart_df = pd.DataFrame(
                        {
                            "SKU": selected_totals.index,
                            "Quantity": selected_totals.values,
                        }
                    ).set_index(
                        "SKU"
                    )

                    st.bar_chart(
                        selected_chart_df,
                        use_container_width=True,
                    )

        elif chart_view == "By Date Sent":

            history_df[
                "_Submitted Date"
            ] = pd.to_datetime(
                history_df[
                    "Date Submitted"
                ],
                dayfirst=True,
                errors="coerce",
            )

            history_df[
                "_Date Only"
            ] = (
                history_df[
                    "_Submitted Date"
                ]
                .dt.strftime(
                    "%d/%m/%Y"
                )
            )

            date_options = (
                history_df[
                    "_Date Only"
                ]
                .dropna()
                .drop_duplicates()
                .tolist()
            )

            if date_options:

                selected_date = st.selectbox(
                    "Select Date Sent",
                    options=date_options,
                    key="history_date_selector",
                )

                selected_date_rows = (
                    history_df[
                        history_df[
                            "_Date Only"
                        ] == selected_date
                    ]
                )

                date_totals = (
                    selected_date_rows[
                        sku_columns
                    ]
                    .sum()
                    .sort_values(
                        ascending=False
                    )
                )

                date_totals = date_totals[
                    date_totals > 0
                ]

                if not date_totals.empty:

                    date_chart_df = pd.DataFrame(
                        {
                            "SKU": date_totals.index,
                            "Quantity": date_totals.values,
                        }
                    ).set_index(
                        "SKU"
                    )

                    st.bar_chart(
                        date_chart_df,
                        use_container_width=True,
                    )

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

        saved_files = (
            list_saved_load_files()
        )

        header_cols = st.columns(
            [
                1.8,
                2.2,
                4.2,
                1.4,
            ]
        )

        header_cols[0].markdown(
            "**Date Submitted**"
        )

        header_cols[1].markdown(
            "**Load Ref**"
        )

        header_cols[2].markdown(
            "**SKU Summary**"
        )

        header_cols[3].markdown(
            "**CSV**"
        )

        for index, row in (
            display_history_df.iterrows()
        ):

            date_value = str(
                row.get(
                    "Date Submitted",
                    "",
                )
            ).strip()

            load_ref = str(
                row.get(
                    "Load Ref",
                    "",
                )
            ).strip()

            summary_parts = []

            for col in display_history_df.columns:

                if col in [
                    "Date Submitted",
                    "Load Ref",
                ]:

                    continue

                try:

                    qty = int(
                        float(
                            row.get(
                                col,
                                0,
                            )
                        )
                    )

                except Exception:

                    qty = 0

                if qty > 0:

                    summary_parts.append(
                        f"{col}: {qty}"
                    )

            sku_summary = (
                ", ".join(
                    summary_parts
                )
                if summary_parts
                else "No SKU data"
            )

            cols = st.columns(
                [
                    1.8,
                    2.2,
                    4.2,
                    1.4,
                ]
            )

            cols[0].write(
                date_value or "N/A"
            )

            cols[1].write(
                load_ref or "N/A"
            )

            cols[2].write(
                sku_summary
            )

            file_name = (
                find_saved_load_file_for_load_ref(
                    load_ref,
                    saved_files,
                )
            )

            if file_name:

                file_path = (
                    f"{GITHUB_FOLDER}/"
                    f"{file_name}"
                )

                csv_content, _ = (
                    get_github_file(
                        file_path
                    )
                )

                if csv_content:

                    with cols[3]:

                        st.download_button(
                            label="Download CSV",
                            data=csv_content.encode(
                                "utf-8-sig"
                            ),
                            file_name=file_name,
                            mime="text/csv",
                            key=(
                                f"download_row_{index}_"
                                f"{clean_filename(load_ref)}"
                            ),
                            use_container_width=True,
                        )

            else:

                cols[3].caption(
                    "No file"
                )

            st.markdown(
                "<hr style='margin: 0.35rem 0 0.7rem 0;'>",
                unsafe_allow_html=True,
            )

        st.download_button(
            "Download Full Load History CSV",
            data=history_content.encode(
                "utf-8-sig"
            ),
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
        "Import previous SSCC CSV files into "
        "the Campeys SKU load history."
    )

    st.info(
        "Select one or more historic SSCC CSV files. "
        "The importer will read the Load Ref, Date "
        "and Item Code values and add the SKU counts "
        "to the GitHub load history."
    )

    uploaded_files = st.file_uploader(
        "Select Historic CSV Files",
        type=["csv"],
        accept_multiple_files=True,
        key="historic_csv_uploader",
    )

    if not uploaded_files:

        return

    import_records = []
    import_errors = []

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

    if import_errors:

        st.error(
            f"{len(import_errors)} file(s) "
            "could not be read."
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

    preview_rows = []

    for record in import_records:

        preview_rows.append(
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
                "SKU Count": len(
                    record[
                        "sku_counts"
                    ]
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

        st.dataframe(
            pd.DataFrame(
                sku_preview_rows
            ),
            use_container_width=True,
            hide_index=True,
        )

    confirm_import = st.checkbox(
        "I have checked the files above and want "
        "to add them to the load history.",
        key="confirm_historic_import",
    )

    if not confirm_import:

        return

    if st.button(
        "📥 Import Historic Loads",
        type="primary",
        use_container_width=True,
        key="import_historic_button",
    ):

        try:

            (
                history_df,
                added_records,
                skipped_records,
            ) = import_historic_csvs(
                import_records
            )

            st.success(
                f"Successfully imported "
                f"{len(added_records)} historic load(s)."
            )

            if skipped_records:

                st.warning(
                    f"{len(skipped_records)} "
                    "load(s) were already present."
                )

            st.dataframe(
                history_df,
                use_container_width=True,
                hide_index=True,
            )

            updated_history_csv = (
                history_df.to_csv(
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

    try:

        (
            contact_content,
            contact_metadata,
        ) = get_github_file(
            CONTACT_LIST_PATH
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

    if not st.session_state.process_complete:

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
                    "The WMS data is missing "
                    "the following columns:"
                )

                st.write(
                    missing_columns
                )

                return

            df = (
                df.copy()
                .dropna(
                    how="all"
                )
            )

            for column in df.columns:

                df[column] = df[
                    column
                ].apply(
                    lambda value:
                    value.strip()
                    if isinstance(
                        value,
                        str,
                    )
                    else value
                )

            valid_row_mask = df.apply(
                is_valid_wms_load_row,
                axis=1,
            )

            df = df.loc[
                valid_row_mask
            ].copy()

            if df.empty:

                raise ValueError(
                    "No valid WMS load rows were found "
                    "after removing blank, NA and "
                    "summary/total rows."
                )

            london = pytz.timezone(
                "Europe/London"
            )

            current_datetime = (
                datetime.now(
                    london
                ).strftime(
                    "%d/%m/%Y %H:%M"
                )
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

            valid_item_codes = (
                output_df[
                    "Item Code"
                ].apply(
                    lambda value:
                    str(value).strip()
                    if is_valid_data_value(
                        value
                    )
                    else ""
                )
            )

            valid_item_codes = (
                valid_item_codes[
                    valid_item_codes != ""
                ]
            )

            if valid_item_codes.empty:

                raise ValueError(
                    "No valid Item Codes were found "
                    "in the converted load."
                )

            sku_counts = (
                valid_item_codes
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

            timestamp = (
                datetime.now(
                    london
                ).strftime(
                    "%Y%m%d_%H%M%S"
                )
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

            st.session_state.csv_text = (
                csv_text
            )

            st.session_state.filename = (
                filename
            )

            st.session_state.sku_counts = (
                sku_counts
            )

            st.session_state.load_ref = (
                load_ref.strip()
            )

            st.session_state.output_df = (
                output_df.copy()
            )

            st.session_state.process_complete = (
                True
            )

            st.session_state.github_result = (
                github_result
            )

            st.session_state.history_df = (
                history_df
            )

            st.success(
                "CSV archived and SKU history "
                "updated successfully."
            )

            st.rerun()

        except Exception as exc:

            st.error(
                f"Processing failed: {exc}"
            )

            return

    if st.session_state.process_complete:

        sku_counts = (
            st.session_state.get(
                "sku_counts",
                {},
            )
        )

        csv_text = (
            st.session_state.get(
                "csv_text",
                "",
            )
        )

        filename = (
            st.session_state.get(
                "filename",
                "",
            )
        )

        load_ref = (
            st.session_state.get(
                "load_ref",
                "",
            )
        )

        output_df = (
            st.session_state.get(
                "output_df",
                pd.DataFrame(),
            )
        )

        st.subheader(
            "Converted Campeys CSV"
        )

        if not output_df.empty:

            st.caption(
                f"{len(output_df)} valid load row(s) converted."
            )

            st.dataframe(
                output_df,
                use_container_width=True,
                hide_index=True,
            )

        st.subheader(
            "SKU Counts"
        )

        if sku_counts:

            sku_counts_df = pd.DataFrame(
                list(
                    sku_counts.items()
                ),
                columns=[
                    "Item Code",
                    "Count",
                ],
            )

            st.dataframe(
                sku_counts_df,
                use_container_width=True,
                hide_index=True,
            )

        st.subheader(
            "Download"
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

        st.divider()

        st.subheader(
            "📧 Send Email with CSV"
        )

        st.info(
            "The email is sent from "
            f"{GMAIL_ADDRESS}."
        )

        st.write(
            "**Select Recipients:**"
        )

        col_email1, col_email2 = (
            st.columns(2)
        )

        with col_email1:

            send_to_kpsnacks = st.checkbox(
                "KP Snacks / Campeys "
                "(kpsnacks@campeys.co.uk)",
                value=True,
                key="send_to_kpsnacks",
            )

            send_to_luke = st.checkbox(
                "Luke Oreilly "
                "(luke.oreilly@kpsnacks.com)",
                value=True,
                key="send_to_luke",
            )

            send_to_grayson = st.checkbox(
                "Grayson Swan "
                "(grayson.swan@kpsnacks.com)",
                value=True,
                key="send_to_grayson",
            )

        with col_email2:

            send_to_gmail = st.checkbox(
                "My Gmail "
                "(kp.ponte.csv@gmail.com)",
                value=False,
                key="send_to_gmail",
            )

        to_recipients = []
        cc_recipients = []

        if send_to_kpsnacks:

            to_recipients.append(
                EMAIL_TO
            )

        if send_to_luke:

            cc_recipients.append(
                LUKE_EMAIL
            )

        if send_to_grayson:

            cc_recipients.append(
                GRAYSON_EMAIL
            )

        if send_to_gmail:

            cc_recipients.append(
                GMAIL_ADDRESS
            )

        selected_recipients = (
            to_recipients
            + cc_recipients
        )

        if selected_recipients:

            for recipient in (
                selected_recipients
            ):

                st.write(
                    f"• {recipient}"
                )

            if st.button(
                "📧 Send Email with CSV",
                type="primary",
                use_container_width=True,
                key="send_email_button",
            ):

                email_subject = (
                    f"CSV File - Load Ref "
                    f"{load_ref.strip()}"
                )

                email_body = (
                    "Hi,\n\n"
                    f"Please find attached the CSV file "
                    f"for load ref "
                    f"{load_ref.strip()}.\n\n"
                    "SKU Counts:\n\n"
                )

                for sku, count in (
                    sku_counts.items()
                ):

                    email_body += (
                        f"{sku}: {count}\n"
                    )

                email_body += (
                    "\n\nThanks"
                )

                with st.spinner(
                    "Sending email through Gmail..."
                ):

                    success, message = (
                        send_email_with_smtp(
                            to_recipients=to_recipients,
                            cc_recipients=cc_recipients,
                            subject=email_subject,
                            body=email_body,
                            csv_content=csv_text,
                            csv_filename=filename,
                        )
                    )

                if success:

                    st.success(
                        f"✅ {message}"
                    )

                else:

                    st.error(
                        f"❌ {message}"
                    )


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

    col1, col2, col3 = st.columns(3)

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
            'Convert WMS data into the Campeys '
            'SSCC CSV format and archive the load.'
            '</div>',
            unsafe_allow_html=True,
        )

        if st.button(
            "Open SSCC Sender",
            key="open_sender",
            use_container_width=True,
        ):

            go_to(
                "sender"
            )

            st.rerun()

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
            'View historical SKU quantities '
            'submitted for each Campeys load.'
            '</div>',
            unsafe_allow_html=True,
        )

        if st.button(
            "Open Load History",
            key="open_history",
            use_container_width=True,
        ):

            go_to(
                "history"
            )

            st.rerun()

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

    st.markdown(
        "<br>",
        unsafe_allow_html=True,
    )

    col4, col5, col6 = st.columns(3)

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
            'View the Campeys contact list '
            'stored in the GitHub repository.'
            '</div>',
            unsafe_allow_html=True,
        )

        if st.button(
            "Open Contact List",
            key="open_contacts",
            use_container_width=True,
        ):

            go_to(
                "contacts"
            )

            st.rerun()

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
            'Upload collection requests and '
            'track archived loads by collection date.'
            '</div>',
            unsafe_allow_html=True,
        )

        if st.button(
            "Open Load Planner",
            key="open_planner",
            use_container_width=True,
        ):

            go_to(
                "planner"
            )

            st.rerun()

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
            'Import previous SSCC CSVs into '
            'the load history.'
            '</div>',
            unsafe_allow_html=True,
        )

        if st.button(
            "Import Historic CSVs",
            key="open_import",
            use_container_width=True,
        ):

            go_to(
                "import"
            )

            st.rerun()


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

elif st.session_state.page == "planner":

    show_planner()

else:

    st.session_state.page = "home"

    st.rerun()

