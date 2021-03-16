# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>
# type: ignore

import os
import sys
import shutil
from pathlib import Path
import nox


ROOT_DIR = Path(__file__).resolve().parent
DEPS_DIR = ROOT_DIR / "tests" / "deps"
assert DEPS_DIR.is_dir(), "Invalid configuration"


@nox.session(python=False)
def clean(session):
    wildcards = [
        "dist",
        "build",
        "htmlcov",
        ".coverage*",
        ".*cache",
        ".*compiled",
        "*.egg-info",
        "*.log",
        "*.tmp",
        ".nox",
    ]
    for w in wildcards:
        for f in Path.cwd().glob(w):
            session.log(f"Removing: {f}")
            shutil.rmtree(f, ignore_errors=True)


@nox.session(python=["3.8", "3.9"], reuse_venv=True)
def test(session):
    # First, while the environment is clean, install just the tool alone and ensure that it is minimally functional.
    # This is needed to catch errors caused by accidental reliance on test dependencies in the main codebase.
    # Also in this way we validate that the executable entry points are configured and installed correctly.
    session.install("-e", ".")
    session.run_always("yakut", "--help", silent=True)
    session.run_always("yakut", "doc", silent=True)

    # Now we can install dependencies for the full integration test suite.
    session.install(
        "pytest   ~= 6.2",
        "coverage ~= 5.3",
    )

    # The test suite generates a lot of temporary files, so we change the working directory.
    # We have to symlink the original setup.cfg as well if we run tools from the new directory.
    tmp_dir = Path(session.create_tmp()).resolve()
    os.chdir(tmp_dir)
    session.log(f"Working directory: {Path.cwd()}")
    fn = "setup.cfg"
    if not (tmp_dir / fn).exists():
        (tmp_dir / fn).symlink_to(ROOT_DIR / fn)

    # The directories to test may be overridden if needed when invoking Nox.
    src_dirs = [(ROOT_DIR / t) for t in (session.posargs or ["yakut", "tests"])]

    # Run PyTest and make a code coverage report.
    env = {
        "PYTHONPATH": str(DEPS_DIR),
        "PATH": os.pathsep.join([session.env["PATH"], str(DEPS_DIR)]),
    }
    session.run("pytest", *map(str, src_dirs), env=env)

    # The coverage threshold is intentionally set low for interactive runs because when running locally
    # in a reused virtualenv the DSDL compiler run may be skipped to save time, resulting in a reduced coverage.
    # Some features are not available on Windows so the coverage threshold is set low for it.
    if session.posargs or session.interactive or sys.platform.startswith("win"):
        fail_under = 1
    else:
        fail_under = 90
    session.run("coverage", "combine")
    session.run("coverage", "report", f"--fail-under={fail_under}")
    if session.interactive:
        session.run("coverage", "html")
        report_file = Path.cwd().resolve() / "htmlcov" / "index.html"
        session.log(f"COVERAGE REPORT: file://{report_file}")

    # MyPy has to be run in the same session because:
    #   1. It requires access to the code generated by the test suite.
    #   2. It has to be run separately per Python version we support.
    # If the interpreter is not CPython, this may need to be conditionally disabled.
    session.install("mypy == 0.812")
    session.run("mypy", "--strict", *map(str, src_dirs))


@nox.session(reuse_venv=True)
def lint(session):
    session.install("pylint == 2.6.0")
    session.run("pylint", "yakut", "tests")

    session.install("black == 20.8b1")
    session.run("black", "--check", ".")
