import base64
import ipaddress
import struct
from dataclasses import dataclass
from typing import ClassVar, Mapping


@dataclass(frozen=True)
class TelegramSessionEncoder:
    """
    Encodes a Telegram session using a given auth_key and data center ID (dc_id).
    Produces a base64-encoded string suitable for use with Telegram clients.
    """
    auth_key: bytes
    dc_id: int

    _VERSION: ClassVar[str] = "1"
    _PORT: ClassVar[int] = 443
    _DC_IP_MAP: ClassVar[Mapping[int, str]] = {
        1: "149.154.175.53",
        2: "149.154.167.51",
        3: "149.154.175.100",
        4: "149.154.167.91",
        5: "91.108.56.130"
    }

    def to_string(self) -> str:
        """
        Converts the session to a base64-encoded string.
        Format: <VERSION><base64(dc_id | ip | port | auth_key)>
        """
        ip_bytes = self._resolve_ip()
        payload = self._build_payload(ip_bytes)
        encoded = base64.urlsafe_b64encode(payload).decode("ascii")
        return f"{self._VERSION}{encoded}"

    def _resolve_ip(self) -> bytes:
        """
        Resolves the IP address for the given DC ID.
        Returns packed IP in bytes.
        """
        ip = self._DC_IP_MAP.get(self.dc_id)
        if not ip:
            raise ValueError(f"Unknown data center ID: {self.dc_id}")
        return ipaddress.ip_address(ip).packed

    def _build_payload(self, ip_bytes: bytes) -> bytes:
        """
        Builds the binary payload to be encoded.
        Structure: <dc_id:1B><ip:N><port:2B><auth_key:256B>
        """
        if len(self.auth_key) != 256:
            raise ValueError("auth_key must be exactly 256 bytes")
        fmt = f">B{len(ip_bytes)}sH256s"
        return struct.pack(fmt, self.dc_id, ip_bytes, self._PORT, self.auth_key)