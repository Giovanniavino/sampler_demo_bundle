"""
Wire protocol for the virtual device link.

Messages are JSON objects, each framed by a 4-byte big-endian length prefix so
arbitrarily large payloads (a whole kit's audio, base64-encoded) survive being
split across TCP segments. Used by both the virtual device and the client.
"""

from __future__ import annotations

import json
import socket
import struct

_HEADER = struct.Struct(">I")
MAX_MESSAGE = 256 * 1024 * 1024          # 256 MB hard cap, guards against junk


class ProtocolError(Exception):
    """Raised on framing errors or an unexpectedly closed connection."""


def send_message(sock: socket.socket, obj: dict) -> None:
    """Serialize obj to JSON and send it as one length-prefixed frame."""
    payload = json.dumps(obj).encode("utf-8")
    sock.sendall(_HEADER.pack(len(payload)) + payload)


def recv_message(sock: socket.socket) -> dict:
    """Read exactly one length-prefixed JSON frame and return the object."""
    (length,) = _HEADER.unpack(_recv_exact(sock, _HEADER.size))
    if length > MAX_MESSAGE:
        raise ProtocolError(f"message too large: {length} bytes")
    return json.loads(_recv_exact(sock, length).decode("utf-8"))


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Receive exactly n bytes or raise ProtocolError."""
    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(min(remaining, 65536))
        if not chunk:
            raise ProtocolError("connection closed mid-message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
