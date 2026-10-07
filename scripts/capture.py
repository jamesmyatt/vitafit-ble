"""Capture Vitafit advertisements and GATT frames for testing and debugging.

Scans for a Vitafit scale and logs its advertisements, then connects and runs
one weigh-in with vitafit-ble, logging every frame sent and received. Each
event is also written to a JSON Lines file, one object per line, so captures
can be turned into test fixtures.

Step on the scale to wake it, then run from the repo root:

    uv run python scripts/capture.py              # one weigh-in
    uv run python scripts/capture.py --scan-only  # advertisements only
    uv run python scripts/capture.py --help
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import sys
import time
from typing import TYPE_CHECKING, Any, TextIO, cast

from bleak import BleakScanner
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from habluetooth import BluetoothServiceInfoBleak

from vitafit_ble import DisplayUnit, VitafitBluetoothDeviceData, async_measure
from vitafit_ble.const import IMPEDANCE_TIMEOUT, LOCAL_NAME_PREFIX, WEIGHT_TIMEOUT
from vitafit_ble.protocol import decode

if TYPE_CHECKING:
    from collections.abc import Callable

    from bleak import BleakClient
    from bleak.backends.characteristic import BleakGATTCharacteristic
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData

_LOGGER = logging.getLogger("vitafit_capture")

# --unit choices.
UNITS = {unit.name.lower(): unit for unit in DisplayUnit}


class Recorder:
    """Write timestamped events to a JSON Lines file."""

    def __init__(self, file: TextIO) -> None:
        """Record to an open text file."""
        self._file = file
        self._start = time.monotonic()

    def record(self, event: str, **fields: Any) -> None:  # noqa: ANN401
        """Write one event."""
        entry = {
            "time": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "elapsed": round(time.monotonic() - self._start, 3),
            "event": event,
            **fields,
        }
        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()


class RecordingClient:
    """Wrap a BleakClient to log every frame `async_measure` sends and receives."""

    def __init__(self, client: BleakClient, recorder: Recorder) -> None:
        """Wrap a connected client."""
        self._client = client
        self._recorder = recorder

    def _frame(self, direction: str, characteristic: str, data: bytes) -> None:
        decoded = decode(data) if direction == "rx" else None
        _LOGGER.info(
            "%s %s %s%s",
            direction.upper(),
            characteristic[4:8],
            data.hex(" "),
            f" {decoded}" if decoded else "",
        )
        self._recorder.record(
            direction,
            characteristic=characteristic,
            data=data.hex(),
            decoded=(
                {"type": type(decoded).__name__, **dataclasses.asdict(decoded)}
                if decoded
                else None
            ),
        )

    async def start_notify(
        self,
        characteristic: str,
        callback: Callable[[BleakGATTCharacteristic, bytearray], None],
    ) -> None:
        """Subscribe, logging each notification before passing it on."""

        def _callback(sender: BleakGATTCharacteristic, data: bytearray) -> None:
            self._frame("rx", characteristic, bytes(data))
            callback(sender, data)

        await self._client.start_notify(characteristic, _callback)

    async def write_gatt_char(
        self, characteristic: str, data: bytes, *, response: bool
    ) -> None:
        """Log a command, then write it."""
        self._frame("tx", characteristic, data)
        await self._client.write_gatt_char(characteristic, data, response=response)


def _service_info(
    device: BLEDevice, advertisement: AdvertisementData
) -> BluetoothServiceInfoBleak:
    return BluetoothServiceInfoBleak(
        name=advertisement.local_name or device.name or "",
        address=device.address,
        rssi=advertisement.rssi,
        manufacturer_data=advertisement.manufacturer_data,
        service_data=advertisement.service_data,
        service_uuids=advertisement.service_uuids,
        source="local",
        device=device,
        advertisement=advertisement,
        connectable=True,
        time=time.monotonic(),
        tx_power=advertisement.tx_power or 0,
        raw=None,
    )


async def _async_scan(
    recorder: Recorder,
    *,
    address: str | None,
    name_prefix: str,
    scan_time: float,
    scan_only: bool,
) -> BLEDevice | None:
    """Log matching advertisements; return the first matching device."""
    found: asyncio.Future[BLEDevice] = asyncio.get_running_loop().create_future()

    def _on_advertisement(device: BLEDevice, advertisement: AdvertisementData) -> None:
        name = advertisement.local_name or device.name or ""
        if address:
            if device.address.upper() != address.upper():
                return
        elif not name.startswith(name_prefix):
            return
        supported = VitafitBluetoothDeviceData().supported(
            _service_info(device, advertisement)
        )
        _LOGGER.info(
            "ADV %s %r rssi=%s supported=%s manufacturer=%s service_data=%s uuids=%s",
            device.address,
            name,
            advertisement.rssi,
            supported,
            {k: v.hex() for k, v in advertisement.manufacturer_data.items()},
            {k: v.hex() for k, v in advertisement.service_data.items()},
            advertisement.service_uuids,
        )
        recorder.record(
            "advertisement",
            address=device.address,
            name=name,
            rssi=advertisement.rssi,
            tx_power=advertisement.tx_power,
            manufacturer_data={
                str(k): v.hex() for k, v in advertisement.manufacturer_data.items()
            },
            service_data={k: v.hex() for k, v in advertisement.service_data.items()},
            service_uuids=advertisement.service_uuids,
            supported=supported,
        )
        if not found.done():
            found.set_result(device)

    _LOGGER.info("Scanning for %ss", scan_time)
    async with BleakScanner(detection_callback=_on_advertisement):
        if scan_only:
            await asyncio.sleep(scan_time)
            return None
        try:
            async with asyncio.timeout(scan_time):
                return await found
        except TimeoutError:
            return None


@dataclasses.dataclass(frozen=True, slots=True)
class WeighInOptions:
    """Options for one weigh-in."""

    weight_timeout: float
    impedance_timeout: float
    linger: float
    """Seconds to keep listening after the weigh-in."""
    unit: DisplayUnit | None
    """Display unit to set; None leaves the scale's unit alone."""
    weight_only: bool
    """Select the scale's weight-only mode instead of measuring impedance."""


async def _async_weigh_in(
    device: BLEDevice, recorder: Recorder, options: WeighInOptions
) -> bool:
    """Connect, log the GATT table, run one weigh-in and disconnect."""
    linger = options.linger
    disconnected = asyncio.Event()
    expected = False  # set just before we disconnect ourselves

    def _on_disconnect(_: BleakClient) -> None:
        by = "client" if expected else "scale"
        _LOGGER.info("Disconnected by %s", by)
        recorder.record("disconnected", by=by)
        disconnected.set()

    _LOGGER.info("Connecting to %s", device.address)
    client = await establish_connection(
        BleakClientWithServiceCache, device, device.address, _on_disconnect
    )
    try:
        for service in client.services:
            for char in service.characteristics:
                _LOGGER.info(
                    "GATT service %s characteristic %s %s",
                    service.uuid,
                    char.uuid,
                    ",".join(char.properties),
                )
                recorder.record(
                    "characteristic",
                    service=service.uuid,
                    characteristic=char.uuid,
                    properties=char.properties,
                )
        measurement = await async_measure(
            cast("BleakClient", RecordingClient(client, recorder)),
            weight_timeout=options.weight_timeout,
            impedance_timeout=options.impedance_timeout,
            display_unit=options.unit,
            weight_only=options.weight_only,
        )
        _LOGGER.info("Result: %s", measurement)
        recorder.record(
            "result",
            measurement=dataclasses.asdict(measurement) if measurement else None,
        )
        if linger and not disconnected.is_set():
            _LOGGER.info("Listening for %ss more", linger)
            # Stop early if the scale disconnects.
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(linger):
                    await disconnected.wait()
    except BleakError as err:
        _LOGGER.error("Bluetooth error: %s", err)  # noqa: TRY400
        recorder.record("error", error=str(err))
        return False
    finally:
        expected = True
        await client.disconnect()
    return measurement is not None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n", 1)[0] if __doc__ else None
    )
    parser.add_argument("--address", help="only this device address")
    parser.add_argument(
        "--name-prefix",
        default=LOCAL_NAME_PREFIX,
        help="match advertised names starting with this (default: %(default)s)",
    )
    parser.add_argument(
        "--scan-time",
        type=float,
        default=60.0,
        help="seconds to scan (default: %(default)s)",
    )
    parser.add_argument(
        "--scan-only", action="store_true", help="log advertisements; don't connect"
    )
    parser.add_argument(
        "--weight-timeout",
        type=float,
        default=WEIGHT_TIMEOUT,
        help="seconds to wait for a stable weight (default: %(default)s)",
    )
    parser.add_argument(
        "--impedance-timeout",
        type=float,
        default=IMPEDANCE_TIMEOUT,
        help="seconds to wait for impedance after the ack (default: %(default)s)",
    )
    parser.add_argument(
        "--unit",
        choices=list(UNITS),
        help="set the scale's display unit (default: leave it as it is)",
    )
    parser.add_argument(
        "--linger",
        type=float,
        default=2.0,
        help="seconds to keep listening after the weigh-in (default: %(default)s)",
    )
    parser.add_argument(
        "--rescan",
        type=float,
        default=0.0,
        help="seconds to scan after disconnecting, to see when the scale stops "
        "advertising (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="JSON Lines file (default: vitafit-capture-<time>.jsonl)",
    )
    parser.add_argument(
        "--weight-only",
        action="store_true",
        help="use the Vitafit app's weight-only mode: no impedance current. The "
        "scale keeps the mode for offline weigh-ins until the next connection",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="debug logs from bleak and vitafit_ble",
    )
    return parser.parse_args()


async def _async_main(args: argparse.Namespace) -> int:
    output = args.output or Path(
        f"vitafit-capture-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.jsonl"
    )
    with output.open("a", encoding="utf-8") as file:
        recorder = Recorder(file)
        recorder.record("start", argv=sys.argv[1:])
        _LOGGER.info("Step on the scale to wake it")
        device = await _async_scan(
            recorder,
            address=args.address,
            name_prefix=args.name_prefix,
            scan_time=args.scan_time,
            scan_only=args.scan_only,
        )
        if args.scan_only:
            ok = True
        elif device is None:
            _LOGGER.error("No matching device found")
            ok = False
        else:
            ok = await _async_weigh_in(
                device,
                recorder,
                WeighInOptions(
                    weight_timeout=args.weight_timeout,
                    impedance_timeout=args.impedance_timeout,
                    linger=args.linger,
                    unit=UNITS[args.unit] if args.unit else None,
                    weight_only=args.weight_only,
                ),
            )
            if args.rescan:
                _LOGGER.info(
                    "Rescanning for %ss to see when the scale stops advertising",
                    args.rescan,
                )
                recorder.record("rescan", seconds=args.rescan)
                await _async_scan(
                    recorder,
                    address=device.address,
                    name_prefix=args.name_prefix,
                    scan_time=args.rescan,
                    scan_only=True,
                )
        recorder.record("end", ok=ok)
    _LOGGER.info("Wrote %s", output)
    return 0 if ok else 1


def main() -> int:
    """Run the capture."""
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if args.verbose:
        logging.getLogger("bleak").setLevel(logging.DEBUG)
        logging.getLogger("vitafit_ble").setLevel(logging.DEBUG)
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    sys.exit(main())
