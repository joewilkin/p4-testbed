P4 Testbed
========================================================
*An Undergraduate Honors Thesis Project by Joseph Wilkin.*

This project combines MiniEdit, the Mininet GUI, with BMv2 software switches and an Aurora 610 programmable hardware switch to create one of the first platforms built specifically for programming in P4 and running P4-based experiments.

This program contains a BMv2 match-action table interface which allows users to easily visualize and manage their P4 programs' tables and table entries without needing the command line. The program also integrates with an Aurora 610 programmable hardware switch, allowing users to build topolgies using this switch and classic Mininet hosts to run experiemts with the simplicity and ease of a network emulator and the fidelity and granulation of a physical testbed. The program also includes a simple match-action table interface for the hardware swtich which allows the user to visualize the entries in their P4 tables.

## Installation Steps

### Software Emulation

This program can be ran on a physical Linux machine or a virtual environment and can be used to emulate Mininet topologies using the BMv2 software P4 switch, so long as the following dependancies have been installed:

* [Mininet](https://github.com/mininet/mininet)
* [p4c](https://github.com/p4lang/p4c)
* [grpc](https://github.com/grpc/grpc)
* [nanomsg](https://github.com/nanomsg/nanomsg)
* [bmv2](https://github.com/p4lang/behavioral-model)
* [protobuf](https://github.com/protocolbuffers/protobuf)
* [thrift](https://github.com/apache/thrift)

Additionally, Python version 3.10 or higher should be installed.

### Hardware Emulation

To use the hardware switch-specific features, the program and dependancies in the above section must be installed on a physical Linux machine connected to an Aurora 610 hardware switch configured with the Tofino 1 architecture. The switch should be started with a compiled P4 program and the server.py script should be running on the switch using:

`python3 server.py`

## Usage Steps

Once the dependancies have been installed, the program can be run using:

`python3 miniedit.py`

This will launch an empty MiniEdit window in which a topology can be built. Notice that two new icons representing the BMv2 software switch and the hardware switch have been included and can be used in constructing network topologies. Pressing the "Run" button will start the underlying Mininet virtual network, which will work as normal.

Please note that at this point in time, the hardware switch must be manually started and configured in order to work with this program. Additonally, the "server.py" script must be ran on the hardware switch. This can be done using:

`python3 server.py`

## Features

On top of the features offered by standard Mininet and MiniEdit, this P4 testbed includes:

* Built-in support for the BMv2 software switch, allowing users to effortlessly construct topologies using P4 switches.
* A match-action table interface which allows users to view and modify the table entries located on the data plane of a P4 switch without using the command line.
* An icon representing the Aurora 610 hardware switch which allows users to effortlessly integrate this swtich into their Mininet topologies.
* A simple interface which allows users to view the tables and table entries present on the hardware switch.

*This tool is based on Mininet, a virtual network emulator licensed under the BSD 3-Clause License. This tool is not endorsed by the Mininet project or its contributors.*
