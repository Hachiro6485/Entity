import getpass
import threading

import config


# =============================================================================
# DESTRUCTIVE ACTION AUTHORIZATION
# =============================================================================
#
# This module is the security gate for actions such as deleting files.
#
# The important rule:
#
#     The AI never receives the PIN.
#
# The AI only asks Entity to perform a protected action.
# Normal Python code handles the authorization.
#
# CLI:
#     asks in the terminal
#
# GUI:
#     asks through the CyberHUD dialog
# =============================================================================


_gui_authorizer = None
_gui_authorizer_lock = threading.Lock()


def set_gui_authorizer(callback):
    """
    Registers the GUI callback used for protected operations.

    callback(action_name: str, details: str) -> bool
    """

    global _gui_authorizer

    with _gui_authorizer_lock:
        _gui_authorizer = callback


def _get_pin():
    """
    Reads the configured Entity PIN.

    The PIN comes from .env through config.py.
    """

    return getattr(
        config,
        "ENTITY_PIN",
        None
    )


def authorize_destructive_action(
    action_name: str,
    details: str
) -> bool:
    """
    Requests authorization for a destructive action.

    Returns:
        True  -> authorized
        False -> rejected
    """

    pin = _get_pin()

    # No PIN means destructive actions are disabled.
    if not pin:

        print(
            "\n[SECURITY] Destructive action refused:"
            " ENTITY_PIN is not configured."
        )

        return False


    # ================================================================
    # GUI PATH
    # ================================================================

    with _gui_authorizer_lock:
        gui_callback = _gui_authorizer

    if gui_callback is not None:

        try:

            return bool(
                gui_callback(
                    action_name,
                    details
                )
            )

        except Exception as e:

            print(
                f"[SECURITY] GUI authorization failed: {e}"
            )

            return False


    # ================================================================
    # CLI PATH
    # ================================================================

    print()
    print("=" * 60)
    print("ENTITY SECURITY ALERT")
    print("=" * 60)
    print(
        f"Protected action: {action_name}"
    )
    print()
    print(
        f"Target: {details}"
    )
    print()
    print(
        "This action may permanently change or destroy data."
    )
    print("=" * 60)

    confirmation = input(
        "Type YES to authorize this action: "
    ).strip()

    if confirmation != "YES":

        print(
            "[SECURITY] Action cancelled."
        )

        return False


    entered_pin = getpass.getpass(
        "Enter Entity PIN: "
    ).strip()

    if entered_pin != pin:

        print(
            "[SECURITY] Incorrect PIN. Action cancelled."
        )

        return False


    print(
        "[SECURITY] Authorization accepted."
    )

    return True