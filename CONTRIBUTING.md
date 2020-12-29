# Development guide

This document is intended for developers only.

## Testing

Write unit tests as functions without arguments prefixed with ``_unittest_``;
optionally, for slow test functions use the prefix ``_unittest_slow_``.
Generally, simple test functions should be located as close as possible to the tested code,
preferably at the end of the same Python module.

The directory `tests/deps` contains various test dependencies, including `sitecustomize.py`,
which is used to automatically enable code coverage measurement.
Therefore, when running tests, ensure that the deps directory is in your `PYTHONPATH`.

## Tools

We recommend the [JetBrains PyCharm](https://www.jetbrains.com/pycharm/) IDE for development.

The test suite stores generated DSDL packages into a directory named ``.dsdl_generated``
under the project root directory.
Make sure to mark it as a source directory to enable code completion and type analysis in the IDE
(for PyCharm: right click -> Mark Directory As -> Sources Root).

Configure the IDE to run Black on save.
See the Black documentation for integration instructions.

## Releasing

The tool is versioned by following `Semantic Versioning <https://semver.org>`_.

For all commits pushed to master, the CI/CD pipeline automatically uploads a new release to PyPI
and pushes a new tag upstream.
It is therefore necessary to ensure that the library version (see ``yakut/VERSION``) is bumped whenever
a new commit is merged into master;
otherwise, the automation will fail with an explicit tag conflict error instead of deploying the release.
