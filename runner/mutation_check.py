"""Mutation check: plant bugs in a copy of minitest; test_runner.py must catch each.

    python mutation_check.py

A test suite that passes is only half the story. This plants one bug at a
time (each a realistic mistake) and fails if any survives the suite.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

src = pathlib.Path(__file__).parent
mutants = {
    "teardown order (pop oldest first)": (
        "generator = generators.pop()",
        "generator = generators.pop(0)",
    ),
    "session fixture not cached": (
        'cache = self.session_cache if fx.scope == "session" else self.cache',
        "cache = self.cache",
    ),
    "xfail not strict": (
        'outcome, message = "failed", f"passed, but marked xfail',
        'outcome, message = "passed", f"passed, but marked xfail',
    ),
    "errors exit 0": (
        'return EXIT_FAILED if counts["failed"] or counts["error"] else EXIT_OK',
        'return EXIT_FAILED if counts["failed"] else EXIT_OK',
    ),
    "no-tests exits 0": ("return EXIT_NO_TESTS", "return EXIT_OK"),
    "raises swallows anything": (
        "    except expected as error:",
        "    except BaseException as error:",
    ),
    "skip ignored": ('if hasattr(func, "_skip"):', "if False:"),
    "-x ignored": (
        "if args.exitfirst and result.outcome",
        "if False and result.outcome",
    ),
    "no XML escaping": ("return _NOT_XML.sub(", "return text or _NOT_XML.sub("),
    "hidden dirs collected": (
        'part.startswith(".") or part == "__pycache__"',
        'part == "__pycache__"',
    ),
    "teardown error hidden": ('if teardown_error and outcome != "error":', "if False:"),
    "cycle check removed": ("if name in chain:", "if False:"),
}
code = (src / "minitest.py").read_text()
survived = []
for name, (old, new) in mutants.items():  # each mutant must match exactly one spot
    assert code.count(old) == 1, name
    with tempfile.TemporaryDirectory() as d:
        shutil.copy(src / "test_runner.py", d)
        pathlib.Path(d, "minitest.py").write_text(code.replace(old, new))
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-x",
                "-p",
                "no:cacheprovider",
                "test_runner.py",
            ],
            cwd=d,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    killed = r.returncode != 0
    print(("killed  " if killed else "SURVIVED"), name)
    if not killed:
        survived.append(name)
print(f"{len(mutants) - len(survived)}/{len(mutants)} killed")
sys.exit(1 if survived else 0)
