"""Acknowledged producer boundary and durable, single-writer local transport."""

import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Callable, Protocol

from .event_contract import Record
from .snapshot import encode


def publish(path: Path, value: object) -> None:
    """Publish one complete JSON object atomically on the same filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".stage-", delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(encode(value))
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


class Producer(Protocol):
    def send(self, sequence: int, record: Record) -> bool:
        """Return only after acknowledgement; False means exact local replay."""
        ...

    def flush(self) -> None: ...


class LocalProducer:
    def __init__(self, root: Path, env: str) -> None:
        if env not in {"dev", "test"}:
            raise ValueError("Local synthetic events require dev/test")
        self.root, self.env = root, env
        root.mkdir(parents=True, exist_ok=True)
        self.lock = (root / ".lock").open("a")
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise ValueError("Another event producer owns this directory") from None
        names = sorted(p.name for p in root.glob("*.json"))
        if names != [f"{i:012d}.json" for i in range(1, len(names) + 1)]:
            self.lock.close()
            raise ValueError("Local delivery history has a gap or unexpected filename")
        self.sequence = 0

    def send(self, sequence: int, record: Record) -> bool:
        record.validate(self.env)
        path = self.root / f"{sequence:012d}.json"
        value = {
            "sequence": sequence,
            "record": record.as_dict(),
            "environment": self.env,
        }
        if sequence != self.sequence + 1:
            raise ValueError("Delivery sequence must be contiguous")
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != value:
                raise ValueError("Replay differs from acknowledged delivery")
            self.sequence = sequence
            return False
        publish(path, value)
        self.sequence = sequence
        return True

    def flush(self) -> None:
        pass  # Every send fsyncs its record and containing directory.

    def close(self) -> None:
        self.lock.close()

    def __enter__(self) -> "LocalProducer":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class Acknowledgement(Protocol):
    def result(self, timeout: float) -> object: ...


class KafkaProducerAdapter:
    """Injected client binding: submit returns a future for broker acknowledgement.

    Client construction, TLS/auth and topic provisioning belong to later tickets.
    The caller translates this boundary to its chosen Kafka client's API.
    """

    def __init__(
        self,
        env: str,
        submit: Callable[[str, bytes, bytes, dict[str, bytes]], Acknowledgement],
        flush: Callable[[], None],
        timeout: float = 30.0,
    ) -> None:
        import math

        if not math.isfinite(timeout) or timeout <= 0 or env not in {"dev", "test"}:
            raise ValueError("Positive finite timeout and dev/test required")
        self.env, self.submit, self.flush_client, self.timeout = (
            env,
            submit,
            flush,
            timeout,
        )

    def send(self, sequence: int, record: Record) -> bool:
        event = record.validate(self.env)
        acknowledgement = self.submit(
            record.topic,
            record.key.encode("utf-8"),
            record.value.encode("utf-8"),
            {
                "event_id": event["event_id"].encode(),
                "event_version": b"1",
                "payload_version": b"1",
            },
        )
        acknowledgement.result(timeout=self.timeout)
        return True

    def flush(self) -> None:
        self.flush_client()
