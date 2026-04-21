from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("cs.observability")


async def send_to_sink(span_name: str, payload: dict[str, Any]) -> None:
    """Simulated observability sink. Replace with Datadog / Honeycomb / etc."""
    logger.info("obs.%s %s", span_name, json.dumps(payload, default=str))
