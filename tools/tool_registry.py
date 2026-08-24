# tools/tool_registry.py

from typing import Callable, Dict, Any

# =============================================================================
# ENTITY TOOL REGISTRY
#
# Single source of truth for all tool definitions.
#
# Future architecture:
#
# Planner
#    ↓
# Executor
#    ↓
# Tool Registry
#    ↓
# Actual Tool Function
#
# =============================================================================

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}


# =============================================================================
# REGISTRATION
# =============================================================================

def register_tool(
    name: str,
    function: Callable,
    description: str = "",
    category: str = "general"
):
    """
    Registers a tool with Entity.

    Example:

        register_tool(
            name="open_app",
            function=open_app,
            description="Open desktop applications",
            category="system"
        )
    """

    TOOL_REGISTRY[name] = {
        "function": function,
        "description": description,
        "category": category,
    }


def entity_tool(
    name: str,
    description: str = "",
    category: str = "general"
):
    """
    Decorator for automatic tool registration.

    Example:

        @entity_tool(
            name="open_app",
            description="Open desktop applications",
            category="system"
        )
        def open_app(...):
            ...
    """

    def decorator(func):

        register_tool(
            name=name,
            function=func,
            description=description,
            category=category
        )

        func.tool_name = name
        func.tool_description = description
        func.tool_category = category

        return func

    return decorator


# =============================================================================
# LOOKUPS
# =============================================================================

def get_tool(name: str):
    """
    Returns the full tool metadata dictionary.
    """
    return TOOL_REGISTRY.get(name)


def get_tool_function(name: str):
    """
    Returns only the callable function.
    """
    tool = TOOL_REGISTRY.get(name)

    if not tool:
        return None

    return tool["function"]


def list_tools():
    """
    Returns all registered tools.
    """
    return TOOL_REGISTRY


def list_tool_descriptions():
    """
    Returns planner-friendly tool descriptions.
    """

    output = []

    for name, info in TOOL_REGISTRY.items():

        output.append({
            "name": name,
            "description": info.get("description", ""),
            "category": info.get("category", "general")
        })

    return output


# =============================================================================
# EXECUTION
# =============================================================================

def execute_tool(name: str, **kwargs):
    """
    Executes a registered tool directly.

    Example:

        execute_tool(
            "open_app",
            app_name="chrome"
        )
    """

    tool = TOOL_REGISTRY.get(name)

    if not tool:
        raise ValueError(f"Tool not found: {name}")

    func = tool["function"]

    return func(kwargs)


# =============================================================================
# DEBUGGING
# =============================================================================

def print_registry():
    """
    Prints all registered tools.
    """

    print("\n=== ENTITY TOOL REGISTRY ===")

    for name, info in TOOL_REGISTRY.items():

        print(
            f"{name} "
            f"[{info.get('category', 'general')}] "
            f"- {info.get('description', '')}"
        )

    print("============================\n")