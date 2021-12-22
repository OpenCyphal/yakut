
###This document is intended for developers only.
### Runtime dependencies
Since setup.cfg lists these dependencies.
```
pip install click "ruamel.yaml<0.18" simplejson~=3.17 requests~=2.25 click~=7.1 psutil~=5.8 scipy~=1.6 coloredlogs~=15.0
```


## Writing tests

Write unit tests as functions without arguments prefixed with ``_unittest_``;
optionally, for slow test functions use the prefix ``_unittest_slow_``.
Generally, simple test functions should be located as close as possible to the tested code,
preferably at the end of the same Python module.

## Being able to run tests

### Installable dependencies

Install [Nox](https://nox.thea.codes): `pip install nox`

Install ncat ([Netcat](https://nmap.org/ncat/)): `sudo apt install ncat`

### Restrictions to running on your computer

When running tests on GNU/Linux, ensure either that the current user is allowed to use `sudo` without an
interactive password prompt or when you're around, you can also enter the password when prompted.
This is needed for setting up `vcan` interfaces, loading relevant kernel modules, and setting up packet capture.

### Mypy inspections
#### Having mypy analyze the code without running the whole test suite

The test suite should pass and one part of it is the mypy code analysis that takes place at the end of the execution of the long test suite.


1. Be in the yakut root directory
2. Run the long test suite once with ```nox``` 
3. Change directory to ```.nox/test-3-8/tmp```
4. This is one of the environments that nox creates for testing
5. Run ```source ../bin/activate``` to activate the virtualenv
6. ```export PYTHONPATH=.compiled/```
7. mypy --strict /home/silver/zubax/yakut/yakut /home/silver/zubax/yakut/tests
## A manual test

One test can be performed manually, it is located: https://github.com/UAVCAN/yakut/blob/a6ad0fdd9667d894434e00b6c751b2bd7345f684/tests/cmd/monitor.py#L340-L362
in the `tests/cmd` directory, `monitor.py` file, starting on line 340. It is not automated because 

## Releasing

The tool is versioned by following [Semantic Versioning](https://semver.org).

For all commits pushed to master, the CI/CD pipeline automatically uploads a new release to PyPI
and pushes a new tag upstream.
It is therefore necessary to ensure that the library version (see ``yakut/VERSION``) is bumped whenever
a new commit is merged into master;
otherwise, the automation will fail with an explicit tag conflict error instead of deploying the release.

### Code coverage
The directory `tests/deps` contains various test dependencies, including `sitecustomize.py`,
which is used to measure code coverage in the many subprocesses that are spawned.


### The useful nox command

Run the test suite and linters, abort on first failure:

```bash
nox -xs test lint
```
### The nox clean command
Here, Nox is configured to reuse existing virtualenv to accelerate interactive testing.
If you want to start from scratch, use `clean`:

```bash
nox -s clean
```
## Using JetBrains PyCharm

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

