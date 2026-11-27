"""Version 1 of the seat parser, kept as a fuzzing target. Don't use it.

It passes every example-based test in test_seats.py, yet has two bugs:
  1. "R1-1..R1-99999999" builds 100 million labels and runs out of memory
     (a denial of service): nothing caps the range size.
  2. "R2-³" crashes: str.isdigit() is True for "³" and other Unicode digits,
     but int("³") raises ValueError instead of SeatParseError.
libFuzzer stops at the first finding, so it reports bug 1 (in seconds).
Version 2 fixes bug 1, and fuzzing it then finds bug 2.
"""

from __future__ import annotations


class SeatParseError(ValueError):
    pass


def _label(text: str) -> tuple[int, int]:
    text = text.strip()
    if not text.startswith("R") or "-" not in text:
        raise SeatParseError(f"not a seat label: {text!r}")
    row, _, seat = text[1:].partition("-")
    if not (row.isdigit() and seat.isdigit()):
        raise SeatParseError(f"not a seat label: {text!r}")
    row_n, seat_n = int(row), int(seat)
    if row_n < 1 or seat_n < 1:
        raise SeatParseError("rows and seats start at 1")
    return row_n, seat_n


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
            labels.extend(f"R{row}-{n}" for n in range(first, last + 1))
        else:
            row, seat = _label(part)
            labels.append(f"R{row}-{seat}")
    return labels
