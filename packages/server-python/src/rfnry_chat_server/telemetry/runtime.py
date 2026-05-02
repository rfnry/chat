from __future__ import annotations

import contextlib

from pydantic import BaseModel

from rfnry_chat_server.telemetry.record import TelemetryRow
from rfnry_chat_server.telemetry.sink import NullTelemetrySink, TelemetrySink


class Telemetry(BaseModel):
    sink: TelemetrySink = NullTelemetrySink()

    model_config = {"arbitrary_types_allowed": True}

    async def write(self, row: TelemetryRow) -> None:
        with contextlib.suppress(Exception):
            await self.sink.write(row)
