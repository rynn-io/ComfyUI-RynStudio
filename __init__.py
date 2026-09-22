"""ComfyUI-RynStudio — Ryn H3 Director integration.

The R2V execution path is adapted from AIMixer/ComfyUI_MiniMaxH3_Director,
commit 576424fb252b2b4a538e792027f7db1a5ef376e4, under Apache-2.0.
This distribution contains modifications by Ryn Studio. See NOTICE and LICENSE.
"""

from .nodes.ryn_director import RynH3Director

NODE_CLASS_MAPPINGS = {"RynH3Director": RynH3Director}
NODE_DISPLAY_NAME_MAPPINGS = {"RynH3Director": "Ryn H3 Director"}
WEB_DIRECTORY = "./web/js"

import logging

_log = logging.getLogger("ComfyUI-RynStudio")

try:
    from .director.http_routes import register_routes as _register_director_routes

    if not _register_director_routes():
        _log.warning("Ryn H3 Director HTTP routes deferred; restart ComfyUI if media upload routes return 404.")
except Exception as _routes_exc:
    _log.warning("Ryn H3 Director HTTP routes failed to load: %s", _routes_exc)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
