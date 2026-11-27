"""Example-based tests. Both versions pass them all: that's the point.
The fuzzer found what these miss, and its finds are kept in regressions/."""

from pathlib import Path

import pytest

import buggy_seats_v1
import buggy_seats_v2
import seats

HERE = Path(__file__).parent


@pytest.mark.parametrize(
    "module", [seats, buggy_seats_v1, buggy_seats_v2], ids=["seats", "v1", "v2"]
)
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("R1-1", ["R1-1"]),
        ("R2-3..R2-5", ["R2-3", "R2-4", "R2-5"]),
        (" R1-1 , R4-10 ", ["R1-1", "R4-10"]),
        ("R3-7..R3-7", ["R3-7"]),
    ],
)
def test_examples(module, text, expected):
    assert module.parse_seats(text) == expected


@pytest.mark.parametrize(
    "module", [seats, buggy_seats_v1, buggy_seats_v2], ids=["seats", "v1", "v2"]
)
@pytest.mark.parametrize(
    "text",
    [
        "",
        "R1",
        "S1-1",
        "R0-1",
        "R1-1..R2-3",
        "R1-5..R1-2",
        "R1-1,,R1-2",
        "Rx-1",
        "R1-1..",
    ],
)
def test_bad_input_is_rejected(module, text):
    with pytest.raises(module.SeatParseError):
        module.parse_seats(text)


def test_the_real_parser_caps_the_number_of_seats():
    assert len(seats.parse_seats("R1-1..R1-100")) == 100
    with pytest.raises(seats.SeatParseError):
        seats.parse_seats("R1-1..R1-101")
    with pytest.raises(seats.SeatParseError):
        seats.parse_seats(",".join(f"R1-{n}" for n in range(1, 102)))


@pytest.mark.parametrize(
    "path", sorted((HERE / "regressions").glob("*")), ids=lambda p: p.name
)
def test_inputs_the_fuzzer_found_are_handled(path):
    """Every input that broke an earlier version must be handled by seats."""
    text = path.read_bytes()[:256].decode(
        "utf-8", errors="replace"
    )  # as the harness reads it
    try:
        labels = seats.parse_seats(text)
    except seats.SeatParseError:
        return
    assert len(labels) <= seats.MAX_SEATS
    assert all(seats.parse_seats(label) == [label] for label in labels)


def test_v2_really_had_the_unicode_digit_bug():
    """The kept crash is a real one: version 2 lets a raw ValueError escape."""
    text = (HERE / "regressions" / "v2-unicode-digit").read_bytes().decode()
    with pytest.raises(ValueError) as caught:
        buggy_seats_v2.parse_seats(text)
    assert not isinstance(caught.value, buggy_seats_v2.SeatParseError)
