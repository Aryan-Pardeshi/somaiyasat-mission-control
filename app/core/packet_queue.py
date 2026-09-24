"""Small bounded packet queue guarded for concurrent workers."""
from __future__ import annotations
from collections import Counter
import threading
from app import config
from app.models.enums import PacketPriority, PacketStatus
from app.models.packet import DataPacket

class PacketQueue:
    """Stores packets until sent, failed, or evicted."""
    def __init__(self, max_size: int = config.MAX_QUEUE_SIZE):
        self.max_size = max_size
        self._packets: list[DataPacket] = []
        self._lock = threading.RLock()
    def add(self, packet: DataPacket) -> DataPacket | None:
        """Add a packet; evict the oldest lowest-priority noncritical item if full."""
        with self._lock:
            if len(self._packets) < self.max_size:
                self._packets.append(packet)
                return None
            ranking = {PacketPriority.LOW: 0, PacketPriority.MEDIUM: 1, PacketPriority.HIGH: 2, PacketPriority.CRITICAL: 3}
            candidates = [p for p in self._packets if p.priority is not PacketPriority.CRITICAL]
            if packet.priority is not PacketPriority.CRITICAL:
                candidates.append(packet)
            if not candidates:
                packet.status = PacketStatus.DROPPED
                return packet
            evicted = min(candidates, key=lambda p: (ranking[p.priority], p.created_at))
            evicted.status = PacketStatus.DROPPED
            if evicted is not packet:
                self._packets.remove(evicted)
                self._packets.append(packet)
            return evicted
    def remove(self, packet_id: int) -> DataPacket | None:
        """Remove a packet by ID."""
        with self._lock:
            packet = self.get(packet_id)
            if packet:
                self._packets.remove(packet)
            return packet
    def get(self, packet_id: int) -> DataPacket | None:
        """Find a packet by ID."""
        with self._lock:
            return next((p for p in self._packets if p.packet_id == packet_id), None)
    def snapshot(self) -> list[DataPacket]:
        """Return a shallow copy for one router cycle."""
        with self._lock:
            return list(self._packets)
    def eligible(self, predicate) -> list[DataPacket]:
        """Filter available packets using the caller's eligibility rule."""
        return list(filter(predicate, self.snapshot()))
    def counts_by_type(self) -> dict[str, int]:
        """Count queued packets by type value."""
        return dict(Counter(p.packet_type.value for p in self.snapshot()))
    def clear(self) -> None:
        """Remove all packets."""
        with self._lock:
            self._packets.clear()
    def __len__(self) -> int:
        with self._lock:
            return len(self._packets)
    def __iter__(self):
        return iter(self.snapshot())
