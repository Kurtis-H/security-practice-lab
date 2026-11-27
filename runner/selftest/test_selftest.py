"""minitest testing its own helpers, using only its own API.

CI runs this with minitest itself. The real proof is test_runner.py (pytest),
since a broken runner could pass its own tests; this shows the API in use.
"""

import minitest
from minitest import fixture, parametrize, raises, skip_if


@fixture(scope="session")
def results():
    return [
        minitest.Result("a", "passed"),
        minitest.Result("b", "failed"),
        minitest.Result("c", "passed"),
        minitest.Result("d", "skipped"),
    ]


@fixture
def counts(results):
    return minitest._count(results)


def test_count_every_outcome(counts):
    assert counts == {"passed": 2, "failed": 1, "error": 0, "skipped": 1, "xfailed": 0}


@parametrize(
    "value, expected",
    [(3, "3"), (None, "None"), (True, "True"), ("short", "short"), ("x" * 21, "str")],
)
def test_id_parts(value, expected):
    assert minitest._id_part(value) == expected


@parametrize(
    "text, expected",
    [
        ("plain", "plain"),
        ("a\x00b", "a\\x00b"),
        ("\x1b[31m", "\\x1b[31m"),
        ("tab\tok", "tab\tok"),
    ],
)
def test_xml_safe(text, expected):
    assert minitest._xml_safe(text) == expected


def test_expand_multiplies_stacked_parameters():
    @parametrize("a", [1, 2])
    @parametrize("b", ["x", "y", "z"])
    def sample(a, b):
        pass

    combos = minitest.expand(sample)
    assert len(combos) == 6
    assert combos[0] == ("1-x", {"a": 1, "b": "x"})


def test_unknown_fixture_scope_is_rejected():
    with raises(ValueError, match="unknown fixture scope"):
        fixture(scope="module")


@skip_if(not hasattr(minitest, "main"), "no entry point")
def test_has_an_entry_point():
    assert callable(minitest.main)


class TestRaises:
    def test_passes_when_raised(self):
        with raises(KeyError):
            {}["missing"]

    def test_fails_when_not_raised(self):
        with raises(AssertionError, match="did not raise"), raises(KeyError):
            pass
