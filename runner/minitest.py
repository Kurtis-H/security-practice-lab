"""minitest: a small test runner written from scratch, to show how pytest-style
runners work inside. No dependencies beyond the standard library.

    python minitest.py [PATH ...] [--junit FILE] [-k TEXT] [-x]

What it does:
  * discovery: test_*.py files, test_* functions, Test* classes' test_* methods
  * fixtures: @fixture functions injected by parameter name, can use other
    fixtures, "function" or "session" scope, teardown after a yield
  * @parametrize, @skip, @skip_if, @xfail and raises()
  * plain assert, with the failing line and local values in the report
  * JUnit XML for CI, and pytest's exit codes:
    0 all passed, 1 a test failed, 2 interrupted or a file failed to import,
    4 usage error, 5 no tests collected
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import re
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EXIT_OK, EXIT_FAILED, EXIT_INTERRUPTED, EXIT_USAGE, EXIT_NO_TESTS = 0, 1, 2, 4, 5

# ---------------------------------------------------------------- decorators

_FIXTURES: dict[str, Fixture] = {}


@dataclass
class Fixture:
    name: str
    func: Callable[..., Any]
    scope: str


def fixture(func: Callable | None = None, *, scope: str = "function"):
    """Register a fixture. Tests ask for it by naming a parameter after it."""
    if scope not in ("function", "session"):
        raise ValueError(f"unknown fixture scope {scope!r}")

    def register(f: Callable) -> Callable:
        _FIXTURES[f.__name__] = Fixture(f.__name__, f, scope)
        return f

    return register(func) if func else register


def parametrize(names: str, values: list):
    """Run the test once per value. Stacking multiplies the cases."""
    keys = [n.strip() for n in names.split(",")]

    def mark(f: Callable) -> Callable:
        rows = [v if len(keys) > 1 else (v,) for v in values]
        for row in rows:
            if len(row) != len(keys):
                raise ValueError(f"{f.__name__}: {row!r} doesn't match {names!r}")
        f.__dict__.setdefault("_params", []).insert(0, (keys, rows))
        return f

    return mark


def skip(reason: str = ""):
    return skip_if(True, reason)


def skip_if(condition: bool, reason: str = ""):
    def mark(f: Callable) -> Callable:
        if condition:
            f._skip = reason or "skipped"
        return f

    return mark


def xfail(reason: str = ""):
    """Expected to fail. If it passes, that's reported as a failure (strict)."""

    def mark(f: Callable) -> Callable:
        f._xfail = reason or "expected failure"
        return f

    return mark


@contextmanager
def raises(expected: type[BaseException], match: str | None = None) -> Iterator[None]:
    try:
        yield
    except expected as error:
        if match is not None and match not in str(error):
            raise AssertionError(f"{error!r} doesn't contain {match!r}") from error
        return
    raise AssertionError(f"did not raise {expected.__name__}")


# ---------------------------------------------------------------- collection


@dataclass
class Case:
    id: str  # tests/test_x.py::TestY::test_z[1-2]
    file: Path
    func: Callable
    owner: type | None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Result:
    case_id: str
    outcome: str  # passed, failed, error, skipped, xfailed
    seconds: float = 0.0
    message: str = ""
    details: str = ""


def find_files(paths: list[Path]) -> list[Path]:
    """conftest.py files first (shared fixtures), then the test files."""
    conftests: list[Path] = []
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
            continue
        for p in sorted(path.rglob("*.py")):
            if any(part.startswith(".") or part == "__pycache__" for part in p.parts):
                continue
            if p.name == "conftest.py":
                conftests.append(p)
            elif p.name.startswith("test_"):
                files.append(p)
    return conftests + files


def load_module(path: Path):
    name = "minitest_" + "_".join(path.with_suffix("").parts[-3:])
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # pickle, dataclasses and typing look modules up here
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


def expand(func: Callable) -> list[tuple[str, dict[str, Any]]]:
    """Every combination of the test's @parametrize lists, with a readable id."""
    combos: list[tuple[str, dict[str, Any]]] = [("", {})]
    for keys, rows in getattr(func, "_params", []):
        combos = [
            (
                f"{cid}-{'-'.join(map(_id_part, row))}"
                if cid
                else "-".join(map(_id_part, row)),
                {**params, **dict(zip(keys, row))},
            )
            for cid, params in combos
            for row in rows
        ]
    return combos


def _id_part(value: Any) -> str:
    if isinstance(value, (int, float, bool, type(None))):
        return str(value)
    if isinstance(value, str) and value.isprintable() and len(value) <= 20:
        return value
    return type(value).__name__


def collect(path: Path, module, root: Path) -> list[Case]:
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = path.as_posix()
    found: list[tuple[str, Callable, type | None]] = []
    for name, obj in vars(module).items():
        if name.startswith("test_") and inspect.isfunction(obj):
            found.append((name, obj, None))
        elif name.startswith("Test") and inspect.isclass(obj):
            for method_name, method in vars(obj).items():
                if method_name.startswith("test_") and inspect.isfunction(method):
                    found.append((f"{name}::{method_name}", method, obj))
    cases = []
    for name, func, owner in found:
        for suffix, params in expand(func):
            case_id = f"{rel}::{name}" + (f"[{suffix}]" if suffix else "")
            cases.append(Case(case_id, path, func, owner, params))
    return cases


# ---------------------------------------------------------------- running


class FixtureError(Exception):
    pass


class Fixtures:
    """Builds fixture values on demand and tears them down in reverse order."""

    def __init__(self, session_cache: dict, session_teardowns: list):
        self.session_cache = session_cache
        self.session_teardowns = session_teardowns
        self.cache: dict[str, Any] = {}
        self.teardowns: list[Iterator] = []

    def get(self, name: str, chain: tuple[str, ...] = ()) -> Any:
        if name in chain:
            raise FixtureError(f"fixture cycle: {' -> '.join(chain + (name,))}")
        if name not in _FIXTURES:
            raise FixtureError(f"fixture {name!r} not found")
        fx = _FIXTURES[name]
        cache = self.session_cache if fx.scope == "session" else self.cache
        if name in cache:
            return cache[name]
        kwargs = {
            arg: self.get(arg, chain + (name,))
            for arg in inspect.signature(fx.func).parameters
        }
        if fx.scope == "session" and any(
            _FIXTURES[a].scope == "function" for a in kwargs
        ):
            raise FixtureError(f"session fixture {name!r} can't use a function fixture")
        value = fx.func(**kwargs)
        if inspect.isgenerator(value):
            generator = value
            value = next(generator)
            (
                self.session_teardowns if fx.scope == "session" else self.teardowns
            ).append(generator)
        cache[name] = value
        return value

    def close(self) -> str:
        return _finish(self.teardowns)


def _finish(generators: list[Iterator]) -> str:
    """Run teardowns, newest first. Returns any error text."""
    errors = []
    while generators:
        generator = generators.pop()
        try:
            next(generator)
        except StopIteration:
            continue
        except Exception:  # noqa: BLE001 - a runner must catch everything a test raises
            errors.append(traceback.format_exc())
        else:
            errors.append(f"fixture {generator.__name__} yielded twice")
    return "\n".join(errors)


def _describe_failure(error: BaseException) -> tuple[str, str]:
    """A one-line message, plus the failing line and its local values."""
    tb = error.__traceback__
    frames = traceback.extract_tb(tb)
    while tb and tb.tb_next:
        tb = tb.tb_next
    message = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
    if not frames:
        return message, ""
    last = frames[-1]
    lines = [f"{last.filename}:{last.lineno}", f"    {last.line}"]
    if tb is not None:
        used = set(re.findall(r"[A-Za-z_]\w*", last.line or ""))  # whole names only
        for name, value in tb.tb_frame.f_locals.items():
            if not name.startswith("__") and name in used:
                lines.append(f"    {name} = {_short_repr(value)}")
    return message, "\n".join(lines)


def _short_repr(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 120 else text[:117] + "..."


def run_case(case: Case, session_cache: dict, session_teardowns: list) -> Result:
    func = case.func
    if hasattr(func, "_skip"):
        return Result(case.id, "skipped", message=func._skip)
    fixtures = Fixtures(session_cache, session_teardowns)
    started = time.perf_counter()
    outcome, message, details = "passed", "", ""
    try:
        wanted = [p for p in inspect.signature(func).parameters if p != "self"]
        kwargs = {
            p: case.params[p] if p in case.params else fixtures.get(p) for p in wanted
        }
        target = getattr(case.owner(), func.__name__) if case.owner else func
    except Exception as error:  # noqa: BLE001 - a runner must catch everything a test raises
        outcome, message = "error", f"setup failed: {error}"
        details = traceback.format_exc()
    else:
        try:
            target(**kwargs)
        except KeyboardInterrupt:
            raise
        except Exception as error:  # noqa: BLE001 - a runner must catch everything a test raises
            if hasattr(func, "_xfail"):
                outcome, message = "xfailed", func._xfail
            else:
                outcome = "failed"
                message, details = _describe_failure(error)
        else:
            if hasattr(func, "_xfail"):
                outcome, message = "failed", f"passed, but marked xfail: {func._xfail}"
    teardown_error = fixtures.close()
    if teardown_error and outcome != "error":
        outcome, message, details = "error", "teardown failed", teardown_error
    return Result(case.id, outcome, time.perf_counter() - started, message, details)


# ---------------------------------------------------------------- reporting


# XML 1.0 can't hold most control characters, even escaped. One "\x1b" from
# coloured output in an assert message would make the whole report unreadable.
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _xml_safe(text: str) -> str:
    return _NOT_XML.sub(lambda m: f"\\x{ord(m.group()):02x}", text)


def write_junit(results: list[Result], path: Path, seconds: float) -> None:
    counts = _count(results)
    suite = ET.Element(
        "testsuite",
        name="minitest",
        tests=str(len(results)),
        failures=str(counts["failed"]),
        errors=str(counts["error"]),
        skipped=str(counts["skipped"] + counts["xfailed"]),
        time=f"{seconds:.3f}",
    )
    for result in results:
        file_part, _, name = result.case_id.partition("::")
        classname = file_part.removesuffix(".py").replace("/", ".")
        if "::" in name:
            cls, _, name = name.partition("::")
            classname += "." + cls
        case = ET.SubElement(
            suite,
            "testcase",
            classname=classname,
            name=name,
            time=f"{result.seconds:.3f}",
        )
        if result.outcome in ("failed", "error"):
            tag = "failure" if result.outcome == "failed" else "error"
            element = ET.SubElement(case, tag, message=_xml_safe(result.message))
            element.text = _xml_safe(result.details)
        elif result.outcome in ("skipped", "xfailed"):
            ET.SubElement(case, "skipped", message=_xml_safe(result.message))
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _count(results: list[Result]) -> dict[str, int]:
    counts = dict.fromkeys(("passed", "failed", "error", "skipped", "xfailed"), 0)
    for result in results:
        counts[result.outcome] += 1
    return counts


MARKS = {"passed": ".", "failed": "F", "error": "E", "skipped": "s", "xfailed": "x"}


def main(argv: list[str] | None = None, out=None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="minitest", description="A tiny test runner.")
    # A list default skips type=, so it must already be Paths.
    parser.add_argument("paths", nargs="*", default=[Path(".")], type=Path)
    parser.add_argument("--junit", type=Path, help="write JUnit XML here")
    parser.add_argument(
        "-k", dest="keyword", help="only run tests whose id contains this"
    )
    parser.add_argument(
        "-x", "--exitfirst", action="store_true", help="stop at first failure"
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return EXIT_OK if exit_.code == 0 else EXIT_USAGE
    missing = [str(p) for p in args.paths if not p.exists()]
    if missing:
        print(f"minitest: no such path: {', '.join(missing)}", file=out)
        return EXIT_USAGE

    # Run as a script, this file is __main__. Test files that import minitest
    # must get this same module, or their @fixture calls fill a second registry.
    sys.modules.setdefault("minitest", sys.modules[__name__])
    _FIXTURES.clear()
    started = time.perf_counter()
    root = Path.cwd()
    cases: list[Case] = []
    import_errors: list[str] = []
    for path in find_files(args.paths):
        try:
            module = load_module(path)
        except Exception:  # noqa: BLE001 - a runner must catch everything a test raises
            import_errors.append(f"{path}: failed to import\n{traceback.format_exc()}")
            continue
        if path.name != "conftest.py":
            cases.extend(collect(path, module, root))
    if args.keyword:
        cases = [c for c in cases if args.keyword in c.id]
    for error in import_errors:
        print("ERROR " + error, file=out)
    if import_errors:
        return EXIT_INTERRUPTED
    if not cases:
        print("minitest: no tests collected", file=out)
        return EXIT_NO_TESTS

    session_cache: dict[str, Any] = {}
    session_teardowns: list[Iterator] = []
    results: list[Result] = []
    interrupted = False
    try:
        for case in cases:
            result = run_case(case, session_cache, session_teardowns)
            results.append(result)
            out.write(MARKS[result.outcome])
            out.flush()
            if args.exitfirst and result.outcome in ("failed", "error"):
                break
    except KeyboardInterrupt:
        interrupted = True
    session_error = _finish(session_teardowns)
    if session_error:
        results.append(
            Result("<session teardown>", "error", 0, "teardown failed", session_error)
        )
    seconds = time.perf_counter() - started
    print(file=out)

    for result in results:
        if result.outcome in ("failed", "error"):
            print(
                f"\n{result.outcome.upper()} {result.case_id}\n  {result.message}",
                file=out,
            )
            if result.details:
                print("  " + result.details.replace("\n", "\n  "), file=out)
    counts = _count(results)
    summary = ", ".join(f"{n} {k}" for k, n in counts.items() if n)
    print(f"\n{summary} in {seconds:.2f}s", file=out)
    if args.junit:
        write_junit(results, args.junit, seconds)
    if interrupted:
        return EXIT_INTERRUPTED
    return EXIT_FAILED if counts["failed"] or counts["error"] else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
