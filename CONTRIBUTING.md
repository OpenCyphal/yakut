# Development guide

This document is intended for developers only.

## Testing

Install dependencies into your current Python environment: `pip install .`
Aside from that, you will need to install other dependencies listed in the CI/CD workflow files
(e.g., [Ncat](https://nmap.org/ncat/); for Debian-based distros try `apt install ncat`).

Write unit tests as functions without arguments prefixed with ``_unittest_``;
optionally, for slow test functions use the prefix ``_unittest_slow_``.
Generally, simple test functions should be located as close as possible to the tested code,
preferably at the end of the same Python module.

The directory `tests/deps` contains various test dependencies, including `sitecustomize.py`,
which is used to measure code coverage in subprocesses (which the test suite spawns a lot of, naturally).

When running tests on GNU/Linux, ensure either that the current user is allowed to use `sudo` without an
interactive password prompt; or, when you're around, you can also enter the password when prompted.
This is needed for setting up `vcan` interfaces, loading relevant kernel modules, and setting up packet capture.

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

#### Running tests/linters selectively from a virtual environment created by Nox

Running the full test suite using Nox takes too much time for interactive testing during development.
A more interactive approach is as follows:

1. Be in the yakut root directory.
2. Run the long test session once with `nox`.
3. Change directory to `.nox/test-3-8/tmp`, here substitute `test-3-8` for the directory you have. 
   This is one of the environments that Nox creates for testing.
4. Run `source ../bin/activate` to activate the virtualenv.
5. `export PYTHONPATH=.compiled/`
6. Run specific commands you need:
   `pytest ../../../yakut/whatever`, `mypy --strict ../../../yakut ../../../tests`, etc.

When you want to run say unit tests at the end of the `yakut/param/formatter.py` file:

1. Make sure `nox` has been run before, this creates the test environment(s).
2. Activate one of the nox test environments like `source .nox/test-3-8/bin/activate`
3. `pytest yakut/param/formatter.py`

### Manual testing

Some tools with rich UI are difficult to test automatically.
To look for manual tests in the codebase, please search for `def _main` under `tests/`.

## Tools

We recommend [JetBrains PyCharm](https://www.jetbrains.com/pycharm/) for development.

The test suite stores compiled DSDL into `.compiled/` in the current working directory
(when using Nox, the current working directory may be under a virtualenv private directory).
Make sure to mark it as a source directory to enable code completion and type analysis in the IDE
(for PyCharm: right click -> Mark Directory As -> Sources Root).
Alternatively, you can just compile DSDL manually directly in the project root.

Configure the IDE to run Black on save.
See the Black documentation for integration instructions.

### Capturing video for documentation

Capture desktop region:

```bash
ffmpeg -video_size 1920x1500 -framerate 10 -f x11grab -i :0.0+3840,117 output.mp4 -y
```

Convert captured video to GIF:

```bash
ffmpeg -i output.mp4 output.gif
```

Stream webcam via MJPEG using VLC (open the stream using web browser or VLC):

```bash
cvlc v4l2:///dev/video0 :chroma=mjpg :live-caching=10 --sout '#transcode{vcodec=mjpg}:std{access=http{mime=multipart/x-mixed-replace;boundary=-7b3cc56e5f51db803f790dad720ed50a},mux=mpjpeg,dst=0.0.0.0:8080}' --network-caching=0
```

## Releasing

The tool is versioned by following [Semantic Versioning](https://semver.org).

For all commits pushed to master, the CI/CD pipeline automatically uploads a new release to PyPI
and pushes a new tag upstream.
It is therefore necessary to ensure that the library version (see ``yakut/VERSION``) is bumped whenever
a new commit is merged into master;
otherwise, the automation will fail with an explicit tag conflict error instead of deploying the release.
