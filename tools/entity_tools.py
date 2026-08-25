from tools.tool_registry import entity_tool
from tools.system_control import (
    open_app,
    type_text,
    media_control
)
from tools.web_tools import search, open_website
from tools.basic_tools import delete_file

import os
import shutil
import json


# =============================================================================
# SYSTEM TOOLS
# =============================================================================

@entity_tool(
    name="open_app",
    description="Opens local applications.",
    category="system"
)
def tool_open_app(args):
    return open_app(args.get("app_name", ""))


@entity_tool(
    name="type_text",
    description="Types text into the active window.",
    category="system"
)
def tool_type_text(args):
    return type_text(args.get("text", ""))


@entity_tool(
    name="media_control",
    description="Controls system media and volume.",
    category="system"
)
def tool_media_control(args):
    return media_control(args.get("command", ""))


# =============================================================================
# WEB TOOLS
# =============================================================================

@entity_tool(
    name="search_web",
    description="Searches Google or YouTube.",
    category="web"
)
def tool_search_web(args):
    return search(args.get("query", ""))

@entity_tool(
    name="open_website",
    description="Opens a website directly in the user's default browser.",
    category="web"
)
def tool_open_website(args):
    return open_website(args.get("url", ""))

# =============================================================================
# FILE SYSTEM TOOLS
# =============================================================================

@entity_tool(
    name="delete_file",
    description=(
        "Permanently deletes one specific file. "
        "This action requires explicit human confirmation and the Entity PIN."
    ),
    category="filesystem"
)
def tool_delete_file(args):

    path = args.get(
        "path",
        ""
    )

    return delete_file(path)

@entity_tool(
    name="create_folder",
    description="Creates a directory on the local machine.",
    category="filesystem"
)
def tool_create_folder(args):

    path = os.path.expandvars(args.get("path", ""))

    if not path:
        raise ValueError("create_folder requires a path.")

    os.makedirs(path, exist_ok=True)

    return f"Folder created: {path}"


@entity_tool(
    name="find_files",
    description="Recursively finds files matching an extension.",
    category="filesystem"
)
def tool_find_files(args):

    extension = args.get("extension", "")
    directory = os.path.expandvars(args.get("directory", ""))

    if not extension:
        raise ValueError("find_files requires extension.")

    if not directory:
        raise ValueError("find_files requires directory.")

    if not extension.startswith("."):
        extension = "." + extension

    matches = []

    for root, _, files in os.walk(directory):
        for file in files:

            if file.lower().endswith(extension.lower()):
                matches.append(
                    os.path.join(root, file)
                )

    return json.dumps(matches)


@entity_tool(
    name="move_files",
    description="Moves files into another directory.",
    category="filesystem"
)
def tool_move_files(args):

    raw_sources = args.get("source_paths", "")
    destination = os.path.expandvars(
        args.get("destination", "")
    )

    if not destination:
        raise ValueError("move_files requires destination.")

    os.makedirs(destination, exist_ok=True)

    try:
        parsed = json.loads(str(raw_sources))

        if isinstance(parsed, list):
            paths = parsed
        else:
            paths = [str(raw_sources)]

    except Exception:
        paths = [str(raw_sources)]

    moved = []

    for src in paths:

        if not src:
            continue

        filename = os.path.basename(src)

        shutil.move(
            src,
            os.path.join(destination, filename)
        )

        moved.append(filename)

    return (
        f"Moved {len(moved)} file(s) "
        f"to {destination}"
    )


@entity_tool(
    name="list_files",
    description="Lists files in a directory.",
    category="filesystem"
)
def tool_list_files(args):

    directory = os.path.expandvars(
        args.get("directory", "")
    )

    files = [
        f for f in os.listdir(directory)
        if os.path.isfile(
            os.path.join(directory, f)
        )
    ]

    return json.dumps(files)


# =============================================================================
# AUTONOMOUS TOOLS
# =============================================================================

@entity_tool(
    name="run_python",
    description="Executes Python code when no dedicated tool exists.",
    category="autonomous"
)
def tool_run_python(args):

    from coder import execute_python

    code = args.get("code", "")

    return execute_python(code)


@entity_tool(
    name="analyze_screen",
    description="Analyzes the current screen using the vision system.",
    category="vision"
)
def tool_analyze_screen(args):

    from core import brain

    question = args.get("question", "")

    return brain.get_vision_analysis(question)


# =============================================================================
# RESPONSE TOOL
# =============================================================================

@entity_tool(
    name="chat",
    description="Returns a response directly to the user.",
    category="response"
)
def tool_chat(args):
    return args.get(
        "response",
        "Task completed."
    )