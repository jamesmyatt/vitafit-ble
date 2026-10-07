"""Frames captured from a real Vitafit VT701 with scripts/capture.py.

Captured on 7 Oct 2026 over several weigh-ins: barefoot and in socks, in
weight-only mode, and with the display in kg, lb and st.

The protocol combines openScale's VT701 handler
(https://github.com/oliexdev/openScale/pull/1423), which gave the frame layout,
the mode and hello commands, the weight and impedance frames and their
acknowledgements, with these captures, which added the command replies, the
weight flags, the display unit, the failed-impedance value and that the unit
command is optional.
"""

from __future__ import annotations


def h(text: str) -> bytes:
    """Bytes from space-separated hex."""
    return bytes.fromhex(text)


# Replies to the mode and hello commands, in order.
START_REPLIES = (
    h("5a 04 26 33 11 aa"),
    h("5a 05 26 44 00 67 aa"),
)
# Reply to the unit command, whatever the unit; only seen when one was sent.
UNIT_ACK = h("5a 04 26 17 35 aa")

NO_LOAD = h("5a 0a 26 10 00 00 00 21 00 00 1d aa")  # 0.00 kg, flag 0x00
# Sent with the display in lb or st. Byte 7 is the display unit (0x21 kg, 0x22 lb,
# 0x23 st); the weight bytes are 0.01 kg regardless.
NO_LOAD_LB = h("5a 0a 26 10 00 00 00 22 00 00 1e aa")  # 0.00 kg
SETTLING_LB = h("5a 0a 26 10 01 00 00 22 22 42 7f aa")  # 87.70 kg
SETTLING_ST = h("5a 0a 26 10 01 00 00 23 22 2e 12 aa")  # 87.50 kg
# After the library sent the unit command back with 02 or 03, the display stayed
# in lb or st.
STABLE_LB = h("5a 0a 26 10 02 00 00 22 22 10 2e aa")  # 87.20 kg
STABLE_ST = h("5a 0a 26 10 02 00 00 23 22 10 2f aa")  # 87.20 kg
SETTLING = h("5a 0a 26 10 01 00 00 21 22 24 1a aa")  # 87.40 kg, flag 0x01
STABLE = h("5a 0a 26 10 02 00 00 21 22 1f 22 aa")  # 87.35 kg, flag 0x02
STABLE_SOCKS = h("5a 0a 26 10 02 00 00 21 22 92 af aa")  # 88.50 kg, flag 0x02
IMPEDANCE = h("5a 0b 26 11 00 00 00 00 00 01 d2 ef aa")  # 466 ohm
IMPEDANCE_FAILED = h("5a 0b 26 11 00 00 00 00 00 ff ff 3c aa")  # in socks
# Barefoot, after the mode command with 0x01 (the Vitafit app's weight-only mode).
IMPEDANCE_WEIGHT_ONLY = h("5a 0b 26 11 00 00 00 00 00 55 aa c3 aa")
