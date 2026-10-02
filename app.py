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

# SKU history file stored in the root of the GitHub repository
SKU_HISTORY_PATH = "sku_counts_history.csv"

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
        raise ValueError(
            "No WMS data was supplied."
        )

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
# GITHUB CONNECTION
# ============================================================

def get_github_connection():
    """Return GitHub authentication and API information."""

    token, username, repo = get_github_settings()

    repo_url = (
        f"https://api.github.com/repos/"
        f"{urllib.parse.quote(username, safe='')}/"
        f"{urllib.parse.quote(repo, safe='')}"
    )

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "KP-to-Campeys-SSCC-Sender",
    }

    # --------------------------------------------------------
    # Check authentication
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
            "is valid."
        )

    authenticated_user = user_response.json().get(
        "login",
        "unknown",
    )

    # --------------------------------------------------------
    # Check repository
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
            f"GitHub message: {github_message}"
        )

    repo_info = repo_response.json()

    default_branch = repo_info.get(
        "default_branch",
        GITHUB_BRANCH,
    )

    return {
        "token": token,
        "username": username,
        "repo": repo,
        "repo_url": repo_url,
        "headers": headers,
        "authenticated_user": authenticated_user,
        "branch": default_branch,
    }


# ============================================================
# GITHUB FILE HELPERS
# ============================================================

def get_github_file(connection, file_path):
    """
    Get a file from GitHub.

    Returns:
        {
            "exists": bool,
            "sha": str or None,
            "content": bytes or None
        }
    """

    encoded_path = "/".join(
        urllib.parse.quote(
            part,
            safe="",
        )
        for part in file_path.split("/")
    )

    file_url = (
        f"{connection['repo_url']}"
        f"/contents/{encoded_path}"
    )

    params = {
        "ref": connection["branch"],
    }

    try:
        response = requests.get(
            file_url,
            headers=connection["headers"],
            params=params,
            timeout=20,
        )

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not read GitHub file '{file_path}': {exc}"
        ) from exc

    # File does not exist yet
    if response.status_code == 404:
        return {
            "exists": False,
            "sha": None,
            "content": None,
            "url": file_url,
        }

    if response.status_code != 200:

        try:
            response_json = response.json()

            github_message = response_json.get(
                "message",
                response.text,
            )

        except Exception:
            github_message = response.text

        raise RuntimeError(
            f"Could not read GitHub file '{file_path}'.\n\n"
            f"HTTP status: {response.status_code}\n"
            f"GitHub message: {github_message}"
        )

    try:
        file_info = response.json()

        encoded_content = file_info.get(
            "content",
            "",
        )

        # GitHub may include line breaks in Base64
        encoded_content = encoded_content.replace(
            "\n",
            "",
        )

        content = base64.b64decode(
            encoded_content
        )

        return {
            "exists": True,
            "sha": file_info.get("sha"),
            "content": content,
            "url": file_info.get(
                "html_url"
            ),
        }

    except Exception as exc:
        raise RuntimeError(
            f"Could not decode GitHub file '{file_path}': {exc}"
        ) from exc


def upload_github_file(
    connection,
    file_path,
    file_bytes,
    commit_message,
    existing_sha=None,
):
    """Create or update a file on GitHub."""

    encoded_path = "/".join(
        urllib.parse.quote(
            part,
            safe="",
        )
        for part in file_path.split("/")
    )

    file_url = (
        f"{connection['repo_url']}"
        f"/contents/{encoded_path}"
    )

    encoded_content = base64.b64encode(
        file_bytes
    ).decode("utf-8")

    payload = {
        "message": commit_message,
        "content": encoded_content,
        "branch": connection["branch"],
    }

    if existing_sha:
        payload["sha"] = existing_sha

    try:
        response = requests.put(
            file_url,
            headers=connection["headers"],
            json=payload,
            timeout=30,
        )

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not connect to GitHub during upload: {exc}"
        ) from exc

    if response.status_code not in (
        200,
        201,
    ):

        try:
            response_json = response.json()

            github_message = response_json.get(
                "message",
                response.text,
            )

            github_errors = response_json.get(
                "errors",
                "",
            )

        except Exception:
            github_message = response.text
            github_errors = ""

        error_text = (
            "GitHub upload failed.\n\n"
            f"Authenticated user: "
            f"{connection['authenticated_user']}\n"
            f"Repository: "
            f"{connection['username']}/"
            f"{connection['repo']}\n"
            f"Branch: {connection['branch']}\n"
            f"Path: {file_path}\n"
            f"HTTP status: {response.status_code}\n"
            f"GitHub message: {github_message}"
        )

        if github_errors:
            error_text += (
                f"\nGitHub errors: {github_errors}"
            )

        raise RuntimeError(error_text)

    try:
        result = response.json()

    except Exception:
        result = {}

    return {
        "file_url": (
            result
            .get("content", {})
            .get("html_url")
        ),
        "commit_url": (
            result
            .get("commit", {})
            .get("html_url")
        ),
    }


# ============================================================
# UPLOAD INDIVIDUAL LOAD CSV
# ============================================================

def upload_to_github(
    csv_bytes,
    filename,
    connection,
):
    """Upload the individual load CSV."""

    filename = clean_filename(filename)

    file_path = (
        f"{GITHUB_FOLDER}/{filename}"
    )

    existing_file = get_github_file(
        connection,
        file_path,
    )

    result = upload_github_file(
        connection=connection,
        file_path=file_path,
        file_bytes=csv_bytes,
        commit_message=(
            f"Archive WMS load CSV: {filename}"
        ),
        existing_sha=existing_file.get(
            "sha"
        ),
    )

    return {
        "filename": filename,
        "path": file_path,
        "authenticated_user": (
            connection["authenticated_user"]
        ),
        "repository": (
            f"{connection['username']}/"
            f"{connection['repo']}"
        ),
        "branch": connection["branch"],
        "commit_url": result.get(
            "commit_url"
        ),
        "file_url": result.get(
            "file_url"
        ),
    }


# ============================================================
# UPDATE SKU HISTORY
# ============================================================

def update_sku_history(
    connection,
    load_ref,
    submission_date,
    sku_counts,
):
    """
    Read the existing SKU history from GitHub,
    add the current load as a new row, add any new
    SKU columns, and upload the updated history.
    """

    existing_file = get_github_file(
        connection,
        SKU_HISTORY_PATH,
    )

    # --------------------------------------------------------
    # Read existing history
    # --------------------------------------------------------

    if existing_file["exists"]:

        try:
            history_df = pd.read_csv(
                io.BytesIO(
                    existing_file["content"]
                ),
                dtype=str,
                keep_default_na=False,
            )

        except Exception as exc:
            raise RuntimeError(
                "The existing GitHub SKU history file "
                "could not be read.\n\n"
                f"Error: {exc}"
            ) from exc

    else:

        history_df = pd.DataFrame(
            columns=[
                "Date Submitted",
                "Load Ref",
            ]
        )

    # --------------------------------------------------------
    # Ensure required columns exist
    # --------------------------------------------------------

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
    # Clean existing columns
    # --------------------------------------------------------

    history_df.columns = [
        str(column).strip()
        for column in history_df.columns
    ]

    # --------------------------------------------------------
    # Build new row
    # --------------------------------------------------------

    new_row = {
        "Date Submitted": submission_date,
        "Load Ref": load_ref,
    }

    for _, row in sku_counts.iterrows():

        item_code = str(
            row["Item Code"]
        ).strip()

        if not item_code:
            continue

        try:
            count = int(
                row["Count"]
            )

        except (ValueError, TypeError):
            count = 0

        new_row[item_code] = count

    # --------------------------------------------------------
    # Add any new SKU columns
    # --------------------------------------------------------

    for column in new_row:

        if column not in history_df.columns:

            history_df[column] = 0

    # --------------------------------------------------------
    # Make sure all SKU columns contain usable values
    # --------------------------------------------------------

    fixed_columns = [
        "Date Submitted",
        "Load Ref",
    ]

    sku_columns = [
        column
        for column in history_df.columns
        if column not in fixed_columns
    ]

    for column in sku_columns:

        if column not in new_row:
            new_row[column] = 0

    # --------------------------------------------------------
    # Add new row
    # --------------------------------------------------------

    new_row_df = pd.DataFrame(
        [new_row],
        columns=history_df.columns,
    )

    history_df = pd.concat(
        [
            history_df,
            new_row_df,
        ],
        ignore_index=True,
    )

    # --------------------------------------------------------
    # Keep the two fixed columns first
    # --------------------------------------------------------

    sku_columns = [
        column
        for column in history_df.columns
        if column not in fixed_columns
    ]

    # Sort SKU columns numerically where possible,
    # otherwise alphabetically.
    def sku_sort_key(value):
        value = str(value)

        if value.isdigit():
            return (
                0,
                int(value),
            )

        return (
            1,
            value.lower(),
        )

    sku_columns = sorted(
        sku_columns,
        key=sku_sort_key,
    )

    history_df = history_df[
        fixed_columns + sku_columns
    ]

    # --------------------------------------------------------
    # Ensure blank historical SKU cells become 0
    # --------------------------------------------------------

    for column in sku_columns:

        history_df[column] = (
            pd.to_numeric(
                history_df[column],
                errors="coerce",
            )
            .fillna(0)
            .astype(int)
        )

    # --------------------------------------------------------
    # Export history CSV
    # --------------------------------------------------------

    history_bytes = history_df.to_csv(
        index=False,
        encoding="utf-8-sig",
    ).encode("utf-8-sig")

    # --------------------------------------------------------
    # Upload updated history to GitHub
    # --------------------------------------------------------

    result = upload_github_file(
        connection=connection,
        file_path=SKU_HISTORY_PATH,
        file_bytes=history_bytes,
        commit_message=(
            f"Update SKU counts history - "
            f"Load Ref {load_ref}"
        ),
        existing_sha=existing_file.get(
            "sha"
        ),
    )

    return {
        "history_df": history_df,
        "file_url": result.get(
            "file_url"
        ),
        "commit_url": result.get(
            "commit_url"
        ),
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
    # Validate inputs
    # --------------------------------------------------------

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

    if not wms_data.strip():
        st.error(
            "Please paste the WMS data."
        )
        st.stop()

    # --------------------------------------------------------
    # Read WMS data
    # --------------------------------------------------------

    try:
        df = read_wms_data(
            wms_data
        )

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
    # Keep expected columns
    # --------------------------------------------------------

    df = df[
        EXPECTED_COLUMNS
    ].copy()

    # --------------------------------------------------------
    # Remove blank rows
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
    # Date / Load Ref / Movement
    # --------------------------------------------------------

    london_tz = pytz.timezone(
        "Europe/London"
    )

    current_datetime = datetime.now(
        london_tz
    ).strftime(
        "%d/%m/%Y %H:%M"
    )

    df["Load Ref"] = (
        load_ref.strip()
    )

    df["Date"] = current_datetime

    df["Movement"] = (
        jde_order_ref.strip()
    )

    # --------------------------------------------------------
    # Final columns
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
        .replace(
            "",
            pd.NA,
        )
        .dropna()
        .value_counts()
        .rename_axis(
            "Item Code"
        )
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

    timestamp_for_filename = (
        datetime.now(
            pytz.timezone(
                "Europe/London"
            )
        ).strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    filename = clean_filename(
        f"{load_ref.strip()}_"
        f"{timestamp_for_filename}.csv"
    )

    # ========================================================
    # GITHUB
    # ========================================================

    st.subheader(
        "GitHub Archive"
    )

    with st.spinner(
        "Connecting to GitHub..."
    ):

        try:
            connection = (
                get_github_connection()
            )

        except Exception as exc:

            st.error(
                "❌ GitHub connection failed"
            )

            st.code(
                str(exc),
                language="text",
            )

            st.stop()

    # --------------------------------------------------------
    # Upload individual CSV
    # --------------------------------------------------------

    with st.spinner(
        "Uploading load CSV..."
    ):

        try:

            github_result = (
                upload_to_github(
                    csv_bytes,
                    filename,
                    connection,
                )
            )

        except Exception as exc:

            st.error(
                "❌ GitHub load CSV upload failed"
            )

            st.code(
                str(exc),
                language="text",
            )

            st.stop()

    st.success(
        "✅ Load CSV successfully archived to GitHub."
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

    if github_result.get(
        "file_url"
    ):

        st.markdown(
            "[📄 Open archived CSV on GitHub]"
            f"({github_result['file_url']})"
        )

    if github_result.get(
        "commit_url"
    ):

        st.markdown(
            "[🔗 Open GitHub commit]"
            f"({github_result['commit_url']})"
        )

    # ========================================================
    # UPDATE SKU HISTORY
    # ========================================================

    st.subheader(
        "SKU Counts History"
    )

    with st.spinner(
        "Updating SKU counts history..."
    ):

        try:

            history_result = (
                update_sku_history(
                    connection=connection,
                    load_ref=load_ref.strip(),
                    submission_date=current_datetime,
                    sku_counts=sku_counts,
                )
            )

        except Exception as exc:

            st.error(
                "❌ SKU history update failed"
            )

            st.code(
                str(exc),
                language="text",
            )

            st.info(
                "The individual load CSV was successfully "
                "uploaded, but the SKU history table could "
                "not be updated."
            )

            st.stop()

    st.success(
        "✅ SKU counts history updated."
    )

    st.write(
        f"**History rows:** "
        f"{len(history_result['history_df'])}"
    )

    st.write(
        f"**SKU columns:** "
        f"{max(0, len(history_result['history_df'].columns) - 2)}"
    )

    if history_result.get(
        "file_url"
    ):

        st.markdown(
            "[📊 Open SKU Counts History on GitHub]"
            f"({history_result['file_url']})"
        )

    # --------------------------------------------------------
    # Show history table in app
    # --------------------------------------------------------

    st.dataframe(
        history_result["history_df"],
        use_container_width=True,
        hide_index=True,
    )

    # ========================================================
    # LOCAL DOWNLOAD
    # ========================================================

    st.subheader(
        "Download"
    )

    st.download_button(
        label="⬇️ Download CSV",
        data=csv_bytes,
        file_name=filename,
        mime="text/csv",
    )

    # ========================================================
    # EMAIL
    # ========================================================

    st.subheader(
        "Email"
    )

    # --------------------------------------------------------
    # Build two-row SKU table for email
    # --------------------------------------------------------

    if not sku_counts.empty:

        item_codes = [
            str(item)
            for item in sku_counts[
                "Item Code"
            ]
        ]

        item_counts = [
            str(count)
            for count in sku_counts[
                "Count"
            ]
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

    # --------------------------------------------------------
    # Email
    # --------------------------------------------------------

    csv_download_url = (
        github_result.get(
            "file_url"
        )
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

    # ========================================================
    # SKU SUMMARY
    # ========================================================

    st.subheader(
        "Current Load SKU Summary"
    )

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