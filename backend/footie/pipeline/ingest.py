"""Stage 1, Ingest: take in match events and tracking frames as they happen.

`MatchFeed` replays a simulated match against a moving clock, so downstream
stages only ever see data up to "now", exactly as with a live provider feed.
Swap this class for a real provider adapter and nothing downstream changes.

If FABRIC_EVENTSTREAM_CONNECTION_STRING is set, every ingested event is also
forwarded to a Microsoft Fabric Eventstream (custom endpoint, Event Hubs
protocol) so it lands in an Eventhouse for live KQL queries.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading

from ..sim.simulator import SimulatedMatch

log = logging.getLogger(__name__)


class MatchFeed:
    def __init__(self, match: SimulatedMatch, sink: "FabricEventstreamSink | None" = None):
        self.match = match
        self.tracking = match.tracking
        self.sink = sink
        self._ei = 0  # next event index
        self._fi = 0  # next frame index
        self.t = 0.0

    def advance_to(self, t: float) -> tuple[list[dict], list[dict]]:
        """Everything that happened in (previous t, t]: events and tracking frames."""
        t = min(t, self.match.duration)
        events: list[dict] = []
        evs = self.match.events
        while self._ei < len(evs) and evs[self._ei]["t"] <= t:
            events.append(evs[self._ei])
            self._ei += 1
        frames: list[dict] = []
        if self.tracking is not None:
            last = self.tracking.index(t)
            while self._fi <= last:
                frames.append(self.tracking.frame(self._fi))
                self._fi += 1
        self.t = t
        if self.sink and events:
            self.sink.send(events)
        return events, frames

    def frame_at(self, t: float) -> dict | None:
        if self.tracking is None:
            return None
        return self.tracking.frame(self.tracking.index(t))

    @property
    def finished(self) -> bool:
        return self._ei >= len(self.match.events)


class FabricEventstreamSink:
    """Non-blocking forwarder to a Fabric Eventstream custom endpoint."""

    def __init__(self, connection_string: str, eventhub_name: str | None = None):
        from azure.eventhub import EventData, EventHubProducerClient  # optional dependency

        self._EventData = EventData
        kwargs = {"eventhub_name": eventhub_name} if eventhub_name else {}
        self._client = EventHubProducerClient.from_connection_string(connection_string, **kwargs)
        self._q: queue.Queue[list[dict]] = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    @classmethod
    def from_env(cls) -> "FabricEventstreamSink | None":
        cs = os.getenv("FABRIC_EVENTSTREAM_CONNECTION_STRING")
        if not cs:
            return None
        try:
            return cls(cs, os.getenv("FABRIC_EVENTSTREAM_NAME"))
        except Exception as exc:  # missing package or bad connection string
            log.warning("Fabric sink disabled: %s", exc)
            return None

    def send(self, events: list[dict]) -> None:
        self._q.put(events)

    def _worker(self) -> None:
        while True:
            events = self._q.get()
            try:
                batch = self._client.create_batch()
                for e in events:
                    batch.add(self._EventData(json.dumps(e)))
                self._client.send_batch(batch)
            except Exception as exc:
                log.warning("Fabric send failed: %s", exc)
