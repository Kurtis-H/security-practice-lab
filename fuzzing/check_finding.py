"""Confirm a fuzzer finding is the bug that was planted, not some other failure.

    python check_finding.py buggy_seats_v1 out/crash-...

Exits 0 and prints the input if the finding matches the target's known bug.
"""

import sys
from pathlib import Path

import buggy_seats_v2


def is_range_dos(text: str) -> bool:
    """v1 has no seat cap. v2 is v1 plus the cap, so v2 must refuse the size.

    (seats.py can't judge this: it rejects numbers over 3 digits first.)
    """
    try:
        buggy_seats_v2.parse_seats(text)
    except buggy_seats_v2.SeatParseError as error:
        return "more than" in str(error)
    except ValueError:
        return False
    return False


def is_unicode_digit_crash(text: str) -> bool:
    """v2 trusts isdigit(): the input leaks a raw ValueError."""
    try:
        buggy_seats_v2.parse_seats(text)
    except buggy_seats_v2.SeatParseError:
        return False
    except ValueError:
        return True
    return False


def is_either_v1_bug(text: str) -> bool:
    """v1 has both bugs; the fuzzer reports whichever it hits first."""
    return is_range_dos(text) or is_unicode_digit_crash(text)


CHECKS = {"buggy_seats_v1": is_either_v1_bug, "buggy_seats_v2": is_unicode_digit_crash}

if __name__ == "__main__":
    target, path = sys.argv[1], Path(sys.argv[2])
    text = path.read_bytes()[:256].decode("utf-8", errors="replace")  # as the harness
    print(f"Input: {text[:80]!r}")
    if not CHECKS[target](text):
        sys.exit(f"{path.name} is not {target}'s planted bug")
    print(f"Confirmed: {target}'s planted bug")
