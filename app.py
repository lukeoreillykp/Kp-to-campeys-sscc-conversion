import base64
import io
import re
import urllib.parse
from datetime import datetime
import smtplib

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

# Default email addresses
EMAIL_TO = "kpsnacks@campeys.co.uk"

# Lowercase canonical email address
LUKE_EMAIL = "luke.oreilly@kpsnacks.com"

GRAYSON_EMAIL = "grayson.swan@kpsnacks.com"

EMAIL_CC = [
    LUKE_EMAIL,
    GRAYSON_EMAIL,
]

# Gmail account used to send the emails
GMAIL_ADDRESS = "kp.ponte.csv@gmail.com"

AUTOSTORE_URL = "https://autostore-live.snacks.local/app"

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

        /* ==================================================
           GENERAL APP STYLING
           ================================================== */

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


        /* ==================================================
           ALWAYS-VISIBLE BACK BUTTONS
           
           Streamlit gives keyed widgets a class based on
           their key, e.g. st-key-sender_back.
           
           These buttons are positioned fixed so they remain
           visible even when the user scrolls down.
           ================================================== */

        .st-key-history_back,
        .st-key-import_back,
        .st-key-contacts_back,
        .st-key-sender_back {

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


        /* Make the actual button compact rather than full-width */

        .st-key-history_back div.stButton > button,
        .st-key-import_back div.stButton > button,
        .st-key-contacts_back div.stButton > button,
        .st-key-sender_back div.stButton > button {

            width: auto !important;
            min-width: 145px !important;

            min-height: 42px !important;

            padding-left: 14px !important;
            padding-right: 14px !important;

            white-space: nowrap;
        }


        /* Keep the fixed button comfortable on phones */

        @media (max-width: 768px) {

            .st-key-history_back,
            .st-key-import_back,
            .st-key-contacts_back,
            .st-key-sender_back {

                top: 65px !important;
                left: 10px !important;
            }

            .st-key-history_back div.stButton > button,
            .st-key-import_back div.stButton > button,
            .st-key-contacts_back div.stButton > button,
            .st-key-sender_back div.stButton > button {

                min-width: 135px !important;
                font-size: 14px !important;
            }
        }


        /* Add a little top breathing room so the fixed button
           doesn't visually collide with page headings. */

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
    """
    Send an email with CSV attachment using Gmail SMTP.

    The CSV attachment uses MIMEApplication.

    Returns:
        (True, message) on success
        (False, error_message) on failure
    """

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

        # ----------------------------------------------------
        # Clean and de-duplicate recipients
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Create email
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Email body
        # ----------------------------------------------------

        msg.attach(
            MIMEText(
                body,
                "plain",
                "utf-8",
            )
        )

        # ----------------------------------------------------
        # CSV attachment
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Connect to Gmail
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Gmail explicitly refused recipient(s)
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # SMTP accepted all recipients
        # ----------------------------------------------------

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


def get_github_file(file_path):

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

            submitted_date = (
                date_values[0]
            )

    if (
        not submitted_date
        and "Date Submitted"
        in df.columns
    ):

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

            submitted_date = (
                date_values[0]
            )

    if not submitted_date:

        raise ValueError(
            f"{uploaded_file.name} does not contain "
            "a usable Date or Date Submitted."
        )

    # --------------------------------------------------------
    # Clean historic data
    # --------------------------------------------------------

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
            "Item Code rows after filtering blank, "
            "NA and summary/total rows."
        )

    item_codes = (
        df["Item Code"]
        .astype(str)
        .str.strip()
    )

    item_codes = item_codes[
        item_codes != ""
    ]

    if item_codes.empty:

        raise ValueError(
            f"{uploaded_file.name} contains "
            "no usable Item Code values."
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

        history_df.insert