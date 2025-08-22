#!/usr/bin/env python3
"""
Shim module to preserve backward compatibility after restructuring the project
into a proper package (src/three_d_resume). The actual implementation now
lives in three_d_resume.server. This shim re-exports the public API used by
existing tests and provides the same console entry point.
"""
# Import the real implementation; support running from source without install (src layout)
try:
    from three_d_resume.server import (  # type: ignore F401
        DevHandler,
        ensure_page_exists,
        find_free_port,
        main as _main,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback for local runs
    import os
    import sys as _sys
    here = os.path.dirname(__file__)
    src = os.path.join(here, "src")
    if os.path.isdir(src) and src not in _sys.path:
        _sys.path.insert(0, src)
    from three_d_resume.server import (  # type: ignore F401
        DevHandler,
        ensure_page_exists,
        find_free_port,
        main as _main,
    )

# Re-export symbols for tests that import `main`
__all__ = [
    "DevHandler",
    "ensure_page_exists",
    "find_free_port",
    "main",
]


def main():
    return _main()


if __name__ == "__main__":
    main()