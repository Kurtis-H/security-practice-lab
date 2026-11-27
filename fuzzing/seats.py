"""Parse seat selections like "R3-1..R3-4, R5-12" into seat labels.

The contract the fuzzer checks: for ANY input string, parse_seats either
returns a list of labels or raises SeatParseError. Anything else (an
IndexError, a ValueError, running out of memory) is a bug. And every label
it returns must parse back to itself.
"""

from __future__ import annotations

import re

MAX_SEATS = 100  # one request can't ask for more; also stops "R1-1..R1-999999999"

# ASCII digits only. str.isdigit() and \d also accept "²", "٣" and other
# Unicode digits that int() may reject; see buggy_seats_v2.py.
_LABEL = re.compile(r"R([0-9]{1,3})-([0-9]{1,3})")


class SeatParseError(ValueError):
    """The selection isn't valid. The only exception parse_seats raises."""


def _label(text: str) -> tuple[int, int]:
    match = _LABEL.fullmatch(text.strip())
    if not match:
        raise SeatParseError(f"not a seat label: {text.strip()!r}")
    row, seat = int(match.group(1)), int(match.group(2))
    if row < 1 or seat < 1:
        raise SeatParseError(f"rows and seats start at 1: {text.strip()!r}")
    return row, seat


def parse_seats(text: str) -> list[str]:
    labels: list[str] = []
    for part in text.split(","):
        if not part.strip():
            raise SeatParseError("empty item in the list")
        if ".." in part:
            start_text, _, end_text = part.partition("..")
            (row, first), (end_row, last) = _label(start_text), _label(end_text)
            if row != end_row:
                raise SeatParseError("a range must stay in one row")
            if last < first:
                raise SeatParseError("a range must go up")
            if len(labels) + (last - first + 1) > MAX_SEATS:
                raise SeatParseError(f"more than {MAX_SEATS} seats")
            labels.extend(f"R{row}-{n}" for n in range(first, last + 1))
        else:
            row, seat = _label(part)
            labels.append(f"R{row}-{seat}")
        if len(labels) > MAX_SEATS:
            raise SeatParseError(f"more than {MAX_SEATS} seats")
    return labels
