#!/usr/bin/python3

import os
import sys
import pdb

#
# This is optional if you use proper PYTHONPATH
#
SDE_INSTALL = os.environ['SDE_INSTALL']
SDE_PYTHON2 = os.path.join(SDE_INSTALL, 'lib', 'python2.7', 'site-packages')
sys.path.append(SDE_PYTHON2)
sys.path.append(os.path.join(SDE_PYTHON2, 'tofino'))

PYTHON3_VER = '{}.{}'.format(
        sys.version_info.major,
        sys.version_info.minor)
SDE_PYTHON3 = os.path.join(SDE_INSTALL, 'lib', 'python' + PYTHON3_VER,
        'site-packages')

sys.path.append(SDE_PYTHON3)
sys.path.append(os.path.join(SDE_PYTHON3, 'tofino'))
sys.path.append(os.path.join(SDE_PYTHON3, 'tofino', 'bfrt_grpc'))

# Here is the most important module
import bfrt_grpc.client as gc

#
# Connect to the BF Runtime Server
#
for bfrt_client_id in range(10):
    try:
        interface = gc.ClientInterface(
                grpc_addr = 'localhost:50052',
                client_id = bfrt_client_id,
                device_id = 0,
                num_tries = 1)
        print('Connected to BF Runtime Server as client', bfrt_client_id)
        break
    except:
        print('Could not connect to BF Runtime server')
        quit

#
# Get the information about the running program
#
bfrt_info = interface.bfrt_info_get()
print('The target runs the program', bfrt_info.p4_name_get())

#
# Establish that you are using this program on the given connection
#
if bfrt_client_id == 0:
    interface.bind_pipeline_config(bfrt_info.p4_name_get())

################### You can now use BFRT CLIENT ###########################

#
# Get the bfrt_info object that contains all the data plane p4 and non-p4 elements 
# to be configured.
#
bfrt_info = interface.bfrt_info_get(bfrt_info.p4_name_get())
ingress_tables = []
for table in bfrt_info.table_list_sorted:
    if '.MyIngress.' in table:
        ingress_tables.append(table)


def getEntries(table):

    # Get the table object of interest
    ipv4_host_table = bfrt_info.table_get(table)
    
    # initialize dict for table entries
    entries = []

    # Get the table's entries
    dev_tgt = gc.Target(0)
    ipv4_host_entries = ipv4_host_table.entry_get(dev_tgt, [])
    for (data, key) in ipv4_host_entries:
        entries.append([data.to_dict(), key.to_dict()])

    entries_dict = {"table": table}
    entries_dict.update({"entries": entries})
    return entries_dict
    
import socket
import json

tables_dict = {"tables": ingress_tables}
data = json.dumps(tables_dict)

s = socket.socket()
print("Socket successfully created")

port = 12345

s.bind(('', port))
print(f"Socket bound to port {port}")

s.listen(1)
print("socket is listening")

# loop forever
while True:
    # server waits on accept() for incoming requests
    # new socket created on return
    c, addr = s.accept()
    print('Got connection from', addr)

    # read bytes from socket
    payload = c.recv(1024).decode()
    
    response = ""
    if payload == "get tables":
        response = bytes(data, encoding="utf-8")
    else:
        response = bytes(json.dumps(getEntries(payload)), encoding="utf-8")
    
    print("sending:", response.decode())
    c.send(response)
    c.close()


