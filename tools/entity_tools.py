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

# =============================================================================
# AUTONOMOUS TOOLS
# =============================================================================

@entity_tool(
    name="run_python",
    description="Executes Python for general-purpose autonomous tasks such as automation, calculation, data processing, filesystem operations, or data retrieval. Use this as the general-purpose execution tool when a specialized tool is unnecessary. Always operate on the smallest scope requested by the user. If the user names a specific folder, search only that folder. For counting or yes/no questions, return only the requested result rather than dumping unnecessary paths or data",
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