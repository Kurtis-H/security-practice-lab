#!/usr/bin/env python3
"""Fuzz the seat parser with Atheris (coverage-guided, libFuzzer-based).

    ./fuzz_seats.py corpus/ -fork=2 -max_total_time=60     # the real parser
    FUZZ_TARGET=buggy_seats_v2 ./fuzz_seats.py corpus/ -fork=2 -ignore_crashes=0

Run it as ./fuzz_seats.py, not python fuzz_seats.py: fork mode re-runs argv[0].

The checks are the parser's contract, not just "doesn't crash":
  * only SeatParseError may escape,
  * never more than MAX_SEATS labels (no denial of service),
  * every label returned parses back to exactly itself.
A failure writes the input to crash-<hash> and exits non-zero.
"""

import importlib
import os
import sys

import atheris

MAX_SEATS = 100

with atheris.instrument_imports():
    target = importlib.import_module(os.environ.get("FUZZ_TARGET", "seats"))


def TestOneInput(data: bytes) -> None:
    # Raw bytes read as UTF-8, so byte-level mutations reach any character
    # (a "1" can turn into the two bytes of "²").
    text = data[:256].decode("utf-8", errors="replace")
    try:
        labels = target.parse_seats(text)
    except target.SeatParseError:
        return
    assert len(labels) <= MAX_SEATS, f"{len(labels)} seats from {text!r}"
    for label in labels:
        assert target.parse_seats(label) == [label], (
            f"{label!r} doesn't parse back to itself"
        )


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
