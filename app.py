import base64
import io
import re
import urllib.parse
from datetime import datetime

import pandas as pd
import pytz
import requests
import streamlit as st


st.set_page_config(page_title="KP to Campeys SSCC Sender", layout="wide")
st.title("📦 KP to Campeys SSCC Sender")


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


def get_github_settings():
    token = st.secrets.get("github_token")
    username = st.secrets.get("github_username")
    repo = st.secrets.get("github_repo")

    if not token:
        raise ValueError("Missing github_token in Streamlit Secrets.")
    if not username:
        raise ValueError("Missing github_username in Streamlit Secrets.")
    if not repo:
        raise ValueError("Missing github_repo in Streamlit Secrets.")

    return (
        str(token).strip(),
        str(username).strip().strip("/"),
        str(repo).strip().strip("/"),
    )


def clean_filename(filename):
    filename = str(filename).strip()
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    filename = re.sub(r"\s+", " ", filename)

    if not filename:
        filename = "wms_output"

    if not filename.lower().endswith(".csv"):
        filename += ".csv"

    return filename


def is_summary_row(value):
    if pd.isna(value):
        return True

    value = str(value).strip().lower()

    if value == "":
        return True

    if "total" in value:
        return True

    if value in ("na", "n/a", "n-a", "n.a.", "n.a"):
        return True

    return False


def is_explicit_na(value):
    if pd.isna(value):
        return False

    value = str(value).strip().lower()
    cleaned = re.sub(r"[\s./\\#_-]+", "", value)

    return cleaned == "na"


def read_wms_data(text):
    if not text or not text.strip():
        raise ValueError("No WMS data was supplied.")

    text = text.strip()

    if "\t" in text:
        separator = "\t"
    else:
        separator = ","

    df = pd.read_csv(
        io.StringIO(text),
        sep=separator,
        dtype=str,
        keep_default_na=False,
    )

    df.columns = df.columns.astype(str).str.strip()

    return df


def upload_to_github(csv_bytes, filename):
    try:
        token, username, repo = get_github_settings()
    except ValueError as error:
        st.error("❌ GitHub configuration error:\n\n" + str(error))
        return False

    encoded_username = urllib.parse.quote(username, safe="")
    encoded_repo = urllib.parse.quote(repo, safe="")
    encoded_filename = urllib.parse.quote(filename, safe="")

    url = (
        "https://api.github.com/repos/"
        + encoded_username
        + "/"
        + encoded_repo
        + "/contents/saved_loads/"
        + encoded_filename
    )

    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    encoded_file = base64.b64encode(csv_bytes).decode("utf-8")

    try:
        check = requests.get(url, headers=headers, timeout=20)
    except requests.RequestException as error:
        st.error(
            "❌ Could not connect to GitHub.\n\n"
            + str(error)
        )
        return False

    payload = {
        "message": "Archive automated reformat entry: " + filename,
        "content": encoded_file,
    }

    if check.status_code == 200:
        try:
            existing = check.json()
        except ValueError:
            st.error(
                "❌ GitHub returned an invalid response when checking "
                "the existing file."
            )
            return False

        sha = existing.get("sha")

        if not sha:
            st.error(
                "❌ GitHub found the file but did not return its SHA."
            )
            return False

        payload["sha"] = sha

    elif check.status_code == 404:
        pass

    else:
        try:
            error_details = check.json()
        except ValueError:
            error_details = check.text

        st.error(
            "❌ GitHub rejected the archive check.\n\n"
            + "HTTP status: "
            + str(check.status_code)
            + "\n\nGitHub response:\n"
            + str(error_details)
        )
        return False

    try:
        response = requests.put(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.RequestException as error:
        st.error(
            "❌ Could not connect to GitHub while uploading the archive.\n\n"
            + str(error)
        )
        return False

    if response.status_code in (200, 201):
        st.success(
            "📂 Cloud Archive: "
            + filename
            + " successfully saved to GitHub."
        )
        return True

    try:
        error_details = response.json()
    except ValueError:
        error_details = response.text

    st.error(
        "❌ GitHub rejected the archive upload.\n\n"
        + "HTTP status: "
        + str(response.status_code)
        + "\n\nGitHub response:\n"
        + str(error_details)
    )

    return False


st.subheader("1. Additional Information")

col1, col2 = st.columns(2)

with col1:
    load_ref = st.text_input(
        "Enter Load Ref "
        "(Names your file and repeats in Load Ref column):"
    )

with col2:
    jde_order_ref = st.text_input(
        "Enter JDE Order Ref "
        "(Populates the Movement column):"
    )


st.subheader("2. Paste WMS Data Below")

st.caption(
    "Include your header row. Copy the entire grid from your WMS "
    "and paste it below."
)

pasted_text = st.text_area(
    "Paste data here:",
    height=250,
    placeholder=(
        "SSCC Code\tItem Code\tDescription\tUnits\t"
        "Rotation Date\tBatch\tStatus\tPositive Release\t"
        "Catch Weight To Remove"
    ),
)

process_button = st.button(
    "Process & Generate Files",
    type="primary",
)


if process_button:
    if not load_ref.strip():
       