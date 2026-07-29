"""BLE connection handling for SUNTEK SC-BLE fridges.

The fridge pushes a status frame every ~4 seconds and an extra one immediately on any
state change, so this holds a persistent connection and subscribes rather than polling.

It accepts only one BLE connection at a time — when the owner opens the vendor app we
get dropped. That is normal operation, not an error, so reconnection backs off and keeps
trying quietly instead of logging noisily.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import CHAR_STATUS
from .protocol import FrameBuffer, FrameError, FridgeStatus, parse_frame

_LOGGER = logging.getLogger(__name__)

RECONNECT_BACKOFF = (2, 5, 10, 20, 30, 60)


class SuntekFridgeDevice:
    """Maintains a subscribed connection and publishes decoded status."""

    def __init__(
        self,
        ble_device: BLEDevice,
        resolve_device: Callable[[], BLEDevice | None],
    ) -> None:
        self._ble_device = ble_device
        self._resolve_device = resolve_device
        self._client: BleakClientWithServiceCache | None = None
        self._buffer = FrameBuffer()
        self._callbacks: list[Callable[[], None]] = []
        self._reconnect_task: asyncio.Task | None = None
        self._stopping = False
        self.status: FridgeStatus | None = None

    @property
    def address(self) -> str:
        return self._ble_device.address

    @property
    def available(self) -> bool:
        return self._client is not None and self._client.is_connected and self.status is not None

    def register_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to status updates. Returns an unsubscribe callable."""
        self._callbacks.append(callback)

        def _unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._callbacks.remove(callback)

        return _unsubscribe

    def _notify_listeners(self) -> None:
        for callback in list(self._callbacks):
            callback()

    async def start(self) -> None:
        """Connect and subscribe. Raises if the initial connection fails."""
        await self._connect()

    async def stop(self) -> None:
        self._stopping = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None
        if self._client:
            with contextlib.suppress(BleakError, OSError):
                await self._client.disconnect()
            self._client = None

    async def _connect(self) -> None:
        device = self._resolve_device() or self._ble_device
        self._ble_device = device
        self._buffer.reset()

        client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            device.address,
            self._handle_disconnect,
        )
        self._client = client
        await client.start_notify(CHAR_STATUS, self._handle_notify)

        # Prime immediately so entities populate without waiting for the heartbeat.
        with contextlib.suppress(BleakError, OSError):
            data = await client.read_gatt_char(CHAR_STATUS)
            self._handle_notify(None, bytearray(data) + b"\n")

        _LOGGER.debug("Connected to %s", device.address)

    def _handle_notify(self, _characteristic, data: bytearray) -> None:
        for frame in self._buffer.feed(bytes(data)):
            try:
                self.status = parse_frame(frame)
            except FrameError as err:
                # A single bad frame is not worth dropping the connection over; the
                # next heartbeat is ~4 seconds away.
                _LOGGER.debug("Ignoring unparseable frame: %s", err)
                continue
            self._notify_listeners()

    def _handle_disconnect(self, _client: BleakClientWithServiceCache) -> None:
        if self._stopping:
            return
        _LOGGER.debug("Disconnected from %s; will reconnect", self.address)
        self.status = None
        self._notify_listeners()
        if not self._reconnect_task or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        for attempt, delay in enumerate(RECONNECT_BACKOFF, start=1):
            if self._stopping:
                return
            await asyncio.sleep(delay)
            try:
                await self._connect()
            except (BleakError, OSError, asyncio.TimeoutError) as err:
                _LOGGER.debug("Reconnect attempt %s failed: %s", attempt, err)
                continue
            self._notify_listeners()
            return

        # Settle into a slow retry rather than giving up — the usual cause is the
        # owner having the vendor app open, which may last a while.
        while not self._stopping:
            await asyncio.sleep(RECONNECT_BACKOFF[-1])
            try:
                await self._connect()
            except (BleakError, OSError, asyncio.TimeoutError):
                continue
            self._notify_listeners()
            return
