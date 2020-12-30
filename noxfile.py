# Copyright (c) 2020 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import os
import pathlib
import nox


PYTHONS = ["3.8", "3.9"]

ROOT_DIR = pathlib.Path(__file__).resolve().parent
DEPS_DIR = ROOT_DIR / "tests" / "deps"
assert DEPS_DIR.is_dir(), "Invalid configuration"


@nox.session(python=PYTHONS)
def test(session):
    session.install("-e", ".")
    session.install(
        "pytest     ~= 6.2",
        "coverage   ~= 5.3",
    )

    os.chdir(session.create_tmp())
    session.log(f"Working directory: {pathlib.Path.cwd()}")

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