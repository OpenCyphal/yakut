# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import os
import shutil
import pathlib
import nox


ROOT_DIR = pathlib.Path(__file__).resolve().parent
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
        ".*generated",
        "*.egg-info",
        "*.log",
        "*.tmp",
    ]
    for w in wildcards:
        for f in pathlib.Path.cwd().glob(w):
            session.log(f"Removing: {f}")
            shutil.rmtree(f, ignore_errors=True)


@nox.session(python=["3.8", "3.9"])
def test(session):
    session.install("-e", ".")
    session.install(
        "pytest     ~= 6.2",
        "coverage   ~= 5.3",
    )

    os.chdir(session.create_tmp())
    session.log(f"Working directory: {pathlib.Path.cwd()}")
    fn = "setup.cfg"
    (pathlib.Path.cwd() / fn).symlink_to(ROOT_DIR / fn)

    env = {
        "PYTHONPATH": str(DEPS_DIR),
        "PATH": os.pathsep.join([session.env["PATH"], str(DEPS_DIR)]),
    }
    tests = session.posargs or ["yakut", "tests"]
    session.run(
        "pytest",
        *[str(ROOT_DIR / t) for t in tests],
        env=env,
    )

    fail_under = 0 if session.posargs else 90
    session.run("coverage", "combine")
    session.run("coverage", "report", f"--fail-under={fail_under}")
    if session.interactive:
        session.run("coverage", "html")
        report_file = pathlib.Path.cwd().resolve() / "htmlcov" / "index.html"
        session.log(f"COVERAGE REPORT: file://{report_file}")


@nox.session(python=["3.8", "3.9"])
def lint(session):
    session.install(
        "mypy   == 0.790",
        "black  == 20.8b1",
        "pylint == 2.6.0",
    )
    session.run("mypy", "--strict", "yakut", "tests")
    session.run("pylint", "yakut")
    session.run("black", "--check", ".")
