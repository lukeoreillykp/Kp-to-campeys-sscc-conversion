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
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="KP to Campeys SSCC Sender",
    page_icon="📦",
    layout="wide",
)

st.title("📦 KP to Campeys SSCC Sender")


# ============================================================
# CONSTANTS
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


EMAIL_TO = "kpsnacks@campeys.co.uk"
EMAIL_CC = [
    "Luke.oreilly@kpsnacks.com",
    "grayson.swan@kpsnacks.com",
]


# ============================================================
# GITHUB SETTINGS
# ============================================================

def get_github_settings():
    """Read GitHub settings from Streamlit secrets."""

    try:
        token = st.secrets["github_token"]
        username = st.secrets["github_username"]
        repo = st.secrets["github_repo"]
    except Exception as exc:
        raise ValueError(
            "GitHub settings are missing from Streamlit Secrets. "
            "Please add github_token, github_username and github_repo."
        ) from exc

    token = str(token).strip()
    username = str(username).strip()
    repo = str(repo).strip()

    if not token:
        raise ValueError("github_token is empty.")

    if not username:
        raise ValueError("github_username is empty.")

    if not repo:
        raise ValueError("github_repo is empty.")

    return token, username, repo


# ============================================================
# FILENAME CLEANING
# ============================================================

def clean_filename(filename):
    """Make a safe filename for GitHub."""

    filename = str(filename).strip()

    filename = re.sub(
        r'[<>:"/\\|?*]',
        "_",
        filename,
    )

    filename = re.sub(
        r"\s+",
        " ",
        filename,
    ).strip()

    if not filename:
        filename = "wms_output"

    if not filename.lower().endswith(".csv"):
        filename += ".csv"

    return filename


# ============================================================
# ROW FILTERING HELPERS
# ============================================================

def is_summary_row(value):
    """Return True for blank/summary rows."""

    if value is None:
        return True

    value = str(value).strip().lower()

    if not value:
        return True

    summary_values = {
        "total",
        "totals",
        "grand total",
        "grand totals",
        "summary",
        "na",
        "n/a",
    }

    if value in summary_values:
        return True

    if value.startswith("total"):
        return True

    return False


def is_explicit_na(value):
    """Return True when a cell contains an explicit NA value."""

    if value is None:
        return True

    cleaned = str(value).strip().lower()

    cleaned = re.sub(
        r"[\s\-_./]+",
        "",
        cleaned,
    )

    return cleaned == "na"


# ============================================================
# READ WMS DATA
# ============================================================

def read_wms_data(text):
    """Read pasted WMS data and detect tab/comma delimiter."""

    text = text.strip()

    if not text:
        raise ValueError("No WMS data was supplied.")

    first_line = next(
        (
            line
            for line in text.splitlines()
            if line.strip()
        ),
        "",
    )

    if "\t" in first_line:
        delimiter = "\t"
    else:
        delimiter = ","

    df = pd.read_csv(
        io.StringIO(text),
        sep=delimiter,
        dtype=str,
        keep_default_na=False,
    )

    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    return df


# ============================================================
# GITHUB UPLOAD
# ============================================================

def upload_to_github(csv_bytes, filename):
    """
    Upload CSV to GitHub using the Contents API.

    Provides detailed diagnostics for:
    - token authentication
    - repository access
    - existing file detection
    - upload/write failures
    """

    token, username, repo = get_github_settings()

    filename = clean_filename(filename)

    repo_url = (
        f"https://api.github.com/repos/"
        f"{urllib.parse.quote(username, safe='')}/"
        f"{urllib.parse.quote(repo, safe='')}"
    )

    file_path = f"{GITHUB_FOLDER}/{filename}"

    encoded_path = "/".join(
        urllib.parse.quote(
            part,
            safe="",
        )
        for part in file_path.split("/")
    )

    file_url = (
        f"{repo_url}/contents/{encoded_path}"
    )

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "KP-to-Campeys-SSCC-Sender",
    }

    # --------------------------------------------------------
    # STEP 1 - Check authentication
    # --------------------------------------------------------

    try:
        user_response = requests.get(
            "https://api.github.com/user",
            headers=headers,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "Could not connect to GitHub while checking "
            f"authentication: {exc}"
        ) from exc

    if user_response.status_code != 200:

        try:
            response_json = user_response.json()

            github_message = response_json.get(
                "message",
                user_response.text,
            )

        except Exception:
            github_message = user_response.text

        raise RuntimeError(
            "GitHub authentication failed.\n\n"
            f"HTTP status: {user_response.status_code}\n"
            f"GitHub message: {github_message}\n\n"
            "Check that github_token in Streamlit Secrets "
            "is valid and has not expired or been revoked."
        )

    authenticated_user = user_response.json().get(
        "login",
        "unknown",
    )

    # --------------------------------------------------------
    # STEP 2 - Check repository access
    # --------------------------------------------------------

    try:
        repo_response = requests.get(
            repo_url,
            headers=headers,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "Could not connect to GitHub while checking "
            f"the repository: {exc}"
        ) from exc

    if repo_response.status_code != 200:

        try:
            response_json = repo_response.json()

            github_message = response_json.get(
                "message",
                repo_response.text,
            )

        except Exception:
            github_message = repo_response.text

        raise RuntimeError(
            "GitHub repository check failed.\n\n"
            f"Repository: {username}/{repo}\n"
            f"HTTP status: {repo_response.status_code}\n"
            f"GitHub message: {github_message}\n\n"
            "Check github_username and github_repo in "
            "Streamlit Secrets. Also make sure the GitHub "
            "account represented by the token has permission "
            "to write to this repository."
        )

    repo_info = repo_response.json()

    default_branch = repo_info.get(
        "default_branch",
        GITHUB_BRANCH,
    )

    # --------------------------------------------------------
    # STEP 3 - Check whether file already exists
    # --------------------------------------------------------

    params = {
        "ref": default_branch,
    }

    try:
        file_response = requests.get(
            file_url,
            headers=headers,
            params=params,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "Could not check the GitHub file path: "
            f"{exc}"
        ) from exc

    sha = None

    if file_response.status_code == 200:

        try:
            existing_file = file_response.json()

            sha = existing_file.get(
                "sha"
            )

        except Exception:
            sha = None

    elif file_response.status_code == 404:
        # Normal if the file does not exist yet.
        pass

    else:

        try:
            response_json = file_response.json()

            github_message = response_json.get(
                "message",
                file_response.text,
            )

        except Exception:
            github_message = file_response.text

        raise RuntimeError(
            "GitHub file/path check failed.\n\n"
            f"Path: {file_path}\n"
            f"HTTP status: {file_response.status_code}\n"
            f"GitHub message: {github_message}"
        )

    # --------------------------------------------------------
    # STEP 4 - Encode CSV
    # --------------------------------------------------------

    encoded_content = base64.b64encode(
        csv_bytes
    ).decode("utf-8")

    upload_payload = {
        "message": (
            f"Archive WMS load CSV: {filename}"
        ),
        "content": encoded_content,
        "branch": default_branch,
    }

    if sha:
        upload_payload["sha"] = sha

    # --------------------------------------------------------
    # STEP 5 - Upload
    # --------------------------------------------------------

    try:
        upload_response = requests.put(
            file_url,
            headers=headers,
            json=upload_payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "Could not connect to GitHub during upload: "
            f"{exc}"
        ) from exc

    if upload_response.status_code not in (
        200,
        201,
    ):

        try:
            response_json = upload_response.json()

            github_message = response_json.get(
                "message",
                upload_response.text,
            )

            github_errors = response_json.get(
                "errors",
                "",
            )

        except Exception:
            github_message = upload_response.text
            github_errors = ""

        error_text = (
            "GitHub upload failed.\n\n"
            f"Authenticated GitHub user: "
            f"{authenticated_user}\n"
            f"Repository: {username}/{repo}\n"
            f"Branch: {default_branch}\n"
            f"Path: {file_path}\n"
            f"HTTP status: "
            f"{upload_response.status_code}\n"
            f"GitHub message: {github_message}"
        )

        if github_errors:
            error_text += (
                f"\nGitHub errors: {github_errors}"
            )

        error_text += (
            "\n\nFor a classic GitHub Personal Access Token, "
            "make sure the token has the `repo` scope and "
            "that the authenticated account has write access "
            "to this repository."
        )

        raise RuntimeError(error_text)

    try:
        upload_result = upload_response.json()
    except Exception:
        upload_result = {}

    commit_url = (
        upload_result
        .get("commit", {})
        .get("html_url")
    )

    html_url = (
        upload_result
        .get("content", {})
        .get("html_url")
    )

    return {
        "filename": filename,
        "path": file_path,
        "authenticated_user": authenticated_user,
        "repository": f"{username}/{repo}",
        "branch": default_branch,
        "commit_url": commit_url,
        "file_url": html_url,
    }


# ============================================================
# USER INPUTS
# ============================================================

st.subheader("Load Information")

load_ref = st.text_input(
    "Load Ref",
    placeholder="Enter Load Ref",
)

jde_order_ref = st.text_input(
    "JDE Order Ref",
    placeholder="Enter JDE Order Ref",
)

st.subheader("Paste WMS Data")

wms_data = st.text_area(
    "WMS Data",
    height=350,
    placeholder="Paste the WMS data here...",
)

process_button = st.button(
    "🚀 Process & Archive",
    type="primary",
)


# ============================================================
# PROCESS
# ============================================================

if process_button:

    # --------------------------------------------------------
    # Validate user inputs
    # --------------------------------------------------------

    if not load_ref.strip():
        st.error("Please enter a Load Ref.")
        st.stop()

    if not jde_order_ref.strip():
        st.error("Please enter a JDE Order Ref.")
        st.stop()

    if not wms_data.strip():
        st.error("Please paste the WMS data.")
        st.stop()

    # --------------------------------------------------------
    # Read WMS data
    # --------------------------------------------------------

    try:
        df = read_wms_data(wms_data)

    except Exception as exc:
        st.error(
            f"Could not read the WMS data: {exc}"
        )
        st.stop()

    # --------------------------------------------------------
    # Validate columns
    # --------------------------------------------------------

    missing_columns = [
        column
        for column in EXPECTED_COLUMNS
        if column not in df.columns
    ]

    if missing_columns:

        st.error(
            "The following required columns are missing:\n\n"
            + "\n".join(
                f"- {column}"
                for column in missing_columns
            )
        )

        st.write(
            "Columns detected in the pasted data:"
        )

        st.write(
            list(df.columns)
        )

        st.stop()

    # --------------------------------------------------------
    # Keep only expected columns
    # --------------------------------------------------------

    df = df[
        EXPECTED_COLUMNS
    ].copy()

    # --------------------------------------------------------
    # Remove completely blank rows
    # --------------------------------------------------------

    df = df[
        df.apply(
            lambda row: any(
                str(value).strip()
                for value in row
            ),
            axis=1,
        )
    ].copy()

    # --------------------------------------------------------
    # Remove summary rows
    # --------------------------------------------------------

    df = df[
        ~df["SSCC Code"].apply(
            is_summary_row
        )
    ].copy()

    # --------------------------------------------------------
    # Remove rows containing explicit NA
    # --------------------------------------------------------

    df = df[
        ~df.apply(
            lambda row: any(
                is_explicit_na(value)
                for value in row
            ),
            axis=1,
        )
    ].copy()

    if df.empty:
        st.error(
            "No valid WMS rows remain after filtering."
        )
        st.stop()

    # --------------------------------------------------------
    # Add Load Ref, Date and Movement
    # --------------------------------------------------------

    london_tz = pytz.timezone(
        "Europe/London"
    )

    current_datetime = datetime.now(
        london_tz
    ).strftime(
        "%d/%m/%Y %H:%M"
    )

    df["Load Ref"] = load_ref.strip()
    df["Date"] = current_datetime
    df["Movement"] = jde_order_ref.strip()

    # --------------------------------------------------------
    # Reorder final columns
    # --------------------------------------------------------

    missing_final_columns = [
        column
        for column in FINAL_COLUMNS
        if column not in df.columns
    ]

    if missing_final_columns:

        st.error(
            "The following final columns are missing:\n\n"
            + "\n".join(
                f"- {column}"
                for column in missing_final_columns
            )
        )

        st.stop()

    output_df = df[
        FINAL_COLUMNS
    ].copy()

    # --------------------------------------------------------
    # SKU counts
    # --------------------------------------------------------

    sku_counts = (
        output_df["Item Code"]
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .value_counts()
        .rename_axis("Item Code")
        .reset_index(
            name="Count"
        )
    )

    # --------------------------------------------------------
    # Create CSV
    # --------------------------------------------------------

    csv_bytes = output_df.to_csv(
        index=False,
        encoding="utf-8-sig",
    ).encode("utf-8-sig")

    # --------------------------------------------------------
    # Filename
    # --------------------------------------------------------

    timestamp_for_filename = datetime.now(
        pytz.timezone("Europe/London")
    ).strftime(
        "%Y%m%d_%H%M%S"
    )

    filename = clean_filename(
        f"{load_ref.strip()}_"
        f"{timestamp_for_filename}.csv"
    )

    # --------------------------------------------------------
    # GitHub upload
    # --------------------------------------------------------

    st.subheader("GitHub Archive")

    with st.spinner(
        "Testing GitHub connection and uploading..."
    ):

        try:
            github_result = upload_to_github(
                csv_bytes,
                filename,
            )

        except Exception as exc:

            st.error(
                "❌ GitHub archive upload failed"
            )

            st.code(
                str(exc),
                language="text",
            )

            st.info(
                "For a classic GitHub Personal Access Token, "
                "check that the token has the `repo` scope and "
                "that the account has write access to the repository."
            )

            st.stop()

    # --------------------------------------------------------
    # Upload success
    # --------------------------------------------------------

    st.success(
        "✅ CSV successfully archived to GitHub."
    )

    st.write(
        f"**Repository:** "
        f"{github_result['repository']}"
    )

    st.write(
        f"**Branch:** "
        f"{github_result['branch']}"
    )

    st.write(
        f"**Archive path:** "
        f"`{github_result['path']}`"
    )

    if github_result.get("file_url"):

        st.markdown(
            "[📄 Open archived CSV on GitHub]"
            f"({github_result['file_url']})"
        )

    if github_result.get("commit_url"):

        st.markdown(
            "[🔗 Open GitHub commit]"
            f"({github_result['commit_url']})"
        )

    # --------------------------------------------------------
    # Local download
    # --------------------------------------------------------

    st.subheader("Download")

    st.download_button(
        label="⬇️ Download CSV",
        data=csv_bytes,
        file_name=filename,
        mime="text/csv",
    )

    # --------------------------------------------------------
    # Email
    # --------------------------------------------------------

    st.subheader("Email")

    # Build two-row SKU table:
    #
    # ITEM001    ITEM002    ITEM003
    # 10         25         7
    #
    if not sku_counts.empty:

        item_codes = [
            str(item)
            for item in sku_counts["Item Code"]
        ]

        item_counts = [
            str(count)
            for count in sku_counts["Count"]
        ]

        sku_header_row = "\t".join(
            item_codes
        )

        sku_count_row = "\t".join(
            item_counts
        )

        sku_table_text = (
            f"{sku_header_row}\n"
            f"{sku_count_row}"
        )

    else:
        sku_table_text = (
            "No SKU counts were available."
        )

    # The GitHub file URL is inserted directly into
    # the email body. Outlook should automatically
    # convert it into a clickable hyperlink.
    csv_download_url = (
        github_result.get("file_url")
        or ""
    )

    email_subject = (
        f"CSV File - Load Ref "
        f"{load_ref.strip()}"
    )

    email_body = (
        "Hi\n\n"
        f"Please download the CSV file for load ref "
        f"{load_ref.strip()} at the following link:\n\n"
        f"{csv_download_url}\n\n"
        "SKU Counts:\n\n"
        f"{sku_table_text}\n\n"
        "Thanks"
    )

    # --------------------------------------------------------
    # Build mailto URL
    # --------------------------------------------------------

    cc_value = ",".join(
        EMAIL_CC
    )

    mailto_url = (
        f"mailto:{EMAIL_TO}"
        f"?cc={urllib.parse.quote(cc_value)}"
        f"&subject={urllib.parse.quote(email_subject)}"
        f"&body={urllib.parse.quote(email_body)}"
    )

    st.markdown(
        f"[📧 Open Email in Outlook]({mailto_url})"
    )

    # --------------------------------------------------------
    # SKU summary
    # --------------------------------------------------------

    st.subheader("SKU Summary")

    if not sku_counts.empty:

        st.dataframe(
            sku_counts,
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "No SKU counts were available."
        )