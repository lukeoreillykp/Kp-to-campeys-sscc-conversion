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

    # Whole-word matching prevents legitimate values
    # containing these words from being incorrectly removed.
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

            st.caption(
                "Total quantity sent for each SKU "
                "across all historical loads."
            )

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

            st.caption(
                "Select a load to see its SKU quantities."
            )

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

                if selected_totals.empty:

                    st.info(
                        "There are no SKU quantities "
                        "available for this load."
                    )

                else:

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

            st.caption(
                "Select a date to see the combined "
                "SKU quantities from all loads "
                "submitted that day."
            )

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

            date_options = sorted(
                date_options,
                key=lambda value:
                datetime.strptime(
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

                if date_totals.empty:

                    st.info(
                        "There are no SKU quantities "
                        "available for this date."
                    )

                else:

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

        if display_history_df.empty:

            st.info(
                "No history rows are available to display."
            )

            return

        st.write(
            "Use the button on the right of each "
            "row to download the matching archived CSV."
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

                val = row.get(
                    col,
                    0,
                )

                try:

                    qty = int(
                        float(val)
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

            with cols[0]:

                st.write(
                    date_value or "N/A"
                )

            with cols[1]:

                st.write(
                    load_ref or "N/A"
                )

            with cols[2]:

                st.write(
                    sku_summary
                )

            with cols[3]:

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

                        key_name = (
                            f"download_row_{index}_"
                            f"{re.sub(
                                r'[^A-Za-z0-9_]+',
                                '_',
                                load_ref,
                            )}"
                        )

                        st.download_button(
                            label="Download CSV",
                            data=csv_content.encode(
                                "utf-8-sig"
                            ),
                            file_name=file_name,
                            mime="text/csv",
                            key=key_name,
                            use_container_width=True,
                        )

                    else:

                        st.caption(
                            "No file"
                        )

                else:

                    st.caption(
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

        st.markdown(
            """
            **Expected CSV format**

            The historic files should contain at least:

            - `Load Ref`
            - `Date`
            - `Item Code`

            The importer will count the Item Code
            entries to create the SKU quantities
            for each load.
            """
        )

        return

    st.subheader(
        "Files Selected"
    )

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

                (
                    history_df_before,
                    _,
                    _,
                ) = import_historic_csvs(
                    []
                )

            existing_keys = set()

            for _, row in (
                history_df_before.iterrows()
            ):

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

            records_to_import = []
            already_exists = []

            for record in import_records:

                record_key = (
                    str(
                        record[
                            "load_ref"
                        ]
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
                    "All selected historic loads "
                    "already exist in the load history. "
                    "Nothing was imported."
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
                    "load(s) were skipped because "
                    "they already exist in the history."
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
        "Contact information retrieved from "
        "the GitHub repository."
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

    # --------------------------------------------------------
    # Initialize process state
    # --------------------------------------------------------

    if "process_complete" not in st.session_state:

        st.session_state.process_complete = False

    # --------------------------------------------------------
    # Input fields
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # PROCESS DATA
    # --------------------------------------------------------

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

            # ------------------------------------------------
            # Clean WMS data
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Only retain rows containing both a valid
            # SSCC Code and Item Code.
            # ------------------------------------------------

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

            # ------------------------------------------------
            # London date/time
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Add required output fields
            # ------------------------------------------------

            df["Load Ref"] = (
                load_ref.strip()
            )

            df["Date"] = (
                current_datetime
            )

            df["Movement"] = (
                jde_order_ref.strip()
            )

            # ------------------------------------------------
            # Build final Campeys dataframe
            # ------------------------------------------------

            output_df = df[
                FINAL_COLUMNS
            ].copy()

            # ------------------------------------------------
            # Final safety check on Item Code
            # ------------------------------------------------

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

            # ------------------------------------------------
            # SKU counts
            # ------------------------------------------------

            sku_counts = (
                valid_item_codes
                .value_counts()
                .sort_index()
                .to_dict()
            )

            # ------------------------------------------------
            # Generate CSV
            # ------------------------------------------------

            csv_buffer = io.StringIO()

            output_df.to_csv(
                csv_buffer,
                index=False,
                encoding="utf-8-sig",
            )

            csv_text = (
                csv_buffer.getvalue()
            )

            # ------------------------------------------------
            # Filename
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Upload CSV to GitHub
            # ------------------------------------------------

            with st.spinner(
                "Uploading CSV to GitHub..."
            ):

                github_result = (
                    upload_to_github(
                        csv_text,
                        filename,
                    )
                )

            # ------------------------------------------------
            # Update SKU history
            # ------------------------------------------------

            with st.spinner(
                "Updating SKU history..."
            ):

                history_df = (
                    update_sku_history(
                        load_ref=load_ref.strip(),
                        sku_counts=sku_counts,
                    )
                )

            # ------------------------------------------------
            # Store process results
            # ------------------------------------------------

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

    # ========================================================
    # DISPLAY PROCESSED RESULTS
    # ========================================================

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

        # ----------------------------------------------------
        # Converted Campeys CSV
        # ----------------------------------------------------

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

        else:

            st.warning(
                "The converted CSV data is not available."
            )

        # ----------------------------------------------------
        # SKU Counts
        # ----------------------------------------------------

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

        else:

            st.info(
                "No SKU counts are available."
            )

        # ----------------------------------------------------
        # Download CSV
        # ----------------------------------------------------

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

        # ====================================================
        # EMAIL
        # ====================================================

        st.divider()

        st.subheader(
            "📧 Send Email with CSV"
        )

        st.markdown(
            "Send the CSV to the selected recipients "
            "via Gmail."
        )

        st.info(
            "The email is sent from "
            f"{GMAIL_ADDRESS}. "
            "A successful message means Gmail accepted "
            "the email for delivery; it does not guarantee "
            "that the recipient's mailbox has received it."
        )

        st.write(
            "**Select Recipients:**"
        )

        # ----------------------------------------------------
        # Recipient checkboxes
        # ----------------------------------------------------

        col_email1, col_email2 = (
            st.columns(2)
        )

        with col_email1:

            send_to_kpsnacks = st.checkbox(
                "KP Snacks / Campeys (kpsnacks@campeys.co.uk)",
                value=True,
                key="send_to_kpsnacks",
            )

            send_to_luke = st.checkbox(
                "Luke Oreilly (luke.oreilly@kpsnacks.com)",
                value=True,
                key="send_to_luke",
            )

            send_to_grayson = st.checkbox(
                "Grayson Swan (grayson.swan@kpsnacks.com)",
                value=True,
                key="send_to_grayson",
            )

        with col_email2:

            send_to_gmail = st.checkbox(
                "My Gmail (kp.ponte.csv@gmail.com)",
                value=False,
                key="send_to_gmail",
            )

        # ----------------------------------------------------
        # Build recipient lists
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Display selected recipients
        # ----------------------------------------------------

        selected_recipients = (
            to_recipients
            + cc_recipients
        )

        if selected_recipients:

            st.write(
                "**Selected recipients:**"
            )

            for recipient in (
                selected_recipients
            ):

                st.write(
                    f"• {recipient}"
                )

        else:

            st.warning(
                "Please select at least one recipient."
            )

        # ----------------------------------------------------
        # Send email
        # ----------------------------------------------------

        if selected_recipients:

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

                    st.caption(
                        "Gmail has accepted the message. "
                        "If a recipient does not receive it, "
                        "check Junk/Spam and their organisation's "
                        "Microsoft 365 quarantine or mail filtering."
                    )

                else:

                    st.error(
                        f"❌ {message}"
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