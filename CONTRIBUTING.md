# Development guide

This document is intended for developers only.

## Testing

Write unit tests as functions without arguments prefixed with ``_unittest_``;
optionally, for slow test functions use the prefix ``_unittest_slow_``.
Generally, simple test functions should be located as close as possible to the tested code,
preferably at the end of the same Python module.

The directory `tests/deps` contains various test dependencies, including `sitecustomize.py`,
which is used to measure code coverage in subprocesses (which the test suite spawns a lot of, naturally).

When running tests on GNU/Linux, ensure that the current user is allowed to use `sudo` without an
interactive password prompt.
This is needed for setting up `vcan` interfaces, loading relevant kernel modules, and setting up packet capture.

### Manual testing

Some tools with rich UI are difficult to fully test manually.
These should be validated manually; please find instructions in the corresponding files under `tests/cmd`.

### Using Nox

Install [Nox](https://nox.thea.codes): `pip install nox`

Run the test suite and linters, abort on first failure:

```bash
nox -xs test lint
```

Nox is configured to reuse existing virtualenv to accelerate interactive testing.
If you want to start from scratch, use `clean`:

```bash
nox -s clean
```

## Tools

We recommend [JetBrains PyCharm](https://www.jetbrains.com/pycharm/) for development.

The test suite stores compiled DSDL into `.compiled/` in the current working directory
(when using Nox, the current working directory may be under a virtualenv private directory).
Make sure to mark it as a source directory to enable code completion and type analysis in the IDE
(for PyCharm: right click -> Mark Directory As -> Sources Root).
Alternatively, you can just compile DSDL manually directly in the project root.

Configure the IDE to run Black on save.
See the Black documentation for integration instructions.

## Releasing

The tool is versioned by following [Semantic Versioning](https://semver.org).

For all commits pushed to master, the CI/CD pipeline automatically uploads a new release to PyPI
and pushes a new tag upstream.
It is therefore necessary to ensure that the library version (see ``yakut/VERSION``) is bumped whenever
a new commit is merged into master;
otherwise, the automation will fail with an explicit tag conflict error instead of deploying the release.
