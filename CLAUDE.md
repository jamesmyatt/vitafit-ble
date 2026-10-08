# CLAUDE.md: vitafit-ble

Python library (PyPI `vitafit-ble`, MIT) for the Vitafit VT701 body fat scale. It reads weight and impedance over BLE GATT.

It is used by the Home Assistant integration in the sibling repo `../ha-vitafit-ble`. Read that repo's `CLAUDE.md` for the owner's preferences, the decisions already made and the overall next steps.

## Status (7 Oct 2026)

- v0.1.0 released on PyPI on 7 Oct 2026 via `release.yml`, with docs at `vitafit-ble.readthedocs.io`. Renovate is enabled.
- Tested on the owner's real VT701 with `scripts/capture.py`. The frames in `tests/frames.py` are real captures.
- The Vitafit app's traffic was captured with Android HCI snoop logs, stored in a gitignored folder (`btsnoop_logs/`) because they include other devices' traffic.

## Scope and decisions

Don't revisit these without asking.

- Weight (kg) and whole-body impedance (Ω) only. No body composition or user profiles; downstream applications such as Home Assistant handle those.
- `async_measure(display_unit=..., weight_only=...)` are optional. By default no unit command is sent, so the scale keeps its display unit, and the mode command selects normal mode. The HA integration only sets the mode.
- `async_poll(ble_device, **measure_kwargs)` passes keyword arguments through to `async_measure`. The owner chose a plain `**kwargs` over named parameters, so mypy doesn't check them.
- No `homeassistant` imports. Use [`inkbird-ble`](https://github.com/Bluetooth-Devices/inkbird-ble) first as the template for structure, docs and code patterns. [`oralb-ble`](https://github.com/Bluetooth-Devices/oralb-ble) is the reference for the `BleakError` handling in `async_poll` and for the shape of `docs/protocol.md`.
- Protocol source: openScale [PR #1423](https://github.com/oliexdev/openScale/pull/1423) (`VitafitVT701Handler.kt`). Treat it as correct, because the owner's scale works with openScale. Real captures have extended it; `docs/protocol.md` has the frames, timing and Vitafit app findings.
- The Vitafit app also sends things the library doesn't need: the mode command repeatedly, the unit command, an ack for every weight frame, and two type `0x15` frames that look like body-composition results. Don't add or decode them.

Deliberately different from the [Bluetooth-Devices](https://github.com/Bluetooth-Devices) org patterns (owner's decisions, 6 Oct 2026):

- `uv_build`, not Poetry.
- Manual GitHub release triggers `release.yml`, with a hand-written `CHANGELOG.md` (Keep a Changelog), not python-semantic-release.
- ruff `ALL` and strict mypy.
- `requires-python >= 3.11` (the real minimum, for `asyncio.timeout`), but CI only tests 3.14, the version HA 2026.9 uses.
- No `__version__` constant; use `importlib.metadata.version("vitafit-ble")`.
- No `@retry_bluetooth_connection_error()`: the weigh-in has state (subscribe, mode and hello commands, wait, ack), so a blind retry could subscribe twice or resend the commands. `establish_connection` already retries the connection.
- Prettier comes from `rbubley/mirrors-prettier` (stable 3.x), because the org's `pre-commit/mirrors-prettier` is archived and pins a 4.0 alpha. It takes indentation from `.editorconfig`.

## Code rules

- `FrameType` and `ImpedanceCode` are enums because `match` needs dotted names; a bare constant in a `case` is a capture pattern.
- Keep "is the frame intact" (`_is_valid`, including the per-type length in `FRAME_LENGTHS`) separate from "is the type decoded" (the `match` in `decode`). Replies to the mode, hello and unit commands are valid frames that `decode` ignores.
- A failed impedance (`0xFFFF` in socks, `0x55AA` in weight-only mode, or out of range) must stay `ImpedanceFrame(impedance_ohm=None)`, not `None`. The session needs it to ack the frame and stop waiting.
- Terminology: type `0x33` is the **mode command** (openScale's first hello) and `0x44` is an unknown request, referred to as the **hello command** (the scale's reply has one data byte, `00` so far). `start_commands()` yields both, then the optional unit command.
- Log at debug level only, apart from the `BleakError` warning in `async_poll`.

## Commands

```sh
uv sync                      # Python 3.11+; CI and HA use 3.14
uv run pre-commit install    # once
uv run pre-commit run --all-files   # ruff, strict mypy, prettier, codespell, pyupgrade, …
uv run pytest                # with coverage
uv run python scripts/capture.py   # log and record a real weigh-in (JSON Lines); --help for options
uv sync --group docs && uv run sphinx-build -W -b html docs docs/_build/html
uv build
```

In CI, the pre-commit hooks run on [pre-commit.ci](https://pre-commit.ci) (configured by the `ci:` block in `.pre-commit-config.yaml`), as `pre-commit/action` recommends; `.github/workflows/ci.yml` only runs the tests.

## Release

Releases are published by `.github/workflows/release.yml` when a GitHub release is published. It uses PyPI trusted publishing, so no token is needed.

To release:

1. Bump `version` in `pyproject.toml`.
2. In `CHANGELOG.md`, rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD`, add a new empty `[Unreleased]` section, and update the links at the bottom.
3. Publish a GitHub release named `vX.Y.Z`.
4. Update `requirements` in `../ha-vitafit-ble/custom_components/vitafit_ble/manifest.json` and that repo's `requirements_dev.txt`.

## Next steps

1. The only uncovered line is the "no stable weight" debug log in `parser.py`'s `async_poll`. It overlaps the session's own timeout log, so it could be removed or tested.
