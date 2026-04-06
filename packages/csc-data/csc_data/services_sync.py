"""Services sync: sequence counter, replay buffer, pending queue, gap detection.

Each server keeps one monotonic outbound sequence counter.  Every SERVICESUPDATE
carries (origin_server_id, seq) so receivers can detect gaps independently of
which intermediate hop forwarded the message.

Replay buffer holds the last REPLAY_BUFFER_SIZE outbound messages keyed by
(origin, seq).  On SYNCREQUEST a peer can retrieve missed updates; if the buffer
does not go back far enough a full SYNCSERVICES is sent instead.
"""

import json
import os
import time
from collections import deque

REPLAY_BUFFER_SIZE = 500


class ServicesSyncManager:
    """Tracks services sync state per server instance."""

    def __init__(self, base_path):
        self.base_path = base_path
        self._seq_path = os.path.join(base_path, "services_seq.json")
        self._pending_path = os.path.join(base_path, "services_pending.json")
        self._seq = self._load_seq()
        # replay buffer entries: (origin_id, seq, args_str)
        self._replay_buffer = deque(maxlen=REPLAY_BUFFER_SIZE)
        # last inbound seq received per origin server
        self._peer_last_seq = {}  # {origin_id: last_seq}

    # ------------------------------------------------------------------
    # Outbound sequence
    # ------------------------------------------------------------------

    def _load_seq(self):
        try:
            with open(self._seq_path, "r", encoding="utf-8") as f:
                return json.load(f).get("seq", 0)
        except (OSError, json.JSONDecodeError):
            return 0

    def _save_seq(self):
        tmp = self._seq_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"seq": self._seq}, f)
        os.replace(tmp, self._seq_path)

    def next_seq(self):
        """Increment and return the next outbound sequence number."""
        self._seq += 1
        self._save_seq()
        return self._seq

    def current_seq(self):
        return self._seq

    def record_outbound(self, origin_id, seq, args_str):
        """Store an outbound (or re-broadcast) update in the replay buffer."""
        self._replay_buffer.append((origin_id, seq, args_str))

    def get_replay_since(self, origin_id, last_seq):
        """Return list of args_str for origin_id with seq > last_seq.

        Returns None if the buffer does not go back far enough (full sync needed).
        """
        matching = [(s, a) for o, s, a in self._replay_buffer
                    if o == origin_id and s > last_seq]
        if not matching:
            # Check whether we ever had entries for this origin
            oldest = next(((s) for o, s, a in self._replay_buffer
                           if o == origin_id), None)
            if oldest is None or oldest > last_seq + 1:
                # Nothing in buffer for this origin — caller should do full sync
                return None
        return [a for _, a in sorted(matching, key=lambda x: x[0])]

    # ------------------------------------------------------------------
    # Inbound gap detection
    # ------------------------------------------------------------------

    def check_inbound_seq(self, origin_id, seq):
        """Check an inbound sequence number from origin_id.

        Returns (gap_start, gap_end) if one or more messages were missed,
        None if in-order or duplicate.
        """
        last = self._peer_last_seq.get(origin_id, 0)
        if last == 0 or seq == last + 1:
            self._peer_last_seq[origin_id] = max(last, seq)
            return None
        if seq > last + 1:
            gap = (last + 1, seq - 1)
            self._peer_last_seq[origin_id] = seq
            return gap
        # Duplicate or out-of-order: ignore
        return None

    def reset_peer_seq(self, origin_id, seq):
        """Reset sequence tracking after a full sync from origin_id."""
        self._peer_last_seq[origin_id] = seq

    # ------------------------------------------------------------------
    # Pending queue (changes made while no peers are connected)
    # ------------------------------------------------------------------

    def _load_pending(self):
        try:
            with open(self._pending_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "pending": []}

    def _save_pending(self, data):
        tmp = self._pending_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self._pending_path)

    def record_local_update(self, stype, key, action, record):
        """Queue a change made while no peers were connected."""
        data = self._load_pending()
        # Keep only the latest entry per type+key
        data["pending"] = [
            e for e in data["pending"]
            if not (e["type"] == stype and e["key"] == key)
        ]
        data["pending"].append({
            "type": stype,
            "key": key,
            "timestamp": record.get("updated_at", time.time()) if record else time.time(),
            "action": action,
            "record": record,
        })
        self._save_pending(data)

    def get_pending(self):
        return self._load_pending().get("pending", [])

    def clear_all_pending(self):
        self._save_pending({"version": 1, "pending": []})
