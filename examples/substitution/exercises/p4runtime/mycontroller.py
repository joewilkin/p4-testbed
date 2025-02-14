from scapy.all import get_if_list, sniff, sendpfast
import threading
import argparse
import os
import sys
import json
from time import sleep

import grpc

# Import P4Runtime lib from parent utils dir
# Probably there's a better way of doing this.
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '../../utils/'))
import p4runtime_lib.bmv2
import p4runtime_lib.helper
from p4runtime_lib.switch import ShutdownAllSwitchConnections

def new_forwarding_rule(p4info_helper, dest, port, switch, connection, modify=False):
    table = 'MyIngress.ipv4_host'
    match_fields = {
        'hdr.ipv4.dstAddr': getAddress(dest)
    }
    action = 'MyIngress.ipv4_forward'
    action_params = {
        'port': port,
        'dstAddr': getMac(dest)
    }
    table_entry = p4info_helper.buildTableEntry(table_name=table,
                                                match_fields=match_fields,
                                                action_name=action,
                                                action_params=action_params)
    if (modify):
        print('modify rule:', switch, 'send', getAddress(dest), 'to port', port)
        connection.ModifyTableEntry(table_entry)
    else:
        print('adding rule:', switch, 'send', getAddress(dest), 'to port', port)
        connection.WriteTableEntry(table_entry)

def read_counter(p4info_helper, switch_connections, switch, port):
    counter_name = 'MyIngress.egressCounter'
    for response in switch_connections[switch].ReadCounters(p4info_helper.get_counters_id(counter_name), port):
        if len(response.entities) > 1:
            print("More than one response from counter read.")
        for entity in response.entities:
            counter = entity.counter_entry
            return counter.data.byte_count

def printGrpcError(e):
    print("gRPC Error:", e.details(), end=' ')
    status_code = e.code()
    print("(%s)" % status_code.name, end=' ')
    traceback = sys.exc_info()[2]
    print("[%s:%d]" % (traceback.tb_frame.f_code.co_filename, traceback.tb_lineno))

class TopoGraph:

    class Node:
        def __init__(self):
            self.edges = []
            self.ports = {}

        def add_edge(self, node, port=None):
            if node not in self.edges:
                self.edges.append(node)
            if port != None:
                self.ports[node] = port
    
    def __init__(self):
        self.nodes = {}
        self.hosts = []
        self.switches = []
        self.subbed_switch = None
    
    def add_link(self, link):
        for link_str in link:
            link_node = link_str.split('-')[0]
            if link_node not in self.nodes.keys():
                new_node = self.Node()
                self.nodes[link_node] = new_node
                if link_node[0] == 'h':
                    self.hosts.append(link_node)
                if link_node[0] == 's':
                    self.switches.append(link_node)
        node1 = link[0].split('-')
        node2 = link[1].split('-')
        if len(node1) > 1:
            self.nodes[node1[0]].add_edge(node2[0], int(node1[1][1:]))
        else:
            self.nodes[node1[0]].add_edge(node2[0])
        if len(node2) > 1:
            self.nodes[node2[0]].add_edge(node1[0], int(node2[1][1:]))
        else:
            self.nodes[node2[0]].add_edge(node1[0])
    
    def default_routing(self):
        routes = []
        for host in self.hosts:
            dest = host
            visited = []
            stack = [host]
            while len(stack) > 0:
                curr_node = stack.pop()
                for adj in self.nodes[curr_node].edges:
                    if adj[0] == 's' and adj not in visited:
                        return_port = self.nodes[adj].ports[curr_node]
                        routes.append({
                            'dest': dest,
                            'port': return_port,
                            'switch': adj
                        })
                        stack.append(adj)
                        visited.append(adj)
        return routes
    
    def get_substitutable(self):
        substitutable = []
        for sw in self.switches:
            if all([link[0] == 's' for link in self.nodes[sw].edges]):
                substitutable.append(sw)
        return substitutable

    def add_hw_ports(self):
        substitutable = self.get_substitutable()
        neighbors = []
        for sw in substitutable:
            for adj in self.nodes[sw].edges:
                if adj not in substitutable:
                    neighbors.append(adj)
        for sw in neighbors:
            port = max(self.nodes[sw].ports.values()) + 1
            self.nodes[sw].add_edge('br-%s-hw' % sw, port)

    def substitute_switch(self, p4info_helper, switch_connections, external_intfs, switch):
        print(external_intfs)
        # Unlink currently linked switch
        defaults = self.default_routing()
        if self.subbed_switch != None:
            print("UNSUBBING", self.subbed_switch)
            for adj in self.nodes[self.subbed_switch].edges:
                port_to_switch = self.nodes[adj].ports[self.subbed_switch]
                routes = [route for route in defaults if route['switch'] == adj and route['port'] == port_to_switch]
                for route in routes:
                    new_forwarding_rule(p4info_helper,
                                        route['dest'],
                                        route['port'],
                                        route['switch'],
                                        switch_connections[route['switch']],
                                        modify=True)
            # Tell multiplexer which ports to stop listening on
            for adj in self.nodes[self.subbed_switch].edges:
                bridge = 'br-%s-hw' % adj
                external_port = self.nodes[self.subbed_switch].ports[adj]
                print('unlinking:', bridge, "from extermal port", external_intfs[external_port-1])
                os.system('ip link set %s nomaster' % external_intfs[external_port-1])
            self.subbed_switch = None
        
        # Tell multiplexer which new ports to start listening on
        if switch != None:
            print("SUBSTITUTING", switch)
            for adj in self.nodes[switch].edges:
                external_port = self.nodes[switch].ports[adj]
                bridge = 'br-%s-hw' % adj
                print('linking', bridge, 'to external port', external_intfs[external_port-1])
                os.system('ip link set %s master %s' % (external_intfs[external_port-1], bridge))
            
            # Link currently linked switch
            for adj in self.nodes[switch].edges:
                port_to_hw = self.nodes[adj].ports['br-%s-hw' % adj]
                port_to_switch = self.nodes[adj].ports[switch]
                routes = [route for route in defaults if route['switch'] == adj and route['port'] == port_to_switch]
                for route in routes:
                    new_forwarding_rule(p4info_helper,
                                        route['dest'],
                                        port_to_hw,
                                        route['switch'],
                                        switch_connections[route['switch']],
                                        modify=True)
            self.subbed_switch = switch

def getAddress(hostname: str):
    assert(hostname[0] == 'h')
    num = int(hostname[1:])
    return '10.0.%i.%i' % (num, num)

def getMac(hostname: str):
    assert(hostname[0] == 'h')
    num = int(hostname[1:])
    return '08:00:00:00:%02i:%i%i' % (num, num, num)

def main(p4info_file_path, bmv2_file_path, topo_path):

    external_intfs = []
    for intf in get_if_list():
        if intf[:3] == 'enp':
            external_intfs.append(intf)
    
    with open(topo_path, 'r') as topo_file:
        topo_json = json.load(topo_file)
        topo = TopoGraph()
        for link in topo_json['links']:
            topo.add_link(link)
        topo.add_hw_ports()

    # Instantiate a P4Runtime helper from the p4info file
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_file_path)

    try:
        # Create a switch connection object for s1 and s2;
        # this is backed by a P4Runtime gRPC connection.
        # Also, dump all P4Runtime messages sent to switch to given txt files.
        print('connecting to switches...')
        switches = {}
        for i in range(len(topo_json['switches'])):
            switches['s%i' % (i+1)] = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s%i' % (i+1),
            address='127.0.0.1:5005%i' % (i+1),
            device_id=i,
            proto_dump_file='logs/s%i-p4runtime-requests.txt' % (i+1))
            print('connected to', 's%i' % (i+1))

        # Send master arbitration update message to establish this controller as
        # master (required by P4Runtime before performing any other write operation)
        for _, sw in switches.items():
            sw.MasterArbitrationUpdate()

        # Install the P4 program on the switches
        for _, sw in switches.items():
            installation_json = bmv2_file_path
            if topo_json['switches'][sw.name]['program']:
                installation_json = topo_json['switches'][sw.name]['program']
            sw.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                       bmv2_json_file_path=installation_json)
            print("Installed", installation_json, "Program using SetForwardingPipelineConfig on", sw.name)
        
        for entry in topo.default_routing():
            new_forwarding_rule(p4info_helper,
                                entry['dest'],
                                entry['port'],
                                entry['switch'],
                                switches[entry['switch']])
        
        counterValues = {sw: 0 for sw in topo.get_substitutable()}
        counterAverages = {sw: 0 for sw in topo.get_substitutable()}

        interval = 1.0
        alpha = 0.04
        
        while True:
            sleep(interval)
            for sw, count in counterValues.items():
                sum = 0
                for adj in topo.nodes[sw].edges:
                    toSoftware = read_counter(p4info_helper, switches, adj, topo.nodes[adj].ports[sw])
                    toHardware = read_counter(p4info_helper, switches, adj, topo.nodes[adj].ports['br-%s-hw' % adj])
                    sum += toSoftware + toHardware
                # Exponential Moving Average
                counterAverages[sw] = counterAverages[sw] * (1-alpha) + (sum-count) * alpha
                counterValues[sw] = sum
            
            print("Averages:")
            for sw, avg in counterAverages.items():
                print(sw, ": ", avg, sep='')

            highest_switch = None
            highest_average = 0
            for sw, avg in counterAverages.items():
                if avg > highest_average:
                    highest_average = avg
                    highest_switch = sw
            if highest_switch != None and highest_switch != topo.subbed_switch:
                pass
                # topo.substitute_switch(p4info_helper, switches, external_intfs, highest_switch)

    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='P4Runtime Controller')
    parser.add_argument('--p4info', help='p4info proto in text format from p4c',
                        type=str, action="store", required=False,
                        default='./build/basic.p4.p4info.txt')
    parser.add_argument('--bmv2-json', help='BMv2 JSON file from p4c',
                        type=str, action="store", required=False,
                        default='./build/basic.json')
    parser.add_argument('--topo-json', help='topology.json file',
                        type=str, action="store", required=False,
                        default='./topology.json')
    args = parser.parse_args()

    if not os.path.exists(args.p4info):
        parser.print_help()
        print("\np4info file not found: %s\nHave you run 'make'?" % args.p4info)
        parser.exit(1)
    if not os.path.exists(args.bmv2_json):
        parser.print_help()
        print("\nBMv2 JSON file not found: %s\nHave you run 'make'?" % args.bmv2_json)
        parser.exit(1)
    main(args.p4info, args.bmv2_json, args.topo_json)