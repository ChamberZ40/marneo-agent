# marneo/tools/loader.py
"""Import all tool modules to trigger self-registration in the registry."""


def load_all_tools() -> None:
    """Import every tool module. Call once at startup."""
    from marneo.tools.core import files     # noqa: F401
    from marneo.tools.core import bash      # noqa: F401
    from marneo.tools.core import web       # noqa: F401
    from marneo.tools.core import lark_cli  # noqa: F401
