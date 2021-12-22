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

<img src="/docs/monitor.png" alt="yakut monitor">

Ask questions and get assistance at [forum.uavcan.org](https://forum.uavcan.org/).

## Installing

First, make sure to [have Python installed](https://docs.python.org/3/using/index.html).
Windows users are recommended to grab the official distribution from Windows Store.
Yakut requires **Python 3.7 or newer**.

Install Yakut: **`pip install yakut`**

By default, Yakut does not support joysticks or MIDI controllers
(this feature is described below in section [Publishing messages](#publishing-messages)).
To enable the support for input devices, install the optional dependency: **`pip install yakut[joystick]`**.
GNU/Linux users will need to also install: [SDL2](https://libsdl.org),
possibly libjack (with headers), possibly libasound2 (with headers).

Afterward do endeavor to read the docs: **`yakut --help`**

Check for new versions every now and then: **`pip install --upgrade yakut`**

Installation & configuration screencasts for Windows and GNU/Linux are
[available on the forum](https://forum.uavcan.org/t/screencast-of-installing-configuring-yakut/1197).

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

Yakut may also be invoked via its alias **`y`** as long as this name does not conflict with another installed program.

## Compiling DSDL

Suppose we have our custom DSDL namespace that we want to use.
First, it needs to be *compiled*:

```bash
yakut compile ~/custom_data_types/sirius_cyber_corp
```

Most of the commands require the standard namespace to be available,
so let's compile it too, along with the regulated namespace:

```bash
yakut compile  ~/public_regulated_data_types/uavcan  ~/public_regulated_data_types/reg
```

Compilation outputs will be stored in the current working directory, but it can be overridden if needed
via `--output` or `YAKUT_COMPILE_OUTPUT`.
Naturally, Yakut needs to know where the outputs are located to use them;
by default it looks in the current directory.
You can specify additional search locations using `--path` or `YAKUT_PATH`.

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
# PowerShell on Windows (double quotes are always required!)
$env:YAKUT_COMPILE_OUTPUT="$env:APPDATA\Yakut"
$env:YAKUT_PATH="$env:YAKUT_COMPILE_OUTPUT"
```

So that you say simply `yakut compile path/to/my_namespace`
knowing that the outputs will be always stored to and read from a fixed place unless you override it.

## Communicating

Commands that access the network need to know how to do so.
There are two ways to configure that:
pass *UAVCAN registers* via environment variables (this is the default),
or pass an initialization expression via `--transport`/`YAKUT_TRANSPORT` (in which case the registers are ignored).
The latter is not recommended for general use so we'll focus on the first one.

UAVCAN registers are named values that contain various configuration parameters of a UAVCAN application/node.
They are extensively described in the [UAVCAN Specification](https://uavcan.org/specification).
When starting a new process, it is possible to pass arbitrary registers via environment variables.

There are certain registers that are looked at by UAVCAN nodes to determine how to connect to the network.
Some of them are given below, but the list is not exhaustive.
The full description of supported registers is available in the API documentation for
[`pyuavcan.application.make_transport()`](https://pyuavcan.readthedocs.io/en/stable/api/pyuavcan.application.html#pyuavcan.application.make_transport).

If the available registers define more than one transport configuration, a redundant transport will be initialized.

 Transport | Register name         | Register type  | Environment variable name | Semantics                                         | Example environment variable value  
-----------|-----------------------|----------------|---------------------------|---------------------------------------------------|-------------------------------------
 All       | `uavcan.node.id`      | `natural16[1]` | `UAVCAN__NODE__ID`        | The local node-ID; anonymous if not set           | `42`                                
 UDP       | `uavcan.udp.iface`    | `string`       | `UAVCAN__UDP__IFACE`      | Space-separated local IPs (16 LSB set to node-ID) | `127.9.0.0 192.168.0.0`             
 Serial    | `uavcan.serial.iface` | `string`       | `UAVCAN__SERIAL__IFACE`   | Space-separated serial port names                 | `COM9 socket://127.0.0.1:50905`     
 CAN       | `uavcan.can.iface`    | `string`       | `UAVCAN__CAN__IFACE`      | Space-separated CAN iface names                   | `socketcan:vcan0 pcan:PCAN_USBBUS1` 
 CAN       | `uavcan.can.mtu`      | `natural16[1]` | `UAVCAN__CAN__MTU`        | Maximum transmission unit; selects Classic/FD     | `64`                                
 CAN       | `uavcan.can.bitrate`  | `natural32[2]` | `UAVCAN__CAN__BITRATE`    | Arbitration/data segment bits per second          | `1000000 4000000`                   
 Loopback  | `uavcan.loopback`     | `bit[1]`       | `UAVCAN__LOOPBACK`        | Use loopback interface (only for basic testing)   | `1`                                 

### Protip on environment variables

Defining the required environment variables manually is unergonomic and time-consuming.
A better option is to have relevant configuration that you use often defined in a dedicated file (or several)
that is sourced into the current shell session as necessary
(conceptually this is similar to virtual environments used in Python, etc).
Here is an example for a doubly-redundant CAN bus (assuming sh/bash/zsh here):

```bash
# Common UAVCAN register configuration for testing & debugging.
# Source this file into your sh/bash/zsh session before using Yakut and other UAVCAN tools.
# Other helpful commands from can-utils:
#   canbusload -tcbr slcan0@1000000 slcan1@1000000
#   candump -decaxta any

export UAVCAN__CAN__IFACE='socketcan:slcan0 socketcan:slcan1'
export UAVCAN__CAN__MTU=8
export UAVCAN__NODE__ID=$(yakut accommodate)  # Pick an unoccupied node-ID automatically for this shell session.
echo "Auto-selected node-ID for this session: $UAVCAN__NODE__ID"
```

Usage:

```bash
$ . my_environment.sh
$ yakut monitor  # Whatever.
```

### Subscribing to subjects

Subscribe to subject 33 of type `uavcan.si.unit.angle.Scalar.1.0` as shown below;
notice how we specify the subject-ID before the data type name.
You will see output if there is a publisher on this subject (more on this in the next section).

```bash
$ export UAVCAN__UDP__IFACE=127.63.0.0
$ yakut sub 33:uavcan.si.unit.angle.Scalar.1.0
---
33:
  _metadata_:
    timestamp: {system: 1608987583.298886, monotonic: 788272.540747}
    priority: nominal
    transfer_id: 0
    source_node_id: 42
  radian: 2.309999942779541

---
33:
  _metadata_:
    timestamp: {system: 1608987583.298886, monotonic: 788272.540747}
    priority: nominal
    transfer_id: 1
    source_node_id: 42
  radian: 2.309999942779541
```

### Publishing messages

Publishing two messages synchronously twice (four messages total):

```bash
export UAVCAN__UDP__IFACE=127.63.0.0
export UAVCAN__NODE__ID=42
yakut pub -N2 33:uavcan.si.unit.angle.Scalar.1.0 'radian: 2.31' \
                 uavcan.diagnostic.Record.1.1    'text: "2.31 rad"'
```

We did not specify the subject-ID for the second subject, so Yakut defaulted to the fixed subject-ID.

The above example will publish constant values which is rarely useful.
You can define arbitrary Python expressions that are evaluated by Yakut before publication.
Such expressions are entered as strings marked with [YAML tag](https://yaml.org/spec/1.2/spec.html#id2761292) `!$`.
There may be an arbitrary number of such expressions in a YAML document,
and their results may be arbitrary as long as the final structure can initialize the specified message.
The following example will publish a sinewave with frequency 1 Hz, amplitude 10 meters:

```bash
yakut pub -T 0.01 1234:uavcan.si.unit.length.Scalar.1.0 '{meter: !$ "sin(t * pi * 2) * 10"}'
```

Notice that we make use of entities like the variable `t` or the standard function `sin` in the expression.
You will see the full list of available entities if you run `yakut pub --help`.

One particularly important capability of this command is the ability to read data from connected
joysticks or MIDI controllers.
It allows the user to control UAVCAN processes or equipment in real time, simulate sensor feeds, etc.
Function `A(x,y)` returns the normalized value of axis `y` from connected controller `x`
(for full details see `yakut pub --help`);
likewise, there is `B(x,y)` for push buttons and `T(x,y)` for toggle switches.
The next example will publish 3D angular velocity setpoint, thrust setpoint, and the arming switch state,
allowing the user to control these parameters interactively:

```bash
yakut pub -T 0.1 \
    5:uavcan.si.unit.angular_velocity.Vector3.1.0 'radian_per_second: !$ "[A(1,0)*10, A(1,1)*10, (A(1,2)-A(1,5))*5]"' \
    6:uavcan.si.unit.power.Scalar.1.0 'watt: !$ A(2,10)*1e3' \
    7:uavcan.primitive.scalar.Bit.1.0 'value: !$ T(1,5)'
```

The list of connected controllers and how their axes are mapped can be seen using `yakut joystick`,
as shown in the video:

[![yakut joystick](https://img.youtube.com/vi/YPr98KM1RFM/maxresdefault.jpg)](https://www.youtube.com/watch?v=YPr98KM1RFM)

Here is an example where a MIDI controller is used to interactively change the frequency and amplitude of a sinewave:

[![yakut publish](https://img.youtube.com/vi/DSsI882ZYh0/maxresdefault.jpg)](https://www.youtube.com/watch?v=DSsI882ZYh0)

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
$ export UAVCAN__UDP__IFACE=127.63.0.0
$ export UAVCAN__NODE__ID=42
$ yakut compile sirius_cyber_corp
$ yakut call 42 123:sirius_cyber_corp.PerformLinearLeastSquaresFit.1.0 'points: [{x: 10, y: 1}, {x: 20, y: 2}]'
---
123:
  slope: 0.1
  y_intercept: 0.0
```

You might notice that the verbose initialization form used in this example is hard to type:
`points: [{x: 10, y: 1}, {x: 20, y: 2}]`.
Instead, you can use positional initialization for convenience: `[[10, 1], [20, 2]]`.

## Monitoring the network

The command `yakut monitor` can be used to display *all* activity on the network in a compact representation.
It tracks online nodes and maintains real-time statistics on all transfers exchanged between each node
on the network.
It may also be able to detect some common network configuration issues like zombie nodes
(nodes that do not publish `uavcan.node.Heartbeat`).

Read `yakut monitor --help` for details.

```bash
$ export UAVCAN__CAN__IFACE="socketcan:can0 socketcan:can1 socketcan:can2"  # Triply-redundant UAVCAN/CAN
$ export UAVCAN__CAN__MTU=8                     # Force MTU = 8 bytes
$ export UAVCAN__CAN__BITRATE="1000000 1000000" # Disable BRS, use the same bit rate for arbitration/data
$ y mon                                         # Abbreviation of "yakut monitor"
```

<img src="/docs/monitor.gif" alt="yakut monitor">

The monitor can be an anonymous node or it can be given a node-ID of its own.
In the latter case it will actively query other nodes using the standard introspection services.

Some transports, UAVCAN/UDP in particular, require special privileges to run this tool due to the security
implications of low-level packet capture.

## Updating node software

The file server command can be used to serve files,
run a plug-and-play node-ID allocator (some embedded bootloader implementations require that),
and automatically send software update requests `uavcan.node.ExecuteCommand` to nodes whose software is old.

To demonstrate this capability, suppose that the network contains the following nodes:

- nodes 1, 2 named `com.example.foo`, software 1.0
- nodes 3, 4 named `com.example.bar`, hardware v4.2, software v3.4
- node 5 named `com.example.baz`

Software updates are distributed as atomic package files.
In case of embedded systems, the package is usually just the firmware image,
possibly compressed or amended with some metadata.
For the file server this is irrelevant since it never looks inside the files it serves.
However, the name is relevant as it shall follow a particular pattern to make the server recognize
the file as a software package.
The full specification is given in the command help: `yakut file-server --help`.

Suppose that we have the following packages that we need to deploy:

- v1.1 for nodes `com.example.foo` with any hardware
- v3.3 for nodes `com.example.bar` with hardware v4.x
- v3.5 for nodes `com.example.bar` with hardware v5.6 only
- nothing for `com.example.baz`

```shell
$ ls *.app*                       # List all software packages
com.example.foo-1.1.app.zip       # Any hardware
com.example.bar-4-3.3.app.pkg     # Hardware v4.x
com.example.bar-5.6-3.5.app.bin   # Hardware v5.6 only
```

The server rescans its root directory whenever a new node is found online,
meaning that packages can be added/removed at runtime and the server will pick up the changes on the fly.
Launch the server:

```shell
$ export UAVCAN__UDP__IFACE=127.63.0.0
$ export UAVCAN__NODE__ID=42
$ yakut file-server --plug-and-play=allocation_table.db --update-software
```

If there are any nodes online (or if they join the network later),
the server will check the version of each by sending `uavcan.node.GetInfo`,
and if a newer package is available locally, it will request the node to install it
by sending `uavcan.node.ExecuteCommand`.

In this specific case, the following will happen:

- Nodes 1 and 2 will be updated to v1.1.
- Nodes 3 and 4 will not be updated because the newer package v3.5 is incompatible with hardware v4.2,
  and the compatible version v3.3 is too old.
- Node 5 will not be updated because there are no suitable packages.

Add `--verbose` to see how exactly the decisions are made.

This command can be used to implement **automatic network-wide configuration management**.
Start the server and leave it running.
Store all relevant packages into its root directory.
When a node is connected or restarted, the server will automatically compare the version of its software
against the local files and perform an update if necessary.
Therefore, the entire network will be kept up-to-date without manual intervention.
