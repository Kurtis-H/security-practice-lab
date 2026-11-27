"""Version 2 of the seat parser, kept as a fuzzing target. Don't use it.

It fixes version 1's range denial of service by capping the seat count,
but still trusts str.isdigit(): "R2-³" passes the check, then int("³")
raises a raw ValueError. The fuzzer finds this in under a minute.
seats.py fixes both bugs.
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
            if len(labels) + (last - first + 1) > 100:
                raise SeatParseError("more than 100 seats")
            labels.extend(f"R{row}-{n}" for n in range(first, last + 1))
        else:
            row, seat = _label(part)
            labels.append(f"R{row}-{seat}")
        if len(labels) > 100:
            raise SeatParseError("more than 100 seats")
    return labels
