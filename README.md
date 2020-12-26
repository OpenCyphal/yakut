# U-tool

[![AppVeyor CI](https://ci.appveyor.com/api/projects/status/2vv83afj3dxqibi5?svg=true)](https://ci.appveyor.com/project/Zubax/u)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=UAVCAN_u&metric=alert_status)](https://sonarcloud.io/dashboard?id=UAVCAN_u)
[![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=UAVCAN_u&metric=reliability_rating)](https://sonarcloud.io/dashboard?id=UAVCAN_u)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/u.svg)](https://pypi.org/project/u/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Forum](https://img.shields.io/discourse/users.svg?server=https%3A%2F%2Fforum.uavcan.org&color=1700b3)](https://forum.uavcan.org)

**`u`** is a simple cross-platform command-line interface (CLI) tool for diagnostics and debugging of
[UAVCAN](https://uavcan.org) networks.
By virtue of being based on [PyUAVCAN](https://github.com/UAVCAN/pyuavcan),
the U-tool supports all UAVCAN transports (UDP, serial, CAN, ...)
and is compatible with all major features of the protocol.
It is designed to be usable with GNU/Linux, Windows, and macOS.

Ask questions and get assistance at [forum.uavcan.org](https://forum.uavcan.org/).

## Install

If you are on Windows,
[make sure to have Python installed](https://devblogs.microsoft.com/python/python-in-the-windows-10-may-2019-update/).

Install the U-tool: **`pip install u`**

Afterward do endeavor to read the docs: **`u --help`**

Check for new versions every now and then: **`pip install -U u`**

## Use

Suppose we have our custom DSDL namespace that we want to use.
First, it needs to be *compiled*:

```bash
u comp ~/custom_data_types/sirius_cyber_corp
```

`comp` means `compile` -- you can shorten commands arbitrarily as long as the resulting abbreviation is unambiguous.

Some commands require the standard namespace to be available,
so let's compile it too, along with the regulated namespace:

```bash
u comp  ~/public_regulated_data_types/uavcan  ~/public_regulated_data_types/reg
```

Compilation outputs will be stored in the current working directory, but it can be overridden if needed.
Naturally, the U-tool needs to know where the outputs are located to use them;
by default it looks in the current directory.
You can specify additional search locations using `--path` or the environment variable `U_PATH`.

In general, any option can be supplied either as a command-line argument or as an environment variable
prefixed with `U_`.
For instance, `--foo-bar` and `U_FOO_BAR` are interchangeable, but the former takes precedence.

Commands that access the network need to know how to do so.
This is configured using the option `--transport`/`U_TRANSPORT`.
Assuming that we use the UDP transport on the local loopback interface,
we could say something like this, depending on which shell/OS you're on:

```bash
# bash/sh/zsh
export U_TRANSPORT='UDP("127.0.0.1",anonymous=True)'
```

```powershell
# PowerShell
$env:U_TRANSPORT="UDP('127.0.0.1',anonymous=True)"
```

You are probably wondering what transports are available and how to use them.
For that, run `u doc --help`.

Suppose that there is a node 42 that serves `sirius_cyber_corp.PerformLinearLeastSquaresFit.1.0` at service-ID 123.
We can invoke it as follows (configuring the transport is left as an exercise to the reader):

```bash
$ u call 42 123.sirius_cyber_corp.PerformLinearLeastSquaresFit.1.0 'points: [{x: 10, y: 1}, {x: 20, y: 2}]'
---
123:
  slope: 0.1
  y_intercept: 0.0
```

Publishing messages -- notice how we specify the subject-ID before the data type name:

```bash
u pub 33.uavcan/si/unit/angle/Scalar_1_0 'radian: 2.31' uavcan.diagnostic.Record.1.1 'text: "2.31 rad"' -N2
```

We did not specify the subject-ID for the second subject, so the U-tool defaulted to the fixed subject-ID.

Notice that the first subject uses a different notation, with `/` and `_` instead of `.`.
This is supported for convenience because it allows you to type data type names very quickly relying on the
standard filesystem tab completion (assuming that your data types are in the current working directory).

Subscribing to subjects is done similarly:

```bash
$ u sub 33.uavcan.si.unit.angle.Scalar.1.0
---
33:
  _metadata_:
    timestamp:
      system: 1608987583.298886
      monotonic: 788272.540747
    priority: nominal
    transfer_id: 0
    source_node_id: 42
  radian: 2.309999942779541

---
33:
  _metadata_:
    timestamp:
      system: 1608987583.298886
      monotonic: 788272.540747
    priority: nominal
    transfer_id: 1
    source_node_id: 42
  radian: 2.309999942779541
```
