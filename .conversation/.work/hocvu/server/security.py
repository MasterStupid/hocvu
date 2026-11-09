"""Bounded request throttling and explicit reverse-proxy trust."""
from __future__ import annotations

from collections import OrderedDict, deque
import ipaddress
import math
import threading
import time


def parse_trusted_proxies(value: str) -> tuple:
    networks = []
    for raw in value.split(","):
        if not raw.strip():
            continue
        try:
            network = ipaddress.ip_network(raw.strip(), strict=False)
            if network.prefixlen == 0:
                raise ValueError("Do not trust the entire Internet")
        except ValueError as exc:
            raise RuntimeError("HV_TRUSTED_PROXIES phải chứa IP/CIDR proxy cụ thể, không dùng wildcard.") from exc
        networks.append(network)
    return tuple(networks)


def client_address(request, trusted_proxies: tuple) -> str:
    """Walk XFF from the transport peer backwards; never trust a client header."""
    try:
        peer = ipaddress.ip_address(request.client.host)
    except (AttributeError, ValueError):
        return "unknown"

    def trusted(address):
        return any(address.version == network.version and address in network
                   for network in trusted_proxies)

    if not trusted(peer):
        return str(peer)
    forwarded = ",".join(request.headers.getlist("x-forwarded-for"))
    parts = forwarded.split(",") if forwarded else []
    if not parts or len(parts) > 32 or len(forwarded) > 4096:
        return str(peer)
    try:
        chain = [ipaddress.ip_address(part.strip()) for part in parts] + [peer]
    except ValueError:
        return str(peer)
    while len(chain) > 1 and trusted(chain[-1]):
        chain.pop()
    return str(chain[-1])


class SlidingWindowLimiter:
    """Per-process, thread-safe, bounded sliding windows; never evict active keys."""

    def __init__(self, max_clients: int = 10000, window: float = 60):
        if max_clients < 1 or window <= 0:
            raise ValueError("Positive limiter capacity and window required")
        self.max_clients = max_clients
        self.window = window
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def consume(self, key: str, limit: int, *, now: float | None = None) -> int:
        """Return zero if allowed, otherwise Retry-After seconds."""
        if limit < 1:
            raise ValueError("Positive request limit required")
        now = time.monotonic() if now is None else now
        cutoff = now - self.window
        with self._lock:
            # Entries are ordered by their last accepted timestamp, not by
            # denied attempts. Reclaim expired clients on every request.
            while self._buckets:
                oldest = next(iter(self._buckets))
                if self._buckets[oldest][-1] > cutoff:
                    break
                self._buckets.popitem(last=False)
            recent = self._buckets.get(key)
            if recent is None:
                if len(self._buckets) >= self.max_clients:
                    oldest = next(iter(self._buckets.values()))
                    return max(1, math.ceil(oldest[-1] + self.window - now))
                recent = self._buckets[key] = deque()
            while recent and recent[0] <= cutoff:
                recent.popleft()
            if len(recent) >= limit:
                return max(1, math.ceil(recent[0] + self.window - now))
            recent.append(now)
            self._buckets.move_to_end(key)
            return 0
