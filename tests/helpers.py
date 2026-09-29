"""Shared test utilities: frame building and fake Blue Connect BLE client."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

MAC = "AA:BB:CC:DD:EE:FF"
ACCESS_CODE = "AB12CD34E"  # 9 alphanumeric characters

# UUIDs of the characteristics read after the measurement (values from coordinator.py).
UUID_RAW_SENSORS = "70ea0005-7a29-4fdf-93d2-838665e72677"
UUID_ACCELEROMETER = "70ea000a-7a29-4fdf-93d2-838665e72677"
UUID_SERIAL_NUMBER = "70ea0020-7a29-4fdf-93d2-838665e72677"
UUID_HW_VERSION = "70ea0021-7a29-4fdf-93d2-838665e72677"
UUID_SW_VERSION = "70ea0022-7a29-4fdf-93d2-838665e72677"


def build_frame(
    temp_c: float = 25.02,
    ph: float = 7.4,
    orp_mv: int = 700,
    conductivity: int | None = 1200,
    salinity: float = 3.5,
    battery_pct: int = 80,
    battery_adc: int = 4000,
    echo: bool = False,
    prefixed: bool = False,
) -> bytes:
    """18-byte frame (19 with `prefixed`, one extra header byte).

    Fields decoded by protocol.parse_raw_frame, all big-endian:
    temperature x100, pH x10, ORP, conductivity (0xFFFF = probe absent),
    salinity x100, battery %, battery ADC. `echo` sets the "B" marker that
    passive mode recognizes as an echo.
    """
    cond = 0xFFFF if conductivity is None else conductivity
    body = bytearray(3)  # 3-byte header
    body += round(temp_c * 100).to_bytes(2, "big")
    body += round(ph * 10).to_bytes(2, "big")
    body += int(orp_mv).to_bytes(2, "big")
    body += int(cond).to_bytes(2, "big")
    body += round(salinity * 100).to_bytes(2, "big")
    body += bytes([battery_pct])
    body += int(battery_adc).to_bytes(2, "big")
    body += bytes([0xB0 if echo else 0x00, 0x00])  # 2 trailing bytes
    assert len(body) == 18
    return (b"\xaa" + bytes(body)) if prefixed else bytes(body)


def clean_hex(frame: bytes) -> str:
    """Frame as stored (without the header byte of 19-byte frames)."""
    return (frame[1:] if len(frame) == 19 else frame).hex().upper()


class FakeBlueClient:
    """Replaces BleakClient: authentication, trigger, notification, reads.

    - `frames`: frames delivered by notification on each trigger write;
    - `auth_ok`: authentication status byte read (True -> 0x01, False -> 0x00,
      None -> the read fails);
    - `write_errors`: exceptions raised successively by write_gatt_char;
    - `reads`: GATT read values (UUID -> bytes); missing -> error.
    """

    def __init__(
        self,
        frames: list[bytes] | None = None,
        auth_ok: bool | None = True,
        write_errors: list[BaseException | None] | None = None,
        reads: dict[str, bytes] | None = None,
        frames_per_trigger: int = 1,
    ) -> None:
        self.frames = list(frames or [])
        self.auth_ok = auth_ok
        self.write_errors = list(write_errors or [])
        self.reads = (
            {
                UUID_RAW_SENSORS: bytes.fromhex("0102030405"),
                UUID_ACCELEROMETER: (0).to_bytes(2, "big", signed=True)
                + (900).to_bytes(2, "big", signed=True)  # y > 700 → vertical
                + (0).to_bytes(2, "big", signed=True),
                UUID_SERIAL_NUMBER: b"SN12345\x00",
                UUID_HW_VERSION: b"WA000100\x00",
                UUID_SW_VERSION: b"CLOUD42\x00",
            }
            if reads is None
            else dict(reads)
        )
        self.is_connected = True
        self.writes: list[tuple[str, bytes]] = []
        self.notify_started = False
        self.notify_stopped = False
        self.disconnected = False
        self._handler: Callable[[Any, bytearray], None] | None = None
        # Number of frames delivered at once by the same trigger write (0x02):
        # >1 simulates a burst of notifications, to test queue-full behavior
        # (see test_notification_queue_full_is_logged).
        self.frames_per_trigger = frames_per_trigger

    async def start_notify(self, uuid: str, handler: Callable) -> None:
        self.notify_started = True
        self._handler = handler

    async def stop_notify(self, uuid: str) -> None:
        self.notify_stopped = True

    async def write_gatt_char(self, uuid: str, data, response: bool = True) -> None:
        self.writes.append((uuid, bytes(data)))
        if self.write_errors:
            error = self.write_errors.pop(0)
            if error is not None:
                raise error
        # Trigger write (0x02): the probe answers with a notification.
        if bytes(data) == b"\x02" and self._handler is not None:
            for _ in range(self.frames_per_trigger):
                if not self.frames:
                    break
                self._handler(None, bytearray(self.frames.pop(0)))

    async def read_gatt_char(self, uuid: str) -> bytearray:
        if uuid.startswith("1fb20002"):  # statut d'authentification
            if self.auth_ok is None:
                raise OSError("auth status unavailable")
            return bytearray([1 if self.auth_ok else 0])
        if uuid not in self.reads:
            raise OSError(f"cannot read {uuid}")
        return bytearray(self.reads[uuid])

    async def disconnect(self) -> None:
        self.disconnected = True
        self.is_connected = False
