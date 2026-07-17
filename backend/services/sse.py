"""Server-Sent Events progress broker.

Single-local-user simplification (deliberate, see plan): one queue + ring buffer
per run_id, no pub-sub fan-out. A reconnecting client replays the buffer then
tails the live queue. If two tabs watch the same run_id concurrently they race
for queue items — acceptable for a single-user local tool.
"""
import asyncio
import json
import queue
import re
import threading
import uuid
from collections import deque
from typing import AsyncGenerator

_RICH_TAG_RE = re.compile(r"\[/?[a-zA-Z0-9_ ]*\]")


def strip_rich_markup(text: str) -> str:
    """Strip Rich console markup (e.g. '[green]OK[/green]') for plain-text display in the browser."""
    return _RICH_TAG_RE.sub("", text).strip()


class ProgressBroker:
    def __init__(self, buffer_size: int = 200):
        self._queues: dict[str, "queue.Queue"] = {}
        self._buffers: dict[str, deque] = {}
        self._done: dict[str, bool] = {}
        self._seq: dict[str, int] = {}
        self._lock = threading.Lock()
        self.buffer_size = buffer_size

    def new_run(self) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._queues[run_id] = queue.Queue()
            self._buffers[run_id] = deque(maxlen=self.buffer_size)
            self._done[run_id] = False
            self._seq[run_id] = 0
        return run_id

    def _stamp(self, run_id: str, event: dict) -> dict:
        """Every event gets a monotonic sequence number so a client that
        connects mid-run can replay the buffer and then skip past those same
        events when it reaches them again in the live queue, instead of
        double-delivering everything published before it attached."""
        seq = self._seq[run_id]
        self._seq[run_id] = seq + 1
        return {**event, "_seq": seq}

    def publish(self, run_id: str, event: dict):
        with self._lock:
            if run_id not in self._queues:
                return
            stamped = self._stamp(run_id, event)
            self._buffers[run_id].append(stamped)
            self._queues[run_id].put(stamped)

    def finish(self, run_id: str, final_event: dict):
        with self._lock:
            if run_id not in self._queues:
                return
            stamped = self._stamp(run_id, final_event)
            self._buffers[run_id].append(stamped)
            self._queues[run_id].put(stamped)
            self._done[run_id] = True
            self._queues[run_id].put(None)  # sentinel

    async def stream(self, run_id: str, last_event_id: int = -1) -> AsyncGenerator[str, None]:
        """`last_event_id`, when the browser reconnects after a dropped connection,
        is the SSE `id:` of the last event it actually received (sent back via the
        `Last-Event-ID` header) — skip re-replaying anything up to and including
        it, so a reconnect resumes the log instead of duplicating it."""
        with self._lock:
            if run_id not in self._queues:
                yield _format({"type": "error", "message": "unknown run_id"})
                return
            buffered = list(self._buffers[run_id])
            q = self._queues[run_id]
            already_done = self._done[run_id]

        last_seq = last_event_id
        for event in buffered:
            if event["_seq"] <= last_seq:
                continue
            yield _format(event)
            last_seq = event["_seq"]
        if already_done:
            return

        while True:
            event = await asyncio.to_thread(q.get)
            if event is None:
                return
            if event["_seq"] <= last_seq:
                continue  # already delivered via the buffer replay above
            yield _format(event)


def parse_last_event_id(header_value: str | None) -> int:
    """Parses the browser's `Last-Event-ID` reconnect header; -1 (replay everything)
    if absent or malformed."""
    try:
        return int(header_value) if header_value is not None else -1
    except ValueError:
        return -1


def _format(event: dict) -> str:
    clean = {k: v for k, v in event.items() if k != "_seq"}
    return f"id: {event['_seq']}\ndata: {json.dumps(clean)}\n\n"


broker = ProgressBroker()
