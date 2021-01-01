# Yakut

[![Build status](https://ci.appveyor.com/api/projects/status/knl63ojynybi3co6/branch/main?svg=true)](https://ci.appveyor.com/project/Zubax/yakut/branch/main)
[![PyPI - Version](https://img.shields.io/pypi/v/yakut.svg)](https://pypi.org/project/yakut/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Forum](https://img.shields.io/discourse/users.svg?server=https%3A%2F%2Fforum.uavcan.org&color=1700b3)](https://forum.uavcan.org)

Yakút is a simple cross-platform command-line interface (CLI) tool for diagnostics and debugging of
[UAVCAN](https://uavcan.org) networks.
By virtue of being based on [PyUAVCAN](https://github.com/UAVCAN/pyuavcan),
Yakut supports all UAVCAN transports (UDP, serial, CAN, ...)
and is compatible with all major features of the protocol.
It is designed to be usable with GNU/Linux, Windows, and macOS.

Ask questions and get assistance at [forum.uavcan.org](https://forum.uavcan.org/).

## Installing

First, make sure to [have Python installed](https://docs.python.org/3/using/index.html).
Windows users are recommended to grab the official distribution from Windows Store.

Install Yakut: **`pip install yakut`**

Afterward do endeavor to read the docs: **`yakut --help`**

Check for new versions every now and then: **`pip install --upgrade yakut`**

## Invoking commands

Any option can be supplied either as a command-line argument or as an environment variable named like
`YAKUT_[subcommand_]option`.
If both are provided, command-line options take precedence over environment variables.
You can use this feature to configure desired defaults by exporting environment variables from the
rc-file of your shell (for bash/zsh this is `~/.bashrc`/`~/.zshrc`, for PowerShell see `$profile`).

Options for the main command shall be specified before the subcommand when invoking Yakut:

```bash
yakut --path=/the/path compile path/to/my_namespace --output=destination/directory
```

In this example, the corresponding environment variables are `YAKUT_PATH` and `YAKUT_COMPILE_OUTPUT`.

Any subcommand like `yakut compile` can be used in an abbreviated form like `yakut com`
as long as the resulting abbreviation is unambiguous.

There is a dedicated `--help` option for every subcommand.

## Compiling DSDL

Suppose we have our custom DSDL namespace that we want to use.
First, it needs to be *compiled*:

```bash
yakut compile ~/custom_data_types/sirius_cyber_corp
```

Some commands require the standard namespace to be available,
so let's compile it too, along with the regulated namespace:

```bash
yakut compile  ~/public_regulated_data_types/uavcan  ~/public_regulated_data_types/reg
```

Compilation outputs will be stored in the current working directory, but it can be overridden if needed
via `--output` or `YAKUT_COMPILE_OUTPUT`.
Naturally, Yakut needs to know where the outputs are located to use them;
by default it looks in the current directory.
You can specify additional search locations using `--path` or`YAKUT_PATH`.

A question one is likely to ask here is:
*Why don't you ship precompiled regulated DSDL together with the tool?*
Indeed, that would be trivial to do, but we avoid that on purpose to emphasize our commitment to
supporting vendor-specific and regulated DSDL at the same level.
In the past we used to give regulated namespaces special treatment,
which caused our users to acquire misconceptions about the purpose of DSDL.
Specifically, there have been forks of the standard namespace extended with vendor-specific types,
which is harmful to the ecosystem.

Having to manually compile the regulated namespaces is not an issue because it is just a single command to run.
You may opt to keeping compiled namespaces that you use often somewhere in a dedicated directory and put
`YAKUT_PATH=/your/directory` into your shell's rc-file so that you don't have to manually specify
the path when invoking Yakut.
Similarly, you can configure it to use that directory as the default destination for compiled DSDL:

```bash
# bash/zsh on GNU/Linux or macOS
export YAKUT_COMPILE_OUTPUT=~/.yakut
export YAKUT_PATH="$YAKUT_COMPILE_OUTPUT"
```

```powershell
# PowerShell on Windows
$env:YAKUT_COMPILE_OUTPUT="$env:APPDATA\Yakut"
$env:YAKUT_PATH="$env:YAKUT_COMPILE_OUTPUT"
```

So that you say simply `yakut compile path/to/my_namespace`
knowing that the outputs will be always stored to and read from a fixed place unless you override it.

## Communicating

Commands that access the network need to know how to do so.
This is configured by providing a *transport initialization expression* via `--transport`/`YAKUT_TRANSPORT`.
Here are practical examples (don't forget to add quotes around the expression):

- `UDP("127.0.0.1",anonymous=True)` -- UAVCAN/UDP on the local loopback interface; local node anonymous.

- `UDP("192.168.1.200")` -- UAVCAN/UDP on the local network; local node-ID 456.

- `Serial('/dev/ttyUSB0',None)` -- UAVCAN/serial over a USB CDC ACM port; local node anonymous.

- `Serial('socket://localhost:50905',123)` -- UAVCAN/serial tunneled via TCP/IP instead of a real serial port.
  The local node-ID is 123.

- `CAN(can.media.socketcan.SocketCANMedia('vcan1',32),3),CAN(can.media.socketcan.SocketCANMedia('vcan2',64),3)` --
  UAVCAN/CAN over a doubly-redundant CAN FD bus using a virtual (simulated) SocketCAN interface.
  The node-ID is 3, and the MTU is 32/64 bytes, respectively.

- `Loopback(2222)` -- A null-transport for testing with node-ID 2222.

To learn more, read `yakut --help`.
If there is a particular transport you use often,
consider configuring it as the default via environment variables as shown earlier.

Next there are practical examples (configuring the transport is left as an exercise to the reader).

### Publishing messages

Publishing two messages synchronously twice (four messages total);
notice how we specify the subject-ID before the data type name:

```bash
yakut pub 33.uavcan.si.unit.angle.Scalar.1.0 'radian: 2.31' uavcan.diagnostic.Record.1.1 'text: "2.31 rad"' -N2
```

We did not specify the subject-ID for the second subject, so Yakut defaulted to the fixed subject-ID.

### Subscribing to subjects

Subscribe to subject 33 of type `uavcan.si.unit.angle.Scalar.1.0`
to receive messages published by the above command:

```bash
$ yakut sub 33.uavcan.si.unit.angle.Scalar.1.0
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

### Invoking RPC-services

Given custom data types:

```shell
# sirius_cyber_corp.PerformLinearLeastSquaresFit.1.0
PointXY.1.0[<64] points
@extent 1024 * 8
---
float64 slope
float64 y_intercept
@sealed
```

```shell
# sirius_cyber_corp.PointXY.1.0
float16 x
float16 y
@sealed
```

Suppose that there is node 42 that serves `sirius_cyber_corp.PerformLinearLeastSquaresFit.1.0` at service-ID 123:

```bash
$ yakut compile sirius_cyber_corp
$ yakut call 42 123.sirius_cyber_corp.PerformLinearLeastSquaresFit.1.0 'points: [{x: 10, y: 1}, {x: 20, y: 2}]'
---
123:
  slope: 0.1
  y_intercept: 0.0
```
