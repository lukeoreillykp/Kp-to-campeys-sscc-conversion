import base64
import io
import re
import urllib.parse
from datetime import datetime

import pandas as pd
import pytz
import requests
import streamlit as st


# ---------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------

st.set_page_config(
    page_title="KP to Campeys SSCC Sender",
    layout="wide",
)

st.title("📦 KP to Campeys SSCC Sender")


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------

def is_invalid_summary_row(row):
    """
    Removes obvious WMS summary/footer rows.

    Only checks the SSCC Code column so legitimate values in
    other columns aren't accidentally removed.
    """

    value = row.get("SSCC Code", "")

    if pd.isna(value):
        return True

    value = str(value).strip().lower()

    if not value:
        return True

    if "total" in value:
        return True

    if value in {"na", "n/a", "n / a", "n.a.", "n.a"}:
        return True

    return False


def contains_explicit_na(value):
    """
    Returns True only when a cell explicitly contains an NA
    marker.

    This deliberately does NOT search for the letters 'na'
    inside normal words.

    For example:
        'N/A'       -> True
        'NA'        -> True
        'N-A'       -> True
        'Banana'    -> False
        'NAT123'    -> False
    """

    if pd.isna(value):
        return False

    cleaned = str(value).strip().lower()

    # Normalise whitespace and punctuation used in NA variants.
    normalised = re.sub(r"[\s#\/\\\-_.]+", "", cleaned)

    return normalised in {
        "na",
        "n/a".replace("/", ""),
        "n-a".replace("-", ""),
        "n.a.".replace(".", ""),
    }


def sanitise_filename(filename):
    """
    Creates a safe filename for GitHub and local downloads.
    """

    filename = str(filename).strip()

    # Remove characters that are invalid/problematic in filenames.
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)

    # Replace line breaks and excessive whitespace.
    filename = re.sub(r"\s+", " ", filename)

    # Prevent filenames such as "." or ".."
    if filename in {"", ".", ".."}:
        return "wms_output"

    return filename


def get_github_settings():
    """
    Reads GitHub settings from Streamlit secrets.

    Expected secrets:

        github_token = "..."
        github_username = "lukeoreillykp"
        github_repo = "Kp-to-campeys-sscc-conversion"
    """

    try:
        token = st.secrets["github_token"]
        username = st.secrets["github_username"]
        repo = st.secrets["github_repo"]
    except Exception as exc:
        raise RuntimeError(
            "GitHub settings are missing from Streamlit secrets. "
            "Please check github_token, github_username and github_repo."
        ) from exc

    token = str(token).strip()
    username = str(username).strip().strip("/")
    repo = str(repo).strip().strip("/")

    if not token:
        raise RuntimeError("github_token is empty.")

    if not username:
        raise RuntimeError("github_username is empty.")

    if not repo:
        raise RuntimeError("github_repo is empty.")

    return token, username, repo


def upload_to_github_archive(csv_bytes, csv_filename):
    """
    Uploads the processed CSV into:

        saved_loads/<filename>.csv

    in the configured GitHub repository.

    Handles both:
        - creating a new file
        - replacing an existing file
    """

    try:
        token, username, repo = get_github_settings()

        # GitHub Contents API.
        # The previous version incorrectly used github.com here.
        api_url = (
            f"https://api.github.com/repos/"
            f"{urllib.parse.quote(username, safe='')}/"
            f"{urllib.parse.quote(repo, safe='')}/contents/"
            f"saved_loads/"
            f"{urllib.parse.quote(csv_filename, safe='')}"
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        encoded_content = base64.b64encode(csv_bytes).decode("utf-8")

        # Check whether the file already exists.
        check_response = requests.get(
            api_url,
            headers=headers,
            timeout=20,
        )

        payload = {
            "message": f"Archive automated reformat entry: {csv_filename}",
            "content": encoded_content,
        }

        # Existing file: GitHub requires the existing SHA.
        if check_response.status_code == 200:
            existing_file = check_response.json()
            existing_sha = existing_file.get("sha")

            if not existing_sha:
                st.warning(
                    "⚠️ GitHub found the archive file but could not determine "
                    "its SHA, so the archive was not updated."
                )
                return False

            payload["sha"] = existing_sha

        # 404 means the file doesn't exist yet.
        elif check_response.status_code == 404:
            pass

        else:
            st.warning(
                "⚠️ Could not check the GitHub archive. "
                f"GitHub returned HTTP {check_response.status_code}: "
                f"{check_response.text}"
            )
            return False

        upload_response = requests.put(
            api_url,
            headers=headers,
            json=payload,
            timeout=30,
        )

        if upload_response.status_code in {200, 201}:
            st.success(
                f"📂 Cloud Archive: '{csv_filename}' successfully "
                "saved to your GitHub repository."
            )
            return True

        st.warning(
            "⚠️ The data was processed, but GitHub could not save the archive. "
            f"HTTP {upload_response.status_code}: "
            f"{upload_response.text}"
        )
        return False

    except requests.RequestException as exc:
        st.warning(
            "⚠️ The data was processed, but the GitHub archive could not "
            f"be reached: {exc}"
        )
        return False

    except Exception as exc:
        st.warning(
            f"⚠️ GitHub integration configuration error: {exc}"
        )
        return False


def parse_wms_data(pasted_text):
    """
    Reads pasted WMS data.

    Supports:
        - tab-separated data copied from WMS
        - comma-separated CSV data
    """

    text = pasted_text.strip()

    if not text:
        raise ValueError("Please paste some WMS data first.")

    separator = "\t" if "\t" in text else ","

    df = pd.read_csv(
        io.StringIO(text),
        sep=separator,
        dtype=str,
        keep_default_na=False,
    )

    # Clean column names.
    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
    )

    return df


# ---------------------------------------------------------
# INPUTS
# ---------------------------------------------------------

st.subheader("1. Additional Information")

col1, col2 = st.columns(2)

with col1:
    extra_info_1 = st.text_input(
        "Enter Load Ref (Names your file and repeats in Load Ref column):"
    )

with col2:
    jde_order_ref = st.text_input(
        "Enter JDE Order Ref (Populates the Movement column):"
    )


# ---------------------------------------------------------
# RAW DATA INPUT
# ---------------------------------------------------------

st.subheader("2. Paste WMS Data Below")

st.caption(
    "Include your header row! Copy the entire grid from your WMS "
    "(Ctrl+A → Ctrl+C) and paste it below (Ctrl+V). "
    "Column order does not matter."
)

pasted_text = st.text_area(
    "Paste data here:",
    height=250,
    placeholder="SSCC Code\tItem Code\tDescription\tUnits...",
)


# ---------------------------------------------------------
# PROCESS DATA
# ---------------------------------------------------------

if st.button("Process & Generate Files", type="primary"):

    if not pasted_text.strip():
        st.error("Please paste some data into the text box first.")
        st.stop()

    if not extra_info_1.strip() or not jde_order_ref.strip():
        st.warning(
            "Please fill out both the Load Ref and JDE Order Ref fields above."
        )
        st.stop()

    try:

        # -------------------------------------------------
        # READ DATA
        # -------------------------------------------------

        df_raw = parse_wms_data(pasted_text)

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
                + "\n".join(f"- {column}" for column in missing_cols)
                + "\n\nPlease check that your WMS header names match."
            )
            st.stop()

        # -------------------------------------------------
        # REMOVE COMPLETELY EMPTY ROWS
        # -------------------------------------------------

        df_clean = df_raw.replace(r"^\s*$", pd.NA, regex=True)
        df_clean = df_clean.dropna(how="all").copy()

        original_row_count = len(df_clean)

        # -------------------------------------------------
        # PROTECTION 1:
        # REMOVE SUMMARY / TOTAL ROWS
        # -------------------------------------------------

        summary_rows_mask = df_clean.apply(
            is_invalid_summary_row,
            axis=1,
        )

        summary_rows_removed = int(summary_rows_mask.sum())

        df_clean = df_clean[
            ~summary_rows_mask
        ].copy()

        # -------------------------------------------------
        # PROTECTION 2:
        # REMOVE ROWS WITH EXPLICIT NA VALUES
        # -------------------------------------------------

        row_has_explicit_na = df_clean.apply(
            lambda row: row.map(contains_explicit_na).any(),
            axis=1,
        )

        na_rows_removed = int(row_has_explicit_na.sum())

        df_filtered = df_clean[
            ~row_has_explicit_na
        ].copy()

        total_dropped = (
            summary_rows_removed
            + na_rows_removed
        )

        # -------------------------------------------------
        # CHECK REMAINING DATA
        # -------------------------------------------------

        if df_filtered.empty:
            st.error(
                "Filtering complete: no valid data was left to convert."
            )
            st.stop()

        # -------------------------------------------------
        # UK DATE/TIME
        # -------------------------------------------------

        local_tz = pytz.timezone("Europe/London")

        current_time = datetime.now(
            local_tz
        ).strftime("%d/%m/%Y %H:%M")

        # -------------------------------------------------
        # SKU SUMMARY
        # -------------------------------------------------

        sku_counts = (
            df_filtered["Item Code"]
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .value_counts()
        )

        clean_text_summary = "\n".join(
            f"• SKU: {sku} -> Count: {count}"
            for sku, count in sku_counts.items()
        )

        # -------------------------------------------------
        # ADD METADATA
        # -------------------------------------------------

        df_filtered["Load Ref"] = extra_info_1.strip()
        df_filtered["Date"] = current_time
        df_filtered["Movement"] = jde_order_ref.strip()

        # -------------------------------------------------
        # FINAL COLUMN ORDER
        # -------------------------------------------------

        missing_output_columns = [
            column
            for column in FINAL_COLUMN_ORDER
            if column not in df_filtered.columns
        ]

        if missing_output_columns:
            st.error(
                "❌ The following output columns are missing:\n\n"
                + "\n".join(
                    f"- {column}"
                    for column in missing_output_columns
                )
            )
            st.stop()

        output_df = df_filtered[
            FINAL_COLUMN_ORDER
        ].copy()

        # -------------------------------------------------
        # SUCCESS MESSAGE
        # -------------------------------------------------

        st.success(
            "🎉 WMS data successfully converted! "
            f"Dropped {total_dropped} invalid row(s)."
        )

        st.caption(
            f"Input rows: {original_row_count} | "
            f"Rows removed: {total_dropped} | "
            f"Output rows: {len(output_df)}"
        )

        st.dataframe(
            output_df,
            use_container_width=True,
        )

        # -------------------------------------------------
        # CREATE CSV
        # -------------------------------------------------

        safe_filename = sanitise_filename(
            extra_info_1
        )

        csv_filename = (
            f"{safe_filename}.csv"
            if safe_filename.lower().endswith(".csv")
            else f"{safe_filename}.csv"
        )

        csv_data = output_df.to_csv(
            index=False
        )

        csv_bytes = csv_data.encode(
            "utf-8-sig"
        )

        # -------------------------------------------------
        # GITHUB ARCHIVE
        # -------------------------------------------------

        upload_to_github_archive(
            csv_bytes,
            csv_filename,
        )

        # -------------------------------------------------
        # EXPORT SECTION
        # -------------------------------------------------

        st.subheader(
            "3. Export Processed Data"
        )

        btn_col1, btn_col2, btn_col3 = st.columns(3)

        # -------------------------------------------------
        # DOWNLOAD CSV
        # -------------------------------------------------

        with btn_col1:

            st.download_button(
                label="📥 1. Download CSV Locally",
                data=csv_bytes,
                file_name=csv_filename,
                mime="text/csv",
                type="primary",
                use_container_width=True,
            )

        # -------------------------------------------------
        # EMAIL
        # -------------------------------------------------

        with btn_col2:

            email_recipient = (
                "Luke.oreilly@kpsnacks.com"
            )

            email_subject = (
                f"{extra_info_1} Pallet Count by SKU"
            )

            email_body = (
                "Hi Luke,\n\n"
                "Here is the pallet count breakdown "
                f"summarized by unique SKU for Load Ref: "
                f"{extra_info_1}\n\n"
                f"{clean_text_summary}\n\n"
                "Regards,\n"
                "WMS Automated Conversion Engine"
            )

            mailto_link = (
                f"mailto:{email_recipient}"
                f"?subject={urllib.parse.quote(email_subject)}"
                f"&body={urllib.parse.quote(email_body)}"
            )

            st.link_button(
                "📧 2. Open Pre-Filled Email",
                url=mailto_link,
                use_container_width=True,
            )

        # -------------------------------------------------
        # GITHUB ARCHIVE LINK
        # -------------------------------------------------

        with btn_col3:

            try:
                _, github_username, github_repo = (
                    get_github_settings()
                )

                repo_view_url = (
                    "https://github.com/"
                    f"{urllib.parse.quote(github_username, safe='')}/"
                    f"{urllib.parse.quote(github_repo, safe='')}"
                    "/tree/main/saved_loads"
                )

                st.link_button(
                    "📋 3. Access Repository Archive",
                    url=repo_view_url,
                    use_container_width=True,
                )

            except Exception:
                st.info(
                    "GitHub archive link unavailable. "
                    "Check your Streamlit secrets."
                )

        # -------------------------------------------------
        # SKU SUMMARY
        # -------------------------------------------------

        st.write("---")

        st.subheader(
            f"📊 {extra_info_1} Pallet Count by SKU"
        )

        if not sku_counts.empty:

            summary_df = (
                sku_counts
                .rename("Pallet Count")
                .reset_index()
                .rename(columns={"index": "SKU"})
            )

            st.dataframe(
                summary_df,
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.info(
                "No SKU counts were available."
            )

    except pd.errors.ParserError as exc:

        st.error(
            "❌ I couldn't read the pasted WMS data. "
            "Please make sure you copied the header row and "
            "the data is tab- or comma-separated."
        )

        st.exception(exc)

    except Exception as exc:

        st.error(
            f"❌ An error occurred while processing the file: {exc}"
        )