#!/usr/bin/env python3
"""Split the KP to Campeys Streamlit app.py into maintainable modules.

Run from the repository root:
    python refactor_app.py

The script never needs internet access. It reads the app.py that is already
in the repository, backs it up, generates the modules, and runs validation.
"""
from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app.py"
BACKUP = ROOT / "app.py.before_refactor"

GROUPS = {
    "services.py": [
        "send_email_with_smtp",
        "get_github_settings",
        "get_github_connection",
        "get_github_file",
        "list_saved_load_files",
        "upload_github_file",
        "upload_to_github",
    ],
    "processing.py": [
        "clean_filename",
        "is_summary_row",
        "is_blank_or_na",
        "is_valid_data_value",
        "is_valid_wms_load_row",
        "read_wms_data",
        "update_sku_history",
        "extract_historic_csv_data",
        "normalise_history_date",
        "import_historic_csvs",
    ],
    "planner.py": [
        "planner_week_monday",
        "planner_date_string",
        "planner_display_date",
        "parse_planner_time",
        "cell_to_collection_count",
        "find_column",
        "parse_collection_request_workbook",
        "load_planner_data",
        "save_planner_data",
        "merge_imported_planner_slots",
        "get_archived_loads",
        "sync_planner_with_archived_loads",
        "planner_slot_status_text",
        "planner_slot_style",
        "create_planner_excel",
    ],
    "screens.py": [
        "show_planner",
        "find_saved_load_file_for_load_ref",
        "show_history",
        "show_import",
        "show_contacts",
        "show_sender",
        "show_home",
    ],
}

IMPORTS = """import base64
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
"""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_source() -> str:
    if not APP.exists():
        fail("app.py was not found. Run this script from your repository root.")
    return APP.read_text(encoding="utf-8")


def function_ranges(source: str):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    funcs = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno - 1
            end = node.end_lineno
            funcs[node.name] = "".join(lines[start:end]).rstrip()
    return funcs


def between(source: str, start_marker: str, end_marker: str) -> str:
    start = source.find(start_marker)
    if start < 0:
        fail(f"Could not find marker: {start_marker!r}")
    end = source.find(end_marker, start + len(start_marker))
    if end < 0:
        fail(f"Could not find marker: {end_marker!r}")
    return source[start:end].rstrip()


def session_init_block(source: str) -> str:
    # Locate the first session-state assignment and include the complete
    # initialization section up to the next major section.
    marker = 'if "page" not in st.session_state:'
    start = source.find(marker)
    if start < 0:
        fail("Could not locate Streamlit session-state initialization.")
    end_marker = "# ============================================================\n# GITHUB / EMAIL SERVICES"
    end = source.find(end_marker, start)
    if end < 0:
        fail("Could not locate the end of session-state initialization.")
    return source[start:end].rstrip()


def make_config(source: str) -> str:
    block = between(source, "# CONFIGURATION", "# PAGE CONFIG")
    return "# Application configuration constants.\n\n" + block.strip() + "\n"


def write(path: Path, content: str) -> None:
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    source = read_source()
    funcs = function_ranges(source)

    missing = [name for names in GROUPS.values() for name in names if name not in funcs]
    if missing:
        fail("Expected functions were not found: " + ", ".join(missing))

    # Safety backup. Do not overwrite an existing backup unless explicitly removed.
    if BACKUP.exists():
        print(f"Backup already exists: {BACKUP.name} (leaving it untouched)")
    else:
        shutil.copy2(APP, BACKUP)
        print(f"Created backup: {BACKUP.name}")

    write(ROOT / "config.py", make_config(source))

    state = f'''{IMPORTS}
from datetime import date, timedelta


def initialize_session_state():
    """Initialize Streamlit session state exactly as the original app did."""
    {session_init_block(source).replace(chr(10), chr(10) + "    ")}


{funcs["go_to"]}
'''
    write(ROOT / "state.py", state)

    services_body = "\n\n\n".join(funcs[n] for n in GROUPS["services.py"])
    write(ROOT / "services.py", f'''{IMPORTS}
from config import *

{services_body}
''')

    processing_body = "\n\n\n".join(funcs[n] for n in GROUPS["processing.py"])
    write(ROOT / "processing.py", f'''{IMPORTS}
from config import *
from services import *

{processing_body}
''')

    planner_body = "\n\n\n".join(funcs[n] for n in GROUPS["planner.py"])
    write(ROOT / "planner.py", f'''{IMPORTS}
from config import *
from services import *
from processing import *

{planner_body}
''')

    screens_body = "\n\n\n".join(funcs[n] for n in GROUPS["screens.py"])
    write(ROOT / "screens.py", f'''{IMPORTS}
from config import *
from state import *
from services import *
from processing import *
from planner import *

{screens_body}
''')

    # Keep the Streamlit page config and CSS in app.py, but move the state and
    # feature implementation into modules. This ordering is important because
    # Streamlit requires set_page_config() before other Streamlit commands.
    page_config = between(source, "st.set_page_config(", "# SESSION STATE")
    page_config = "st.set_page_config(" + page_config.split("st.set_page_config(", 1)[1]

    nav_marker = "# ============================================================\n# MAIN NAVIGATION"
    nav_start = source.find(nav_marker)
    if nav_start < 0:
        fail("Could not locate main navigation section.")
    navigation = source[nav_start:].rstrip()

    app = f'''import streamlit as st

{page_config.strip()}

from state import initialize_session_state
from screens import (
    show_home,
    show_sender,
    show_history,
    show_import,
    show_contacts,
    show_planner,
)

initialize_session_state()

{navigation}
'''
    write(APP, app)

    # Validate syntax for all generated Python files.
    generated = [ROOT / "app.py", ROOT / "config.py", ROOT / "state.py", ROOT / "services.py", ROOT / "processing.py", ROOT / "planner.py", ROOT / "screens.py"]
    print("Running syntax checks...")
    subprocess.run([sys.executable, "-m", "py_compile", *map(str, generated)], check=True)

    # Import non-entry modules. Importing app.py itself would execute the
    # Streamlit UI, so deliberately do not import it here.
    print("Running module import checks...")
    code = "import config, state, services, processing, planner, screens"
    subprocess.run([sys.executable, "-c", code], check=True)

    print("\nRefactor complete.")
    print("Generated:")
    for p in generated:
        print(f"  - {p.name}")
    print(f"Backup: {BACKUP.name}")
    print("\nRun your normal Streamlit command to test the app, e.g.: streamlit run app.py")


if __name__ == "__main__":
    main()
