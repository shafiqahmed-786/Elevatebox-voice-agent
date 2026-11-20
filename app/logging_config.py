"""
Logging setup. Every business-logic log line in this codebase includes
`call_id=...` as its first structured field (see the log calls throughout
app/services, app/scheduler, app/whatsapp, app/telephony) specifically so
"debug from a single call ID" is something you can actually do:

    grep 'call=abc123' app.log

None of these modules ever log a token, API key, or the full WhatsApp
Authorization header -- errors log Meta's/OmniDimension's error message
field only, never request headers.
"""

from __future__ import annotations

import logging
import sys

from app.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger("elevatebox")
    root.setLevel(settings.log_level)
    root.handlers = [handler]
    root.propagate = False
