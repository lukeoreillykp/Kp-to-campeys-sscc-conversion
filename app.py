import base64
import io
import re
import urllib.parse
from datetime import datetime

import pandas as pd
import pytz
import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont


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
        .main-title {
            text-align: center;
            font-size: 42px;
            font-weight: 700;
            margin-bottom: 5px;
        }

        .sub-title {
            text-align: center;
            font-size: 19px;
            margin-bottom: 35px;
        }

        .tool-card {
            border: 1px solid #d9d9d9;
            border-radius: 14px;
            padding: 22px;
            min-height: 260px;
            background: #ffffff;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            text-align: center;
            margin-bottom: 20px;
        }

        .tool-title {
            font-size: 22px;
            font-weight: 700;
            margin-top: 10px;
            margin-bottom: 8px;
        }

        .tool-description {
            font-size: 15px;
            color: #555555;
            min-height: 55px;
            margin-bottom: 15px;
        }

        div.stButton > button {
            width: 100%;
            border-radius: 8px;
            min-height: 45px;
            font-weight: 600;
        }

        .home-button {
            margin-bottom: 20px;
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
        username = st.secrets.get("github_username", GITHUB_OWNER)
        repo = st.secrets.get("github_repo", GITHUB_REPO)

        return token, username, repo

    except Exception:
        return None, None, None


def get_github_connection():
    """
    Validate the GitHub token and repository.
    Returns (headers, owner, repo) or raises an exception.
    """
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

    repo_url = f"https://api.github.com/repos/{username}/{repo}"

    response = requests.get(
        repo_url,
        headers=headers,
        timeout=20,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"GitHub repository check failed "
            f"({response.status_code}): {response.text}"
        )

    return headers, username, repo


def get_github_file(file_path):
    """
    Retrieve a file from GitHub.

    Returns:
        decoded content, GitHub API JSON response
    """
    headers, owner, repo = get_github_connection()

    encoded_path = urllib.parse.quote(file_path, safe="/")

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
            f"({response.status_code}): {response.text}"
        )

    data = response.json()

    if data.get("encoding") == "base64":
        content = base64.b64decode(
            data["content"].replace("\n", "")
        ).decode("utf-8-sig")

    else:
        download_url = data.get("download_url")

        if not download_url:
            raise RuntimeError("GitHub file has no downloadable content.")

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


def upload_github_file(file_path, file_content, commit_message):
    """
    Create or update a file in GitHub.
    Returns useful GitHub information including download URL.
    """
    headers, owner, repo = get_github_connection()

    encoded_path = urllib.parse.quote(file_path, safe="/")

    url = (
        f"https://api.github.com/repos/"
        f"{owner}/{repo}/contents/{encoded_path}"
    )

    # Check whether the file already exists so we can include its SHA.
    existing_response = requests.get(
        f"{url}?ref={GITHUB_BRANCH}",
        headers=headers,
        timeout=20,
    )

    sha = None

    if existing_response.status_code == 200:
        sha = existing_response.json().get("sha")

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
            f"({response.status_code}): {response.text}"
        )

    result = response.json()

    return {
        "file_url": result.get("content", {}).get("html_url"),
        "download_url": result.get("content", {}).get("download_url"),
        "commit_url": result.get("commit", {}).get("html_url"),
    }


def upload_to_github(csv_text, filename):
    """Upload an individual processed CSV into saved_loads."""
    file_path = f"{GITHUB_FOLDER}/{filename}"

    return upload_github_file(
        file_path=file_path,
        file_content=csv_text,
        commit_message=f"Archive load CSV: {filename}",
    )


# ============================================================
# SKU HISTORY
# ============================================================

def update_sku_history(load_ref, sku_counts):
    """
    Add a new row to the SKU history table.

    New SKU columns are automatically added.
    Existing loads receive 0 for newly introduced SKUs.
    """
    existing_content, _ = get_github_file(SKU_HISTORY_PATH)

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

    # Ensure the first two columns exist.
    if history_df.empty:
        history_df = pd.DataFrame(
            columns=["Date Submitted", "Load Ref"]
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

    # Keep the first two columns in the correct order.
    other_columns = [
        c
        for c in history_df.columns
        if c not in ["Date Submitted", "Load Ref"]
    ]

    history_df = history_df[
        ["Date Submitted", "Load Ref"] + other_columns
    ]

    # Add any new SKUs.
    for sku in sku_counts.keys():
        if sku not in history_df.columns:
            history_df[sku] = 0

    # Make sure existing rows have zero rather than NaN.
    sku_columns = [
        c
        for c in history_df.columns
        if c not in ["Date Submitted", "Load Ref"]
    ]

    if sku_columns and not history_df.empty:
        history_df[sku_columns] = (
            history_df[sku_columns]
            .fillna(0)
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0)
            .astype(int)
        )

    # Current load row.
    london = pytz.timezone("Europe/London")

    new_row = {
        "Date Submitted": datetime.now(london).strftime(
            "%d/%m/%Y %H:%M"
        ),
        "Load Ref": load_ref,
    }

    for sku in sku_columns:
        new_row[sku] = int(sku_counts.get(sku, 0))

    history_df = pd.concat(
        [
            history_df,
            pd.DataFrame([new_row]),
        ],
        ignore_index=True,
    )

    # Ensure all SKU columns are integers.
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
        commit_message=f"Update SKU history for load {load_ref}",
    )

    return history_df


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

    return value.strip("_") or "load"


def is_summary_row(value):
    if pd.isna(value):
        return False

    text = str(value).strip().lower()

    summary_terms = [
        "total",
        "subtotal",
        "summary",
    ]

    return any(term in text for term in summary_terms)


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
    """
    Attempt to read pasted WMS data as tab-delimited first,
    then comma-delimited.
    """
    raw_text = raw_text.strip()

    if not raw_text:
        raise ValueError("No WMS data was entered.")

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
# IMAGE / ICON CREATION
# ============================================================

def create_tool_image(tool_type):
    """
    Create a simple local illustration for each home-screen tool.
    This avoids relying on external image hosting.
    """
    width = 700
    height = 300

    image = Image.new(
        "RGB",
        (width, height),
        "white",
    )

    draw = ImageDraw.Draw(image)

    # Try a standard font. Fall back if unavailable.
    try:
        font_large = ImageFont.truetype(
            "DejaVuSans.ttf",
            120,
        )
        font_small = ImageFont.truetype(
            "DejaVuSans.ttf",
            34,
        )
    except Exception:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    icons = {
        "sender": ("📦", "SSCC"),
        "history": ("📊", "History"),
        "autostore": ("🏭", "AutoStore"),
        "contacts": ("👥", "Contacts"),
        "planner": ("📋", "Planner"),
    }

    emoji, label = icons.get(
        tool_type,
        ("🔧", "Tool"),
    )

    # Large centred icon.
    bbox = draw.textbbox(
        (0, 0),
        emoji,
        font=font_large,
    )

    emoji_width = bbox[2] - bbox[0]
    emoji_height = bbox[3] - bbox[1]

    draw.text(
        (
            (width - emoji_width) / 2,
            35,
        ),
        emoji,
        font=font_large,
    )

    # Label underneath.
    bbox = draw.textbbox(
        (0, 0),
        label,
        font=font_small,
    )

    label_width = bbox[2] - bbox[0]

    draw.text(
        (
            (width - label_width) / 2,
            205,
        ),
        label,
        font=font_small,
        fill="black",
    )

    return image


# ============================================================
# HOME SCREEN
# ============================================================

def show_home():
    st.markdown(
        '<div class="main-title">KP to Campeys</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="sub-title">'
        "Campeys Operations Tools"
        "</div>",
        unsafe_allow_html=True,
    )

    st.info(
        "Select a tool below."
    )

    col1, col2, col3 = st.columns(3)

    # --------------------------------------------------------
    # SSCC SENDER
    # --------------------------------------------------------

    with col1:
        st.markdown(
            '<div class="tool-card">',
            unsafe_allow_html=True,
        )

        st.image(
            create_tool_image("sender"),
            use_container_width=True,
        )

        st.markdown(
            '<div class="tool-title">'
            "KP to Campeys SSCC Sender"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-description">'
            "Convert WMS data into the Campeys SSCC CSV format "
            "and archive the load."
            "</div>",
            unsafe_allow_html=True,
        )

        if st.button(
            "Open SSCC Sender",
            key="open_sender",
        ):
            go_to("sender")
            st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

    # --------------------------------------------------------
    # LOAD HISTORY
    # --------------------------------------------------------

    with col2:
        st.markdown(
            '<div class="tool-card">',
            unsafe_allow_html=True,
        )

        st.image(
            create_tool_image("history"),
            use_container_width=True,
        )

        st.markdown(
            '<div class="tool-title">'
            "Load History"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-description">'
            "View the historical SKU quantities submitted for "
            "each Campeys load."
            "</div>",
            unsafe_allow_html=True,
        )

        if st.button(
            "Open Load History",
            key="open_history",
        ):
            go_to("history")
            st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

    # --------------------------------------------------------
    # AUTOSTORE
    # --------------------------------------------------------

    with col3:
        st.markdown(
            '<div class="tool-card">',
            unsafe_allow_html=True,
        )

        st.image(
            create_tool_image("autostore"),
            use_container_width=True,
        )

        st.markdown(
            '<div class="tool-title">'
            "AutoStore"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-description">'
            "Open the live AutoStore application."
            "</div>",
            unsafe_allow_html=True,
        )

        st.link_button(
            "Open AutoStore",
            AUTOSTORE_URL,
            use_container_width=True,
        )

        st.markdown("</div>", unsafe_allow_html=True)

    # Second row.
    col4, col5, col6 = st.columns(3)

    # --------------------------------------------------------
    # CONTACT LIST
    # --------------------------------------------------------

    with col4:
        st.markdown(
            '<div class="tool-card">',
            unsafe_allow_html=True,
        )

        st.image(
            create_tool_image("contacts"),
            use_container_width=True,
        )

        st.markdown(
            '<div class="tool-title">'
            "Campeys Contact List"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-description">'
            "View the Campeys contact list stored in the "
            "GitHub repository."
            "</div>",
            unsafe_allow_html=True,
        )

        if st.button(
            "Open Contact List",
            key="open_contacts",
        ):
            go_to("contacts")
            st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

    # --------------------------------------------------------
    # LOAD PLANNER
    # --------------------------------------------------------

    with col5:
        st.markdown(
            '<div class="tool-card">',
            unsafe_allow_html=True,
        )

        st.image(
            create_tool_image("planner"),
            use_container_width=True,
        )

        st.markdown(
            '<div class="tool-title">'
            "Campeys Load Planner"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-description">'
            "Open the Campeys collection request / load "
            "planner workbook."
            "</div>",
            unsafe_allow_html=True,
        )

        st.link_button(
            "Open Load Planner",
            CAMPEYS_LOAD_PLANNER_URL,
            use_container_width=True,
        )

        st.markdown("</div>", unsafe_allow_html=True)

    with col6:
        st.markdown(
            '<div class="tool-card">',
            unsafe_allow_html=True,
        )

        st.markdown(
            "<br><br><br>",
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-title">'
            "More tools"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="tool-description">'
            "Additional Campeys tools can be added here later."
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# HISTORY SCREEN
# ============================================================

def show_history():
    st.button(
        "← Back to Home",
        key="history_back",
        on_click=go_to,
        args=("home",),
    )

    st.title("📊 Load History")

    st.caption(
        "SKU quantities submitted for each processed load."
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
            io.StringIO(history_content),
        )

        st.dataframe(
            history_df,
            use_container_width=True,
            hide_index=True,
        )

        st.download_button(
            "Download Load History CSV",
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
# CONTACT SCREEN
# ============================================================

def show_contacts():
    st.button(
        "← Back to Home",
        key="contacts_back",
        on_click=go_to,
        args=("home",),
    )

    st.title("👥 Campeys Contact List")

    st.caption(
        "Contact information retrieved from the GitHub repository."
    )

    try:
        contact_content, contact_metadata = get_github_file(
            CONTACT_LIST_PATH
        )

        if not contact_content:
            st.warning(
                "The Campeys contact list could not be found "
                "in the GitHub repository."
            )
            return

        st.text_area(
            "Contact List",
            value=contact_content,
            height=500,
        )

        st.download_button(
            "Download Contact List",
            data=contact_content.encode("utf-8"),
            file_name=CONTACT_LIST_PATH,
            mime="text/plain",
            use_container_width=True,
        )

        # If GitHub supplied a direct download URL, provide
        # an external-open option as well.
        if contact_metadata:
            download_url = contact_metadata.get(
                "download_url"
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

    st.title("📦 KP to Campeys SSCC Sender")

    st.caption(
        "Convert WMS data, archive the CSV and maintain the "
        "SKU load history."
    )

    # --------------------------------------------------------
    # INPUTS
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
        placeholder=(
            "Paste the WMS export here..."
        ),
    )

    process_button = st.button(
        "Process & Archive",
        type="primary",
        use_container_width=True,
    )

    if not process_button:
        return

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

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
        # ----------------------------------------------------
        # READ DATA
        # ----------------------------------------------------

        df = read_wms_data(wms_data)

        missing_columns = [
            column
            for column in EXPECTED_COLUMNS
            if column not in df.columns
        ]

        if missing_columns:
            st.error(
                "The WMS data is missing the following columns:"
            )

            st.write(missing_columns)

            return

        # ----------------------------------------------------
        # CLEAN DATA
        # ----------------------------------------------------

        df = df.copy()

        # Remove completely blank rows.
        df = df.dropna(
            how="all"
        )

        # Remove rows where SSCC Code contains summary text.
        df = df[
            ~df["SSCC Code"].apply(
                is_summary_row
            )
        ]

        # Remove rows containing explicit NA values.
        na_mask = df.applymap(
            is_explicit_na
        ).any(axis=1)

        df = df[
            ~na_mask
        ]

        # ----------------------------------------------------
        # ADD REQUIRED FIELDS
        # ----------------------------------------------------

        london = pytz.timezone(
            "Europe/London"
        )

        current_datetime = datetime.now(
            london
        ).strftime(
            "%d/%m/%Y %H:%M"
        )

        df["Load Ref"] = load_ref.strip()
        df["Date"] = current_datetime
        df["Movement"] = jde_order_ref.strip()

        # ----------------------------------------------------
        # REORDER COLUMNS
        # ----------------------------------------------------

        output_df = df[
            FINAL_COLUMNS
        ].copy()

        # ----------------------------------------------------
        # SKU COUNTS
        # ----------------------------------------------------

        sku_counts = (
            output_df["Item Code"]
            .astype(str)
            .str.strip()
            .value_counts()
            .sort_index()
            .to_dict()
        )

        # ----------------------------------------------------
        # CSV
        # ----------------------------------------------------

        csv_buffer = io.StringIO()

        output_df.to_csv(
            csv_buffer,
            index=False,
            encoding="utf-8-sig",
        )

        csv_text = csv_buffer.getvalue()

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

        # ----------------------------------------------------
        # GITHUB
        # ----------------------------------------------------

        with st.spinner(
            "Uploading CSV to GitHub..."
        ):
            github_result = upload_to_github(
                csv_text,
                filename,
            )

        # ----------------------------------------------------
        # SKU HISTORY
        # ----------------------------------------------------

        with st.spinner(
            "Updating SKU history..."
        ):
            history_df = update_sku_history(
                load_ref=load_ref.strip(),
                sku_counts=sku_counts,
            )

        st.success(
            "CSV archived and SKU history updated successfully."
        )

        # ----------------------------------------------------
        # DISPLAY ARCHIVE INFORMATION
        # ----------------------------------------------------

        st.subheader(
            "Archived CSV"
        )

        if github_result.get("file_url"):
            st.link_button(
                "Open Archived CSV on GitHub",
                github_result["file_url"],
                use_container_width=True,
            )

        if github_result.get("download_url"):
            st.link_button(
                "Download Archived CSV",
                github_result["download_url"],
                use_container_width=True,
            )

        # ----------------------------------------------------
        # SKU COUNTS
        # ----------------------------------------------------

        st.subheader(
            "SKU Counts"
        )

        sku_display = pd.DataFrame(
            [
                sku_counts
            ]
        )

        st.dataframe(
            sku_display,
            use_container_width=True,
            hide_index=True,
        )

        # ----------------------------------------------------
        # HISTORY
        # ----------------------------------------------------

        st.subheader(
            "Load History"
        )

        st.dataframe(
            history_df,
            use_container_width=True,
            hide_index=True,
        )

        # ----------------------------------------------------
        # LOCAL DOWNLOAD
        # ----------------------------------------------------

        st.download_button(
            "Download CSV",
            data=csv_text.encode("utf-8-sig"),
            file_name=filename,
            mime="text/csv",
            use_container_width=True,
        )

        # ----------------------------------------------------
        # EMAIL LINK
        # ----------------------------------------------------

        csv_download_url = (
            github_result.get("file_url")
            or github_result.get("download_url")
            or ""
        )

        sku_headers = "\t".join(
            str(key)
            for key in sku_counts.keys()
        )

        sku_values = "\t".join(
            str(value)
            for value in sku_counts.values()
        )

        sku_table_text = (
            f"{sku_headers}\n"
            f"{sku_values}"
        )

        email_subject = (
            f"CSV File - Load Ref {load_ref.strip()}"
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

        st.subheader(
            "Email"
        )

        st.markdown(
            "The CSV is ready to send to the Campeys team."
        )

        st.markdown(
            f"[📧 Open Email in Outlook]({mailto_url})"
        )

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

elif st.session_state.page == "contacts":
    show_contacts()

else:
    st.session_state.page = "home"
    st.rerun()