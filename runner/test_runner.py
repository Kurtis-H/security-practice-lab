"""Tests for minitest, written with pytest (the runner under test can't vouch
for itself). Each test writes a small project into a temp folder and runs it."""

import io
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import minitest

HERE = Path(__file__).parent


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Write files into a temp project, then run minitest there."""
    monkeypatch.chdir(tmp_path)

    class Project:
        path = tmp_path

        def write(self, name, code):
            file = tmp_path / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(textwrap.dedent(code))
            return file

        def run(self, *args):
            out = io.StringIO()
            code = minitest.main(list(args), out=out)
            return code, out.getvalue()

        def junit(self, *args):
            code, _ = self.run(*args, "--junit", "report.xml")
            suite = ET.parse(tmp_path / "report.xml").getroot()
            outcomes = {}
            for case in suite.iter("testcase"):
                kind = next((child.tag for child in case), "passed")
                outcomes[f"{case.get('classname')}::{case.get('name')}"] = kind
            return code, suite, outcomes

    return Project()


# ---------------------------------------------------------------- exit codes


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("def test_ok():\n    assert True\n", minitest.EXIT_OK),
        ("def test_bad():\n    assert 1 == 2\n", minitest.EXIT_FAILED),
        ("import not_a_real_module\n", minitest.EXIT_INTERRUPTED),
        ("def helper():\n    pass\n", minitest.EXIT_NO_TESTS),
    ],
    ids=["pass", "fail", "import-error", "no-tests"],
)
def test_exit_codes_match_pytest(project, code, expected):
    project.write("test_a.py", code)
    assert project.run()[0] == expected


def test_missing_path_and_bad_flag_are_usage_errors(project):
    assert project.run("nowhere/")[0] == minitest.EXIT_USAGE
    assert project.run("--no-such-flag")[0] == minitest.EXIT_USAGE


def test_an_error_in_one_file_still_reports_it(project):
    project.write("test_ok.py", "def test_ok():\n    pass\n")
    project.write("test_broken.py", "def test_x(:\n")
    code, output = project.run()
    assert code == minitest.EXIT_INTERRUPTED
    assert "test_broken.py: failed to import" in output and "SyntaxError" in output


# ---------------------------------------------------------------- discovery


def test_discovers_functions_classes_and_subfolders_only(project):
    project.write(
        "test_a.py",
        """
        def test_one(): pass
        def helper_not_a_test(): pass
        class TestGroup:
            def test_two(self): pass
            def not_a_test(self): pass
        class Helper:
            def test_ignored(self): pass
        """,
    )
    project.write("sub/test_b.py", "def test_three(): pass\n")
    project.write("notes.py", "def test_not_in_a_test_file(): pass\n")
    project.write(".hidden/test_c.py", "def test_hidden(): pass\n")
    _, _, outcomes = project.junit()
    assert set(outcomes) == {
        "test_a::test_one",
        "test_a.TestGroup::test_two",
        "sub.test_b::test_three",
    }


def test_each_test_gets_a_fresh_class_instance(project):
    project.write(
        "test_a.py",
        """
        class TestState:
            items = None
            def test_first(self):
                assert self.items is None
                self.items = [1]
            def test_second(self):
                assert self.items is None
        """,
    )
    assert project.run()[0] == minitest.EXIT_OK


def test_k_selects_and_x_stops_at_first_failure(project):
    project.write(
        "test_a.py",
        """
        def test_alpha(): assert False
        def test_beta(): assert False
        def test_gamma(): pass
        """,
    )
    _, _, outcomes = project.junit("-k", "gamma")
    assert outcomes == {"test_a::test_gamma": "passed"}
    _, _, outcomes = project.junit("-x")
    assert list(outcomes) == ["test_a::test_alpha"]


# ---------------------------------------------------------------- fixtures


def test_fixture_setup_and_teardown_order(project):
    project.write(
        "test_a.py",
        """
        from minitest import fixture
        log = []

        @fixture(scope="session")
        def db():
            log.append("db up"); yield "db"; log.append("db down")

        @fixture
        def user(db):
            log.append("user up"); yield "ann"; log.append("user down")

        def test_one(user, db):
            log.append("test one")

        def test_two(user):
            log.append("test two")
            assert False

        def test_zz_log():
            assert log == [
                "db up", "user up", "test one", "user down",
                "user up", "test two", "user down",
            ], log
        """,
    )
    _, _, outcomes = project.junit()
    # The session fixture is set up once and torn down only at the end;
    # a failing test still gets its teardown.
    assert outcomes["test_a::test_two"] == "failure"
    assert outcomes["test_a::test_zz_log"] == "passed"


def test_teardown_runs_newest_first(project):
    """A connection must close before the database it depends on."""
    project.write(
        "test_a.py",
        """
        from minitest import fixture
        log = []

        @fixture
        def database():
            yield "db"
            log.append("database closed")

        @fixture
        def connection(database):
            yield "conn"
            log.append("connection closed")

        def test_uses_both(connection):
            pass

        def test_zz_order():
            assert log == ["connection closed", "database closed"], log
        """,
    )
    assert project.run()[0] == minitest.EXIT_OK


def test_fixtures_in_conftest_are_shared(project):
    project.write(
        "conftest.py",
        "from minitest import fixture\n@fixture\ndef answer():\n    return 42\n",
    )
    project.write(
        "sub/test_a.py", "def test_uses_it(answer):\n    assert answer == 42\n"
    )
    assert project.run()[0] == minitest.EXIT_OK


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("def test_x(nope): pass\n", "fixture 'nope' not found"),
        (
            (
                "from minitest import fixture\n"
                "@fixture\ndef a(b): return 1\n@fixture\ndef b(a): return 2\n"
                "def test_x(a): pass\n"
            ),
            "fixture cycle: a -> b -> a",
        ),
        (
            (
                "from minitest import fixture\n"
                "@fixture\ndef f():\n    yield 1\n    raise OSError('cleanup broke')\n"
                "def test_x(f): pass\n"
            ),
            "teardown failed",
        ),
        (
            (
                "from minitest import fixture\n"
                "@fixture\ndef per_test(): return 1\n"
                "@fixture(scope='session')\ndef shared(per_test): return 2\n"
                "def test_x(shared): pass\n"
            ),
            "session fixture 'shared' can't use a function fixture",
        ),
    ],
    ids=["missing", "cycle", "teardown-raises", "scope-mismatch"],
)
def test_fixture_problems_are_errors_not_failures(project, code, message):
    project.write("test_a.py", code)
    code_, output = project.run()
    assert code_ == minitest.EXIT_FAILED
    assert "ERROR test_a.py::test_x" in output and message in output


# ---------------------------------------------------------------- marks


def test_parametrize_ids_and_stacking(project):
    project.write(
        "test_a.py",
        """
        from minitest import parametrize
        @parametrize("a, b", [(1, 2), (3, 4)])
        @parametrize("op", ["add", "mul"])
        def test_x(a, b, op):
            assert a < b
        @parametrize("value", [object(), "a very long string that is too long"])
        def test_odd_ids(value): pass
        """,
    )
    _, _, outcomes = project.junit()
    assert set(outcomes) == {
        "test_a::test_x[1-2-add]",
        "test_a::test_x[1-2-mul]",
        "test_a::test_x[3-4-add]",
        "test_a::test_x[3-4-mul]",
        "test_a::test_odd_ids[object]",
        "test_a::test_odd_ids[str]",
    }


def test_parametrize_rejects_rows_of_the_wrong_size():
    with pytest.raises(ValueError, match="doesn't match"):
        minitest.parametrize("a, b", [(1, 2), (3,)])(lambda a, b: None)


def test_skip_skip_if_and_strict_xfail(project):
    project.write(
        "test_a.py",
        """
        from minitest import skip, skip_if, xfail
        @skip("later")
        def test_skip(): raise RuntimeError
        @skip_if(False, "never")
        def test_not_skipped(): pass
        @xfail("known bug")
        def test_xfail(): assert False
        @xfail("fixed?")
        def test_xpass(): pass
        """,
    )
    code, _, outcomes = project.junit()
    assert outcomes == {
        "test_a::test_skip": "skipped",
        "test_a::test_not_skipped": "passed",
        "test_a::test_xfail": "skipped",
        "test_a::test_xpass": "failure",  # strict: an unexpected pass is a failure
    }
    assert code == minitest.EXIT_FAILED


def test_raises():
    with minitest.raises(KeyError):
        {}["missing"]
    with minitest.raises(ValueError, match="bad"):
        raise ValueError("bad input")
    with (
        pytest.raises(AssertionError, match="did not raise"),
        minitest.raises(KeyError),
    ):
        pass
    with (
        pytest.raises(AssertionError, match="doesn't contain"),
        minitest.raises(ValueError, match="other"),
    ):
        raise ValueError("bad input")
    # The wrong exception type isn't swallowed.
    with pytest.raises(TypeError), minitest.raises(ValueError):
        raise TypeError("wrong")


# ---------------------------------------------------------------- reporting


def test_failure_report_shows_the_line_and_its_values(project):
    project.write(
        "test_a.py",
        """
        def test_total():
            prices = [100, 250]
            total = prices[0]
            assert total == sum(prices), "total skips seats"
        """,
    )
    _, output = project.run()
    assert "AssertionError: total skips seats" in output
    assert 'assert total == sum(prices), "total skips seats"' in output
    assert "total = 100" in output and "prices = [100, 250]" in output


def test_junit_counts_and_survives_hostile_text(project):
    project.write(
        "test_a.py",
        """
        def test_pass(): pass
        def test_markup(): assert False, "<script>&amp;</script>"
        def test_control_chars(): assert False, "bell\\x07 escape\\x1b[31m nul\\x00"
        """,
    )
    code, suite, outcomes = project.junit()
    assert code == minitest.EXIT_FAILED
    assert suite.get("tests") == "3" and suite.get("failures") == "2"
    assert outcomes["test_a::test_markup"] == "failure"
    message = next(c for c in suite.iter("failure") if "script" in c.get("message"))
    assert message.get("message") == "AssertionError: <script>&amp;</script>"
    control = next(c for c in suite.iter("failure") if "bell" in c.get("message"))
    assert (
        control.get("message") == "AssertionError: bell\\x07 escape\\x1b[31m nul\\x00"
    )


# ---------------------------------------------------------------- vs pytest


def test_same_outcomes_as_pytest(project):
    """Differential test: plain-assert tests must get pytest's verdicts."""
    project.write(
        "test_diff.py",
        """
        def test_pass(): assert 1 + 1 == 2
        def test_fail(): assert [1, 2] == [1, 3]
        def test_error_in_code(): {}["missing"]
        class TestGroup:
            def test_pass(self): assert "a" in "abc"
            def test_fail(self): assert None
        """,
    )
    _, _, ours = project.junit()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--junitxml=py.xml",
        ],
        cwd=project.path,
        capture_output=True,
        check=False,
    )
    theirs = {}
    for case in ET.parse(project.path / "py.xml").getroot().iter("testcase"):
        kind = next(
            (child.tag for child in case if child.tag != "system-out"), "passed"
        )
        theirs[f"{case.get('classname')}::{case.get('name')}"] = kind
    assert ours == theirs


def test_runs_as_a_script_with_its_own_imports(tmp_path):
    """As a script, minitest is __main__: test files must still share its registry."""
    (tmp_path / "test_a.py").write_text(
        "from minitest import fixture\n@fixture\ndef x():\n    return 1\n"
        "def test_x(x):\n    assert x == 1\n"
    )
    result = subprocess.run(
        [sys.executable, str(HERE / "minitest.py"), "."],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(HERE)},
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
