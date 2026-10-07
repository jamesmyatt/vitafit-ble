# Vitafit protocol

## VT701

This page documents the GATT exchange that
[`vitafit_ble.session`](https://github.com/jamesmyatt/vitafit-ble/blob/main/src/vitafit_ble/session.py)
runs and the frames that
[`vitafit_ble.protocol`](https://github.com/jamesmyatt/vitafit-ble/blob/main/src/vitafit_ble/protocol.py)
encodes and decodes. It is a developer reference, not a stable public API.

### Advertisement

The scale only advertises while it is awake, after someone steps on it. Its
local name is `Vitafit Body Fat`, and it advertises no service UUIDs. Its
manufacturer data uses company ID `0xFFFF` and is 14 bytes:
`01 26 00 01 00 00 00 26` followed by the scale's MAC address. The meaning of
the first 8 bytes is unknown.

### GATT exchange

GATT service `0xFFF0`. The scale notifies on `0xFFF1`; the client writes on
`0xFFF2`.

Frame layout is `[header][length][0x26][type][data…][checksum][0xAA]`:

- `header` is `0xA5` from client to scale, and `0x5A` from scale to client.
- `length` counts the bytes after itself.
- `checksum` is the XOR of `length` through the last data byte.

The frames, in the order `vitafit-ble` runs them, after subscribing:

| Type               | Direction      | Frame                                                    | Meaning                                                                                                                                                                                                                                                                                                                                         |
| ------------------ | -------------- | -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0x33` `MODE`      | Client → scale | `a5 05 26 33 <mode> <chk> aa`                            | Mode command: `00` (`a5 05 26 33 00 10 aa`) measures impedance, `01` (`a5 05 26 33 01 11 aa`) is weight-only. openScale calls this the first hello.                                                                                                                                                                                             |
| `0x33` `MODE`      | Scale → client | `5a 04 26 33 11 aa`                                      | Reply, the same for either mode. Not decoded.                                                                                                                                                                                                                                                                                                   |
| `0x44` `HELLO`     | Client → scale | `a5 04 26 44 66 aa`                                      | Unknown request, referred to as the hello command.                                                                                                                                                                                                                                                                                              |
| `0x44` `HELLO`     | Scale → client | `5a 05 26 44 00 67 aa`                                   | Reply: one data byte of unknown meaning, `00` in every capture so far. Not decoded.                                                                                                                                                                                                                                                             |
| `0x17` `UNIT`      | Client → scale | `a5 05 26 17 <code> <chk> aa`                            | Optional: set the display unit, `code` 01 kg, 02 lb, 03 st. Only sent when `async_measure()` is given `display_unit`.                                                                                                                                                                                                                           |
| `0x17` `UNIT`      | Scale → client | `5a 04 26 17 35 aa`                                      | Reply, the same for every unit. Not decoded.                                                                                                                                                                                                                                                                                                    |
| `0x10` `WEIGHT`    | Scale → client | `5a 0a 26 10 <flag> 00 00 <unit> <w_hi> <w_lo> <chk> aa` | Weight, 0.01 kg, big-endian, whatever the display unit. `flag` is 0x00 with no load, 0x01 while measuring and 0x02 when stable. `unit` is 0x20 + the display unit: 0x21 kg, 0x22 lb, 0x23 st. Streamed throughout, from as soon as notifications are on.                                                                                        |
| `0x10` `WEIGHT`    | Client → scale | `a5 05 26 10 <flag> <chk> aa`                            | Acknowledge a weight frame, echoing its `flag`. `vitafit-ble` only acknowledges the stable weight (`a5 05 26 10 02 31 aa`). openScale says this starts the impedance measurement; a normal-mode weigh-in without it hasn't been tried. The Vitafit app also acknowledges each settling frame (`a5 05 26 10 01 32 aa`); no effect has been seen. |
| `0x11` `IMPEDANCE` | Scale → client | `5a 0b 26 11 00 00 00 00 00 <z_hi> <z_lo> <chk> aa`      | Impedance, Ω, big-endian. `0xFFFF` means the scale couldn't measure it, for example through socks; `0x55AA` means weight-only mode.                                                                                                                                                                                                             |
| `0x11` `IMPEDANCE` | Client → scale | `a5 05 26 11 00 32 aa`                                   | Acknowledge impedance                                                                                                                                                                                                                                                                                                                           |

Display unit, from captures of a real scale:

- `unit` is 0x20 plus a unit code: 1 kg, 2 lb, 3 st. With the display set to
  lb or st, weight frames had `unit` 0x22 or 0x23.
- The unit command sets the display unit straight away, even mid-weigh-in.
  The scale replies about 0.1 s later, and never sends that reply otherwise.
- The unit command is optional. Without it, the scale keeps its unit and still
  sends the stable weight and impedance. openScale always sends it, with `01`,
  after the mode and hello commands.
- The weight bytes are in 0.01 kg whatever the display unit: an lb frame read
  87.70 and the next, kg, frame 87.55; an st frame read 87.50 and the next
  87.20.

Weight-only mode, from captures of a real scale and the Vitafit app:

- The Vitafit app sends the mode command with `01` for its "Weight Only Mode", which
  the manual describes as "zero-current technology that only measure weight
  and BMI", for users who are pregnant or have a pacemaker.
- With `01`, barefoot weigh-ins gave impedance `0x55AA` 0.7–2.2 s after the
  stable-weight acknowledgement. With `00`, the next weigh-in gave 447 Ω after
  5 s.
- The scale remembers the mode: it carries over to later weigh-ins without a
  connection, until a mode command sets it again. `async_measure()` sends the
  mode command on every connection: `01` with `weight_only=True`, otherwise
  `00`.

Type `0x15` frames, from captures of the Vitafit app:

- In both modes, after the first impedance frame and before acknowledging it,
  the app writes two unexplained type `0x15` frames, parts `01` and `02`. The
  scale doesn't reply to them, and `vitafit-ble` doesn't send them.
- In normal mode, after a real impedance, the data changes with each weigh-in
  and looks packed or scrambled, probably the app's body-composition results.
  After 440 Ω:
  `a5 0f 26 15 01 6d 0e 21 ee 22 b5 41 45 61 13 70 aa` and
  `a5 0f 26 15 02 40 c7 21 9c 60 12 26 7b 6f 2c 68 aa`.
- In weight-only mode, the data is mostly zeros:
  `a5 0f 26 15 01 0c 00 00 00 00 00 00 00 61 2d 7d aa` and
  `a5 0f 26 15 02 00 00 00 00 18 f0 18 f0 10 10 3e aa`. The last data byte
  of part 1 varied between captures: `2d` here, `2f` in an earlier one.

Timing, from captures of a real scale:

- Weight frames arrive about every 0.36 s, starting as soon as notifications
  are on, even before the mode and hello commands are sent.
- After the stable-weight acknowledgement, the scale keeps repeating the
  stable weight until impedance is ready, about 5 s later.
- The scale repeats the impedance frame until it is acknowledged.

This protocol combines openScale's
[VT701 handler](https://github.com/oliexdev/openScale/pull/1423) with captures
from a real VT701 made with `scripts/capture.py`. openScale gave the frame
layout, the mode and hello commands, and the weight and impedance frames with their
acknowledgements. The captures added the command replies, the weight flags,
the display unit, the failed-impedance value, the timing, and that the unit
command is optional. The frames on this page and the test vectors in
`tests/frames.py` are from those captures.

## Capturing frames

`scripts/capture.py` records a real weigh-in for testing and debugging. It
scans for the scale, logs each advertisement and whether `vitafit-ble`
recognises it, then connects, lists the GATT services, and runs
`async_measure()`, logging every frame sent (`TX`) and received (`RX`) with
its decoded value. It keeps listening for a couple of seconds afterwards
(`--linger`) to catch any late frames, and logs who ends the connection,
the scale or the script. With `--rescan SECONDS`, it then scans again to show
how long the scale keeps advertising. Each event is also written to a JSON
Lines file (`vitafit-capture-<time>.jsonl` by default).

Step on the scale to wake it, then run from the repo root:

```sh
uv run python scripts/capture.py              # one weigh-in
uv run python scripts/capture.py --scan-only  # advertisements only
uv run python scripts/capture.py --rescan 60  # then watch advertising for 60 s
uv run python scripts/capture.py --unit lb    # also set the display unit (kg, lb or st)
uv run python scripts/capture.py --help       # address filter, timeouts, output file
```
