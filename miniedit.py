#!/usr/bin/env python

"""
MiniEdit: a simple network editor for Mininet

This is a simple demonstration of how one might build a
GUI application using Mininet as the network model.

Bob Lantz, April 2010
Gregory Gee, July 2013

Modified by Joseph Wilkin, April 2025
This is a modified version of MiniEdit built specifically for P4 and BMv2.

Controller icon from http://semlabs.co.uk/
OpenFlow icon from https://www.opennetworking.org/
"""

import json
import os
import re
import sys
import socket

from functools import partial
from optparse import OptionParser  # pylint: disable=deprecated-module
from subprocess import call
from sys import exit  # pylint: disable=redefined-builtin

from mininet.log import info, debug, warn, setLogLevel
from mininet.net import Mininet, VERSION
from mininet.util import (netParse, ipAdd, quietRun,
                          buildTopo, custom, customClass, decode )
from mininet.term import makeTerm, cleanUpScreens
from mininet.node import (Controller, RemoteController, NOX, OVSController,
                          CPULimitedHost, Host, Node,
                          OVSSwitch, UserSwitch, IVSSwitch )
from mininet.link import TCLink, Intf, Link
from mininet.cli import CLI
from mininet.moduledeps import moduleDeps
from mininet.topo import SingleSwitchTopo, LinearTopo, SingleSwitchReversedTopo
from mininet.topolib import TreeTopo
from p4_mininet import P4Switch, P4Host

# pylint: disable=import-error
if sys.version_info[0] == 2:
    from Tkinter import ( Frame, Label, LabelFrame, Entry, OptionMenu,
                          Checkbutton, Menu, Toplevel, Button, BitmapImage,
                          PhotoImage, Canvas, Scrollbar, Wm, TclError,
                          StringVar, IntVar, E, W, EW, NW, Y, VERTICAL, SOLID,
                          CENTER, RIGHT, LEFT, BOTH, TRUE, FALSE )
    from ttk import Notebook
    from tkMessageBox import showerror
    import tkFont
    import tkFileDialog
    import tkSimpleDialog
else:
    from tkinter import ( Frame, Label, LabelFrame, Entry, OptionMenu,
                          Checkbutton, Menu, Toplevel, Button, BitmapImage,
                          PhotoImage, Canvas, Scrollbar, Wm, TclError,
                          StringVar, IntVar, Radiobutton, E, W, EW, NW, Y, VERTICAL, SOLID,
                          CENTER, RIGHT, LEFT, BOTH, TRUE, FALSE )
    from tkinter.ttk import Notebook
    from tkinter.ttk import Combobox
    from tkinter.ttk import Progressbar
    from tkinter.messagebox import (showerror, showwarning, showinfo)
    from tkinter import font as tkFont
    from tkinter import simpledialog as tkSimpleDialog
    from tkinter import filedialog as tkFileDialog
# someday: from ttk import *
# pylint: enable=import-error


# Miniedit still needs work in order to pass pylint...
# pylint: disable=line-too-long,too-many-branches
# pylint: disable=too-many-statements,attribute-defined-outside-init
# pylint: disable=missing-docstring,too-many-ancestors
# pylint: disable=too-many-nested-blocks,too-many-arguments

try:
    import packaging.version # replacement for distutils.version
    StrictVersion = packaging.version.parse
except ImportError: # python2.7 lacks ModuleNotFoundError
    import distutils.version # pylint: disable=deprecated-module
    StrictVersion = distutils.version.StrictVersion
    

MINIEDIT_VERSION = '2.2.0.1'

if 'PYTHONPATH' in os.environ:
    sys.path = os.environ[ 'PYTHONPATH' ].split( ':' ) + sys.path

info( 'MiniEdit running against Mininet '+VERSION, '\n' )
MININET_VERSION = re.sub(r'[^\d\.]', '', VERSION)

TOPODEF = 'none'
TOPOS = { 'minimal': lambda: SingleSwitchTopo( k=2 ),
          'linear': LinearTopo,
          'reversed': SingleSwitchReversedTopo,
          'single': SingleSwitchTopo,
          'none': None,
          'tree': TreeTopo }
CONTROLLERDEF = 'ref'
CONTROLLERS = { 'ref': Controller,
                'ovsc': OVSController,
                'nox': NOX,
                'remote': RemoteController,
                'none': lambda name: None }
LINKDEF = 'default'
LINKS = { 'default': Link,
          'tc': TCLink }
HOSTDEF = 'proc'
HOSTS = { 'proc': Host,
          'rt': custom( CPULimitedHost, sched='rt' ),
          'cfs': custom( CPULimitedHost, sched='cfs' ) }


class InbandController( RemoteController ):
    "RemoteController that ignores checkListening"
    def checkListening( self ):
        "Overridden to do nothing."
        return

class CustomUserSwitch(UserSwitch):
    "Customized UserSwitch"
    def __init__( self, name, dpopts='--no-slicing', **kwargs ):
        UserSwitch.__init__( self, name, **kwargs )
        self.switchIP = None

    def getSwitchIP(self):
        "Return management IP address"
        return self.switchIP

    def setSwitchIP(self, ip):
        "Set management IP address"
        self.switchIP = ip

    def start( self, controllers ):
        "Start and set management IP address"
        # Call superclass constructor
        UserSwitch.start( self, controllers )
        # Set Switch IP address
        if self.switchIP is not None:
            if not self.inNamespace:
                self.cmd( 'ifconfig', self, self.switchIP )
            else:
                self.cmd( 'ifconfig lo', self.switchIP )

class LegacyRouter( Node ):
    "Simple IP router"
    def __init__( self, name, inNamespace=True, **params ):
        Node.__init__( self, name, inNamespace, **params )

    # pylint: disable=arguments-differ
    def config( self, **_params ):
        if self.intfs:
            self.setParam( _params, 'setIP', ip='0.0.0.0' )
        r = Node.config( self, **_params )
        self.cmd('sysctl -w net.ipv4.ip_forward=1')
        return r

class LegacySwitch(OVSSwitch):
    "OVS switch in standalone/bridge mode"
    def __init__( self, name, **params ):
        OVSSwitch.__init__( self, name, failMode='standalone', **params )
        self.switchIP = None

class customOvs(OVSSwitch):
    "Customized OVS switch"

    def __init__( self, name, failMode='secure', datapath='kernel', **params ):
        OVSSwitch.__init__( self, name, failMode=failMode, datapath=datapath,**params )
        self.switchIP = None

    def getSwitchIP(self):
        "Return management IP address"
        return self.switchIP

    def setSwitchIP(self, ip):
        "Set management IP address"
        self.switchIP = ip

    def start( self, controllers ):
        "Start and set management IP address"
        # Call superclass constructor
        OVSSwitch.start( self, controllers )
        # Set Switch IP address
        if self.switchIP is not None:
            self.cmd( 'ifconfig', self, self.switchIP )

class PrefsDialog(tkSimpleDialog.Dialog):
    "Preferences dialog"

    def __init__(self, parent, title, prefDefaults):

        self.prefValues = prefDefaults

        tkSimpleDialog.Dialog.__init__(self, parent, title)

    def body(self, master):
        "Create dialog body"
        self.rootFrame = master
        self.leftfieldFrame = Frame(self.rootFrame, padx=5, pady=5)
        self.leftfieldFrame.grid(row=0, column=0, sticky='nswe', columnspan=2)
        self.rightfieldFrame = Frame(self.rootFrame, padx=5, pady=5)
        self.rightfieldFrame.grid(row=0, column=2, sticky='nswe', columnspan=2)

        # Field for Base IP
        Label(self.leftfieldFrame, text="IP Base:").grid(row=0, sticky=E)
        self.ipEntry = Entry(self.leftfieldFrame)
        self.ipEntry.grid(row=0, column=1)
        ipBase =  self.prefValues['ipBase']
        self.ipEntry.insert(0, ipBase)

        # Selection of terminal type
        Label(self.leftfieldFrame, text="Default Terminal:").grid(row=1, sticky=E)
        self.terminalVar = StringVar(self.leftfieldFrame)
        self.terminalOption = OptionMenu(self.leftfieldFrame, self.terminalVar, "xterm", "gterm")
        self.terminalOption.grid(row=1, column=1, sticky=W)
        terminalType = self.prefValues['terminalType']
        self.terminalVar.set(terminalType)

        # Field for CLI
        Label(self.leftfieldFrame, text="Start CLI:").grid(row=2, sticky=E)
        self.cliStart = IntVar()
        self.cliButton = Checkbutton(self.leftfieldFrame, variable=self.cliStart)
        self.cliButton.grid(row=2, column=1, sticky=W)
        if self.prefValues['startCLI'] == '0':
            self.cliButton.deselect()
        else:
            self.cliButton.select()

        # Selection of switch type
        Label(self.leftfieldFrame, text="Default Switch:").grid(row=3, sticky=E)
        self.switchType = StringVar(self.leftfieldFrame)
        self.switchTypeMenu = OptionMenu(self.leftfieldFrame, self.switchType, "Open vSwitch Kernel Mode", "Indigo Virtual Switch", "Userspace Switch", "Userspace Switch inNamespace")
        self.switchTypeMenu.grid(row=3, column=1, sticky=W)
        switchTypePref = self.prefValues['switchType']
        if switchTypePref == 'ivs':
            self.switchType.set("Indigo Virtual Switch")
        elif switchTypePref == 'userns':
            self.switchType.set("Userspace Switch inNamespace")
        elif switchTypePref == 'user':
            self.switchType.set("Userspace Switch")
        else:
            self.switchType.set("Open vSwitch Kernel Mode")


        # Fields for OVS OpenFlow version
        ovsFrame= LabelFrame(self.leftfieldFrame, text='Open vSwitch', padx=5, pady=5)
        ovsFrame.grid(row=4, column=0, columnspan=2, sticky=EW)
        Label(ovsFrame, text="OpenFlow 1.0:").grid(row=0, sticky=E)
        Label(ovsFrame, text="OpenFlow 1.1:").grid(row=1, sticky=E)
        Label(ovsFrame, text="OpenFlow 1.2:").grid(row=2, sticky=E)
        Label(ovsFrame, text="OpenFlow 1.3:").grid(row=3, sticky=E)

        self.ovsOf10 = IntVar()
        self.covsOf10 = Checkbutton(ovsFrame, variable=self.ovsOf10)
        self.covsOf10.grid(row=0, column=1, sticky=W)
        if self.prefValues['openFlowVersions']['ovsOf10'] == '0':
            self.covsOf10.deselect()
        else:
            self.covsOf10.select()

        self.ovsOf11 = IntVar()
        self.covsOf11 = Checkbutton(ovsFrame, variable=self.ovsOf11)
        self.covsOf11.grid(row=1, column=1, sticky=W)
        if self.prefValues['openFlowVersions']['ovsOf11'] == '0':
            self.covsOf11.deselect()
        else:
            self.covsOf11.select()

        self.ovsOf12 = IntVar()
        self.covsOf12 = Checkbutton(ovsFrame, variable=self.ovsOf12)
        self.covsOf12.grid(row=2, column=1, sticky=W)
        if self.prefValues['openFlowVersions']['ovsOf12'] == '0':
            self.covsOf12.deselect()
        else:
            self.covsOf12.select()

        self.ovsOf13 = IntVar()
        self.covsOf13 = Checkbutton(ovsFrame, variable=self.ovsOf13)
        self.covsOf13.grid(row=3, column=1, sticky=W)
        if self.prefValues['openFlowVersions']['ovsOf13'] == '0':
            self.covsOf13.deselect()
        else:
            self.covsOf13.select()

        # Field for DPCTL listen port
        Label(self.leftfieldFrame, text="dpctl port:").grid(row=5, sticky=E)
        self.dpctlEntry = Entry(self.leftfieldFrame)
        self.dpctlEntry.grid(row=5, column=1)
        if 'dpctl' in self.prefValues:
            self.dpctlEntry.insert(0, self.prefValues['dpctl'])

        # sFlow
        sflowValues = self.prefValues['sflow']
        self.sflowFrame= LabelFrame(self.rightfieldFrame, text='sFlow Profile for Open vSwitch', padx=5, pady=5)
        self.sflowFrame.grid(row=0, column=0, columnspan=2, sticky=EW)

        Label(self.sflowFrame, text="Target:").grid(row=0, sticky=E)
        self.sflowTarget = Entry(self.sflowFrame)
        self.sflowTarget.grid(row=0, column=1)
        self.sflowTarget.insert(0, sflowValues['sflowTarget'])

        Label(self.sflowFrame, text="Sampling:").grid(row=1, sticky=E)
        self.sflowSampling = Entry(self.sflowFrame)
        self.sflowSampling.grid(row=1, column=1)
        self.sflowSampling.insert(0, sflowValues['sflowSampling'])

        Label(self.sflowFrame, text="Header:").grid(row=2, sticky=E)
        self.sflowHeader = Entry(self.sflowFrame)
        self.sflowHeader.grid(row=2, column=1)
        self.sflowHeader.insert(0, sflowValues['sflowHeader'])

        Label(self.sflowFrame, text="Polling:").grid(row=3, sticky=E)
        self.sflowPolling = Entry(self.sflowFrame)
        self.sflowPolling.grid(row=3, column=1)
        self.sflowPolling.insert(0, sflowValues['sflowPolling'])

        # NetFlow
        nflowValues = self.prefValues['netflow']
        self.nFrame= LabelFrame(self.rightfieldFrame, text='NetFlow Profile for Open vSwitch', padx=5, pady=5)
        self.nFrame.grid(row=1, column=0, columnspan=2, sticky=EW)

        Label(self.nFrame, text="Target:").grid(row=0, sticky=E)
        self.nflowTarget = Entry(self.nFrame)
        self.nflowTarget.grid(row=0, column=1)
        self.nflowTarget.insert(0, nflowValues['nflowTarget'])

        Label(self.nFrame, text="Active Timeout:").grid(row=1, sticky=E)
        self.nflowTimeout = Entry(self.nFrame)
        self.nflowTimeout.grid(row=1, column=1)
        self.nflowTimeout.insert(0, nflowValues['nflowTimeout'])

        Label(self.nFrame, text="Add ID to Interface:").grid(row=2, sticky=E)
        self.nflowAddId = IntVar()
        self.nflowAddIdButton = Checkbutton(self.nFrame, variable=self.nflowAddId)
        self.nflowAddIdButton.grid(row=2, column=1, sticky=W)
        if nflowValues['nflowAddId'] == '0':
            self.nflowAddIdButton.deselect()
        else:
            self.nflowAddIdButton.select()

        # initial focus
        return self.ipEntry

    def apply(self):
        ipBase = self.ipEntry.get()
        terminalType = self.terminalVar.get()
        startCLI = str(self.cliStart.get())
        sw = self.switchType.get()
        dpctl = self.dpctlEntry.get()

        ovsOf10 = str(self.ovsOf10.get())
        ovsOf11 = str(self.ovsOf11.get())
        ovsOf12 = str(self.ovsOf12.get())
        ovsOf13 = str(self.ovsOf13.get())

        sflowValues = {'sflowTarget':self.sflowTarget.get(),
                       'sflowSampling':self.sflowSampling.get(),
                       'sflowHeader':self.sflowHeader.get(),
                       'sflowPolling':self.sflowPolling.get()}
        nflowvalues = {'nflowTarget':self.nflowTarget.get(),
                       'nflowTimeout':self.nflowTimeout.get(),
                       'nflowAddId':str(self.nflowAddId.get())}
        self.result = {'ipBase':ipBase,
                       'terminalType':terminalType,
                       'dpctl':dpctl,
                       'sflow':sflowValues,
                       'netflow':nflowvalues,
                       'startCLI':startCLI}
        if sw == 'Indigo Virtual Switch':
            self.result['switchType'] = 'ivs'
            if StrictVersion(MININET_VERSION) < StrictVersion('2.1'):
                self.ovsOk = False
                showerror(title="Error",
                          message='MiniNet version 2.1+ required. You have '+VERSION+'.')
        elif sw == 'Userspace Switch':
            self.result['switchType'] = 'user'
        elif sw == 'Userspace Switch inNamespace':
            self.result['switchType'] = 'userns'
        else:
            self.result['switchType'] = 'ovs'

        self.ovsOk = True
        if ovsOf11 == "1":
            ovsVer = self.getOvsVersion()
            if StrictVersion(ovsVer) < StrictVersion('2.0'):
                self.ovsOk = False
                showerror(title="Error",
                          message='Open vSwitch version 2.0+ required. You have '+ovsVer+'.')
        if ovsOf12 == "1" or ovsOf13 == "1":
            ovsVer = self.getOvsVersion()
            if StrictVersion(ovsVer) < StrictVersion('1.10'):
                self.ovsOk = False
                showerror(title="Error",
                          message='Open vSwitch version 1.10+ required. You have '+ovsVer+'.')

        if self.ovsOk:
            self.result['openFlowVersions']={'ovsOf10':ovsOf10,
                                             'ovsOf11':ovsOf11,
                                             'ovsOf12':ovsOf12,
                                             'ovsOf13':ovsOf13}
        else:
            self.result = None

    @staticmethod
    def getOvsVersion():
        "Return OVS version"
        outp = quietRun("ovs-vsctl --version")
        r = r'ovs-vsctl \(Open vSwitch\) (.*)'
        m = re.search(r, outp)
        if m is None:
            warn( 'Version check failed' )
            return None
        else:
            info( 'Open vSwitch version is '+m.group(1), '\n' )
            return m.group(1)


class CustomDialog(object):

    # TODO: Fix button placement and Title and window focus lock
    def __init__(self, master, _title):
        self.top=Toplevel(master)

        self.bodyFrame = Frame(self.top)
        self.bodyFrame.grid(row=0, column=0, sticky='nswe')
        self.body(self.bodyFrame)

        #return self.b # initial focus
        buttonFrame = Frame(self.top, relief='ridge', bd=3, bg='lightgrey')
        buttonFrame.grid(row=1 , column=0, sticky='nswe')

        okButton = Button(buttonFrame, width=8, text='OK', relief='groove',
                   bd=4, command=self.okAction)
        okButton.grid(row=0, column=0, sticky=E)

        canlceButton = Button(buttonFrame, width=8, text='Cancel', relief='groove',
                    bd=4, command=self.cancelAction)
        canlceButton.grid(row=0, column=1, sticky=W)

    def body(self, master):
        self.rootFrame = master

    def apply(self):
        self.top.destroy()

    def cancelAction(self):
        self.top.destroy()

    def okAction(self):
        self.apply()
        self.top.destroy()

class HostDialog(CustomDialog):

    def __init__(self, master, title, prefDefaults):

        self.prefValues = prefDefaults
        self.result = None

        CustomDialog.__init__(self, master, title)

    def body(self, master):
        self.rootFrame = master
        n = Notebook(self.rootFrame)
        self.propFrame = Frame(n)
        self.vlanFrame = Frame(n)
        self.interfaceFrame = Frame(n)
        self.mountFrame = Frame(n)
        n.add(self.propFrame, text='Properties')
        n.add(self.vlanFrame, text='VLAN Interfaces')
        n.add(self.interfaceFrame, text='External Interfaces')
        n.add(self.mountFrame, text='Private Directories')
        n.pack()

        ### TAB 1
        # Field for Hostname
        Label(self.propFrame, text="Hostname:").grid(row=0, sticky=E)
        self.hostnameEntry = Entry(self.propFrame)
        self.hostnameEntry.grid(row=0, column=1)
        if 'hostname' in self.prefValues:
            self.hostnameEntry.insert(0, self.prefValues['hostname'])

        # Field for IP address
        Label(self.propFrame, text="IP Address:").grid(row=1, sticky=E)
        self.ipEntry = Entry(self.propFrame)
        self.ipEntry.grid(row=1, column=1)
        if 'ip' in self.prefValues:
            self.ipEntry.insert(0, self.prefValues['ip'])

        # Field for MAC address
        Label(self.propFrame, text="MAC Address:").grid(row=2, sticky=E)
        self.macEntry = Entry(self.propFrame)
        self.macEntry.grid(row=2, column=1)
        if 'mac' in self.prefValues:
            self.ipEntry.insert(0, self.prefValues['mac'])

        # Field for default route
        Label(self.propFrame, text="Default Route:").grid(row=3, sticky=E)
        self.routeEntry = Entry(self.propFrame)
        self.routeEntry.grid(row=3, column=1)
        if 'defaultRoute' in self.prefValues:
            self.routeEntry.insert(0, self.prefValues['defaultRoute'])

        # Field for CPU
        Label(self.propFrame, text="Amount CPU:").grid(row=4, sticky=E)
        self.cpuEntry = Entry(self.propFrame)
        self.cpuEntry.grid(row=4, column=1)
        if 'cpu' in self.prefValues:
            self.cpuEntry.insert(0, str(self.prefValues['cpu']))
        # Selection of Scheduler
        if 'sched' in self.prefValues:
            sched =  self.prefValues['sched']
        else:
            sched = 'host'
        self.schedVar = StringVar(self.propFrame)
        self.schedOption = OptionMenu(self.propFrame, self.schedVar, "host", "cfs", "rt")
        self.schedOption.grid(row=4, column=2, sticky=W)
        self.schedVar.set(sched)

        # Selection of Cores
        Label(self.propFrame, text="Cores:").grid(row=5, sticky=E)
        self.coreEntry = Entry(self.propFrame)
        self.coreEntry.grid(row=5, column=1)
        if 'cores' in self.prefValues:
            self.coreEntry.insert(1, self.prefValues['cores'])

        # Start command
        Label(self.propFrame, text="Start Command:").grid(row=6, sticky=E)
        self.startEntry = Entry(self.propFrame)
        self.startEntry.grid(row=6, column=1, sticky='nswe', columnspan=3)
        if 'startCommand' in self.prefValues:
            self.startEntry.insert(0, str(self.prefValues['startCommand']))
        # Stop command
        Label(self.propFrame, text="Stop Command:").grid(row=7, sticky=E)
        self.stopEntry = Entry(self.propFrame)
        self.stopEntry.grid(row=7, column=1, sticky='nswe', columnspan=3)
        if 'stopCommand' in self.prefValues:
            self.stopEntry.insert(0, str(self.prefValues['stopCommand']))

        ### TAB 2
        # External Interfaces
        self.externalInterfaces = 0
        Label(self.interfaceFrame, text="External Interface:").grid(row=0, column=0, sticky=E)
        self.b = Button( self.interfaceFrame, text='Add', command=self.addInterface)
        self.b.grid(row=0, column=1)

        self.interfaceFrame = VerticalScrolledTable(self.interfaceFrame, rows=0, columns=1, title='External Interfaces')
        self.interfaceFrame.grid(row=1, column=0, sticky='nswe', columnspan=2)
        self.tableFrame = self.interfaceFrame.interior
        self.tableFrame.addRow(value=['Interface Name'], readonly=True)

        # Add defined interfaces
        externalInterfaces = []
        if 'externalInterfaces' in self.prefValues:
            externalInterfaces = self.prefValues['externalInterfaces']

        for externalInterface in externalInterfaces:
            self.tableFrame.addRow(value=[externalInterface])

        ### TAB 3
        # VLAN Interfaces
        self.vlanInterfaces = 0
        Label(self.vlanFrame, text="VLAN Interface:").grid(row=0, column=0, sticky=E)
        self.vlanButton = Button( self.vlanFrame, text='Add', command=self.addVlanInterface)
        self.vlanButton.grid(row=0, column=1)

        self.vlanFrame = VerticalScrolledTable(self.vlanFrame, rows=0, columns=2, title='VLAN Interfaces')
        self.vlanFrame.grid(row=1, column=0, sticky='nswe', columnspan=2)
        self.vlanTableFrame = self.vlanFrame.interior
        self.vlanTableFrame.addRow(value=['IP Address','VLAN ID'], readonly=True)

        vlanInterfaces = []
        if 'vlanInterfaces' in self.prefValues:
            vlanInterfaces = self.prefValues['vlanInterfaces']
        for vlanInterface in vlanInterfaces:
            self.vlanTableFrame.addRow(value=vlanInterface)

        ### TAB 4
        # Private Directories
        self.privateDirectories = 0
        Label(self.mountFrame, text="Private Directory:").grid(row=0, column=0, sticky=E)
        self.mountButton = Button( self.mountFrame, text='Add', command=self.addDirectory)
        self.mountButton.grid(row=0, column=1)

        self.mountFrame = VerticalScrolledTable(self.mountFrame, rows=0, columns=2, title='Directories')
        self.mountFrame.grid(row=1, column=0, sticky='nswe', columnspan=2)
        self.mountTableFrame = self.mountFrame.interior
        self.mountTableFrame.addRow(value=['Mount','Persistent Directory'], readonly=True)

        directoryList = []
        if 'privateDirectory' in self.prefValues:
            directoryList = self.prefValues['privateDirectory']
        for privateDir in directoryList:
            if isinstance( privateDir, tuple ):
                self.mountTableFrame.addRow(value=privateDir)
            else:
                self.mountTableFrame.addRow(value=[privateDir,''])


    def addDirectory( self ):
        self.mountTableFrame.addRow()

    def addVlanInterface( self ):
        self.vlanTableFrame.addRow()

    def addInterface( self ):
        self.tableFrame.addRow()

    def apply(self):
        externalInterfaces = []
        for row in range(self.tableFrame.rows):
            if (len(self.tableFrame.get(row, 0)) > 0 and
                row > 0):
                externalInterfaces.append(self.tableFrame.get(row, 0))
        vlanInterfaces = []
        for row in range(self.vlanTableFrame.rows):
            if (len(self.vlanTableFrame.get(row, 0)) > 0 and
                len(self.vlanTableFrame.get(row, 1)) > 0 and
                row > 0):
                vlanInterfaces.append([self.vlanTableFrame.get(row, 0), self.vlanTableFrame.get(row, 1)])
        privateDirectories = []
        for row in range(self.mountTableFrame.rows):
            if len(self.mountTableFrame.get(row, 0)) > 0 and row > 0:
                if len(self.mountTableFrame.get(row, 1)) > 0:
                    privateDirectories.append((self.mountTableFrame.get(row, 0), self.mountTableFrame.get(row, 1)))
                else:
                    privateDirectories.append(self.mountTableFrame.get(row, 0))

        results = {'cpu': self.cpuEntry.get(),
                   'cores':self.coreEntry.get(),
                   'sched':self.schedVar.get(),
                   'hostname':self.hostnameEntry.get(),
                   'ip':self.ipEntry.get(),
                   'mac':self.macEntry.get(),
                   'defaultRoute':self.routeEntry.get(),
                   'startCommand':self.startEntry.get(),
                   'stopCommand':self.stopEntry.get(),
                   'privateDirectory':privateDirectories,
                   'externalInterfaces':externalInterfaces,
                   'vlanInterfaces':vlanInterfaces}
        self.result = results

        if results['ip'] != '' and not re.match("^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])$", results['ip']):
            showwarning(title="MiniEdit", message=f'Host MAC Address \"{results["ip"]}\" is not valid. Results may be different from expected.')

        if results['mac'] != '' and not re.match("[0-9a-f]{2}([-:]?)[0-9a-f]{2}(\\1[0-9a-f]{2}){4}$", results['mac']):
            showwarning(title="MiniEdit", message=f'Host MAC Address \"{results["mac"]}\" is not valid. Results may be different from expected.')

class P4SwitchDialog(CustomDialog):
    """ Written by Joseph Wilkin """
    """ Dialog screen for the BMv4 P4 Software Switch """

    def __init__(self, master, title, prefDefaults):
        self.prefValues = prefDefaults
        self.result = None
        CustomDialog.__init__(self, master, title)

    def body(self, master):
        self.rootFrame = master
        n = Notebook(self.rootFrame)
        self.propFrame = Frame(n)
        self.ipFrame = Frame(n)
        n.add(self.propFrame, text='Properties')
        n.add(self.ipFrame, text='Multihoming IPs')
        n.pack()

        ### ROW 1
        # Field for Hostname
        Label(self.propFrame, text="Hostname:").grid(row=0, sticky=E)
        self.hostnameEntry = Entry(self.propFrame)
        self.hostnameEntry.grid(row=0, column=1, padx=10, pady=10)
        if 'hostname' in self.prefValues:
            self.hostnameEntry.insert(0, self.prefValues['hostname'])


        ### ROW 2
        # Field for JSON Path
        Label(self.propFrame, text="Compiled P4 Program:").grid(row=1, sticky=E, padx=(10, 0))
        self.jsonPathEntry = Entry(self.propFrame)
        self.jsonPathEntry.grid(row=1, column=1)
        Button(self.propFrame, text="Open", command=self.getJson).grid(row=2, column=1, sticky=E, padx=10, pady=10)
        if 'jsonPath' in self.prefValues:
            self.jsonPathEntry.insert(0, self.prefValues['jsonPath'])

    def getJson(self):
        """ Get compiled P4 program from local machine """

        myFormats = [
            ('Compiled P4 Program (JSON)','*.json'),
            ('All Files','*'),
        ]
        self.f = tkFileDialog.askopenfile(filetypes=myFormats, mode='rb')
        if self.f is None:
            return
        
        print("Selected file", str(self.f.name))
        self.jsonPathEntry.delete(0, 'end')
        self.jsonPathEntry.insert(0, str(self.f.name))

    def apply(self):             
        results = {'hostname': self.hostnameEntry.get(),
                   'jsonPath': self.jsonPathEntry.get()}
        
        self.result = results
        


class SwitchDialog(CustomDialog):

    def __init__(self, master, title, prefDefaults):

        self.prefValues = prefDefaults
        self.result = None
        CustomDialog.__init__(self, master, title)

    def body(self, master):
        self.rootFrame = master
        self.leftfieldFrame = Frame(self.rootFrame)
        self.rightfieldFrame = Frame(self.rootFrame)
        self.leftfieldFrame.grid(row=0, column=0, sticky='nswe')
        self.rightfieldFrame.grid(row=0, column=1, sticky='nswe')

        rowCount = 0
        externalInterfaces = []
        if 'externalInterfaces' in self.prefValues:
            externalInterfaces = self.prefValues['externalInterfaces']

        # Field for Hostname
        Label(self.leftfieldFrame, text="Hostname:").grid(row=rowCount, sticky=E)
        self.hostnameEntry = Entry(self.leftfieldFrame)
        self.hostnameEntry.grid(row=rowCount, column=1)
        self.hostnameEntry.insert(0, self.prefValues['hostname'])
        rowCount+=1

        # Field for DPID
        Label(self.leftfieldFrame, text="DPID:").grid(row=rowCount, sticky=E)
        self.dpidEntry = Entry(self.leftfieldFrame)
        self.dpidEntry.grid(row=rowCount, column=1)
        if 'dpid' in self.prefValues:
            self.dpidEntry.insert(0, self.prefValues['dpid'])
        rowCount+=1

        # Field for Netflow
        Label(self.leftfieldFrame, text="Enable NetFlow:").grid(row=rowCount, sticky=E)
        self.nflow = IntVar()
        self.nflowButton = Checkbutton(self.leftfieldFrame, variable=self.nflow)
        self.nflowButton.grid(row=rowCount, column=1, sticky=W)
        if 'netflow' in self.prefValues:
            if self.prefValues['netflow'] == '0':
                self.nflowButton.deselect()
            else:
                self.nflowButton.select()
        else:
            self.nflowButton.deselect()
        rowCount+=1

        # Field for sflow
        Label(self.leftfieldFrame, text="Enable sFlow:").grid(row=rowCount, sticky=E)
        self.specifiedsflow = IntVar()
        self.sflowButton = Checkbutton(self.leftfieldFrame, variable=self.sflow)
        self.sflowButton.grid(row=rowCount, column=1, sticky=W)
        if 'sflow' in self.prefValues:
            if self.prefValues['sflow'] == '0':
                self.sflowButton.deselect()
            else:
                self.sflowButton.select()
        else:
            self.sflowButton.deselect()
        rowCount+=1

        # Selection of switch type
        Label(self.leftfieldFrame, text="Switch Type:").grid(row=rowCount, sticky=E)
        self.switchType = StringVar(self.leftfieldFrame)
        self.switchTypeMenu = OptionMenu(self.leftfieldFrame, self.switchType, "Default", "Open vSwitch Kernel Mode", "Indigo Virtual Switch", "Userspace Switch", "Userspace Switch inNamespace")
        self.switchTypeMenu.grid(row=rowCount, column=1, sticky=W)
        if 'switchType' in self.prefValues:
            switchTypePref = self.prefValues['switchType']
            if switchTypePref == 'ivs':
                self.switchType.set("Indigo Virtual Switch")
            elif switchTypePref == 'userns':
                self.switchType.set("Userspace Switch inNamespace")
            elif switchTypePref == 'user':
                self.switchType.set("Userspace Switch")
            elif switchTypePref == 'ovs':
                self.switchType.set("Open vSwitch Kernel Mode")
            else:
                self.switchType.set("Default")
        else:
            self.switchType.set("Default")
        rowCount+=1

        # Field for Switch IP
        Label(self.leftfieldFrame, text="IP Address:").grid(row=rowCount, sticky=E)
        self.ipEntry = Entry(self.leftfieldFrame)
        self.ipEntry.grid(row=rowCount, column=1)
        if 'switchIP' in self.prefValues:
            self.ipEntry.insert(0, self.prefValues['switchIP'])
        rowCount+=1

        # Field for DPCTL port
        Label(self.leftfieldFrame, text="DPCTL port:").grid(row=rowCount, sticky=E)
        self.dpctlEntry = Entry(self.leftfieldFrame)
        self.dpctlEntry.grid(row=rowCount, column=1)
        if 'dpctl' in self.prefValues:
            self.dpctlEntry.insert(0, self.prefValues['dpctl'])
        rowCount+=1

        # External Interfaces
        Label(self.rightfieldFrame, text="External Interface:").grid(row=0, sticky=E)
        self.b = Button( self.rightfieldFrame, text='Add', command=self.addInterface)
        self.b.grid(row=0, column=1)

        self.interfaceFrame = VerticalScrolledTable(self.rightfieldFrame, rows=0, columns=1, title='External Interfaces')
        self.interfaceFrame.grid(row=1, column=0, sticky='nswe', columnspan=2)
        self.tableFrame = self.interfaceFrame.interior

        # Add defined interfaces
        for externalInterface in externalInterfaces:
            self.tableFrame.addRow(value=[externalInterface])

        self.commandFrame = Frame(self.rootFrame)
        self.commandFrame.grid(row=1, column=0, sticky='nswe', columnspan=2)
        self.commandFrame.columnconfigure(1, weight=1)
        # Start command
        Label(self.commandFrame, text="Start Command:").grid(row=0, column=0, sticky=W)
        self.startEntry = Entry(self.commandFrame)
        self.startEntry.grid(row=0, column=1,  sticky='nsew')
        if 'startCommand' in self.prefValues:
            self.startEntry.insert(0, str(self.prefValues['startCommand']))
        # Stop command
        Label(self.commandFrame, text="Stop Command:").grid(row=1, column=0, sticky=W)
        self.stopEntry = Entry(self.commandFrame)
        self.stopEntry.grid(row=1, column=1, sticky='nsew')
        if 'stopCommand' in self.prefValues:
            self.stopEntry.insert(0, str(self.prefValues['stopCommand']))

    def addInterface( self ):
        self.tableFrame.addRow()

    def defaultDpid( self, name):
        "Derive dpid from switch name, s1 -> 1"
        assert self  # satisfy pylint and allow contextual override
        try:
            dpid = int( re.findall( r'\d+', name )[ 0 ] )
            dpid = hex( dpid )[ 2: ]
            return dpid
        except IndexError:
            return None
            #raise Exception( 'Unable to derive default datapath ID - '
            #                 'please either specify a dpid or use a '
            #                 'canonical switch name such as s23.' )

    def apply(self):
        externalInterfaces = []
        for row in range(self.tableFrame.rows):
            # debug( 'Interface is ' + self.tableFrame.get(row, 0), '\n' )
            if len(self.tableFrame.get(row, 0)) > 0:
                externalInterfaces.append(self.tableFrame.get(row, 0))

        dpid = self.dpidEntry.get()
        if (self.defaultDpid(self.hostnameEntry.get()) is None
           and len(dpid) == 0):
            showerror(title="Error",
                          message= 'Unable to derive default datapath ID - '
                             'please either specify a DPID or use a '
                             'canonical switch name such as s23.' )


        results = {'externalInterfaces':externalInterfaces,
                   'hostname':self.hostnameEntry.get(),
                   'dpid':dpid,
                   'startCommand':self.startEntry.get(),
                   'stopCommand':self.stopEntry.get(),
                   'sflow':str(self.sflow.get()),
                   'netflow':str(self.nflow.get()),
                   'dpctl':self.dpctlEntry.get(),
                   'switchIP':self.ipEntry.get()}
        sw = self.switchType.get()
        if sw == 'Indigo Virtual Switch':
            results['switchType'] = 'ivs'
            if StrictVersion(MININET_VERSION) < StrictVersion('2.1'):
                self.ovsOk = False
                showerror(title="Error",
                          message='MiniNet version 2.1+ required. You have '+VERSION+'.')
        elif sw == 'Userspace Switch inNamespace':
            results['switchType'] = 'userns'
        elif sw == 'Userspace Switch':
            results['switchType'] = 'user'
        elif sw == 'Open vSwitch Kernel Mode':
            results['switchType'] = 'ovs'
        else:
            results['switchType'] = 'default'
        self.result = results

class InterfaceSelector(CustomDialog):
    """ Written by Joseph Wilkin """
    """ Window to select which external interfaces to bind the host """
    """ opened whenever a host is connected to a hardware switch """

    def __init__(self, master, title, hostName, externalInterfaces, externalInterfaceBindings):
        self.hostName = hostName
        self.externalInterfaces = externalInterfaces
        self.externalInterfaceBindings = externalInterfaceBindings

        self.choices = {}
        for i in range(len(self.externalInterfaces)):
            if self.externalInterfaces[i] not in self.externalInterfaceBindings:
                self.choices.update({self.externalInterfaces[i]: i + 1})
        self.result = None
        CustomDialog.__init__(self, master, title)

    def body(self, master):
        w = Label(master, text=f"Please select which external\ninterface to bind {self.hostName} to:", font="50")
        w.pack(pady=15, padx=15)

        self.v = StringVar(master, "1")

        for (text, value) in self.choices.items():
            Radiobutton(master, text=text, variable=self.v,
                        value=value).pack(ipady=5)        

    def okAction(self):
        for key, val in self.choices.items():
            if str(val) == str(self.v.get()):
                self.result = key
        self.apply()
        self.top.destroy()

class HardwareTableOptionsDialog(CustomDialog):
    """ Written by Joseph Wilkin """
    """ Match-Action Table Interface for the Hardware Switch """

    def __init__(self, master, title):
        self.tables = self.getTables()
        CustomDialog.__init__(self, master, title)

    def body(self, master):
        self.rootFrame = master
        self.entryFrame = Frame(self.rootFrame)
        self.entryFrame.grid(row=3, column=1, sticky='nswe', columnspan=6, padx=20, pady=(10, 20))

        Label(self.rootFrame, text="Table:").grid(row=1, column=1, sticky='e', padx=10, pady=(10, 0))
        self.combobox = Combobox(self.rootFrame, values=self.tables)
        self.combobox.grid(row=1, column=2, sticky='we', pady=(10, 0), padx=(0, 10))
        self.getEntriesButton = Button(self.rootFrame, text="Select", command=self.getEntries)
        self.getEntriesButton.grid(row=1, column=3, sticky='w', pady=(10, 0))

        self.entryFrame = VerticalScrolledTable(self.entryFrame, rows=0, columns=3, title='Entries')
        self.entryFrame.grid(row=3, column=1, sticky='nswe', columnspan=4)
        self.entryTableFrame = self.entryFrame.interior
        self.entryTableFrame.addRow(value=['Key', 'Action', 'Action Data'], readonly=True)
    
    def getTables(self):
        # create TCP socket and connect to server program running on hardware switch
        s = socket.socket()
        port = 12345
        s.connect(('10.5.52.9', port))

        # send "get tables" to server to request tables from server
        req = "get tables"
        s.send(req.encode())

        # get response from server
        reply = s.recv(1024).decode()
        tables_dict = json.loads(reply)
        s.close()
        return tables_dict['tables']

    def getEntries(self):

        # get selected table
        selected_table = self.combobox.get()
        if selected_table == "":
            return
        
        # get rid of previous rows
        self.entryTableFrame.clear()
        self.entryTableFrame.addRow(value=['Key', 'Action', 'Action Data'], readonly=True)

        # create TCP socket and connect to server program running on hardware switch
        s = socket.socket()
        port = 12345
        s.connect(('10.5.52.9', port))

        # send selected table to server to request its entries from server
        s.send(selected_table.encode())

        # get response from server
        reply = s.recv(1024).decode()
        entries_dict = json.loads(reply)
        s.close()
        
        for entry in entries_dict["entries"]:
            #data = entry[0]
            #key = entry[1]
            print("data:", entry[0])
            print("key:", entry[1])
            all_keys = ""
            for key in list(entry[1].keys()):
                all_keys = all_keys + (key + " : " + str(hex(entry[1][key]["value"])) + ", ")
            all_keys = all_keys[:-2]

            all_data = ""
            data_keys = []
            for key in list(entry[0].keys()):
                if key != 'action_name' and key != 'is_default_entry':
                    data_keys.append(key)

            for key in data_keys:
                 all_data = all_data + (key + " : " + str(entry[0][key]) + ", ")
            all_data = all_data[:-2]

            self.entryTableFrame.addRow(value=[all_keys, entry[0]['action_name'], all_data], readonly=True)

class TableOptionsDialog(CustomDialog):

    """ Written by Joseph Wilkin """
    """ BMv2 Software Switch Match-Action Table Interface """

    def __init__(self, master, title, node):
        self.node = node
        # get tables and table metadata
        self.tableList = self.getTables()

        # get list of tables' names
        self.tables = []
        for t in self.tableList:
            self.tables.append(t["table"])

        # populate list with entries that are currently in the tables
        self.updateEntries()

        CustomDialog.__init__(self, master, title)

    def body(self, master):
 
        self.rootFrame = master
        self.entryFrame = Frame(self.rootFrame)
        self.entryFrame.grid(row=3, column=1, sticky='nswe', columnspan=6, padx=20, pady=(10, 20))

        Label(self.rootFrame, text="Table:").grid(row=1, column=1, sticky='e', padx=10, pady=(10, 0))
        self.combobox = Combobox(self.rootFrame, values=self.tables)
        self.combobox.grid(row=1, column=2, sticky='we', pady=(10, 0), padx=(0, 10))
        self.getEntriesButton = Button(self.rootFrame, text="Select", command=self.getEntries)
        self.getEntriesButton.grid(row=1, column=3, sticky='w', pady=(10, 0))

        self.addRowButton = Button(self.rootFrame, text="Add Rule", command=self.addEntry)
        self.addRowButton.grid(row=1, column=4, padx=10, pady=(10, 0))

        self.saveButton = Button(self.rootFrame, text="Save Rules", command=self.save)
        self.saveButton.grid(row=1, column=5, padx=10, pady=(10,0))

        self.addFromFileButton = Button(self.rootFrame, text="Import Rules from File", command=self.addEntriesFromFile)
        self.addFromFileButton.grid(row=1, column=6, padx=(0, 10), pady=(10, 0))

        self.entryFrame = VerticalScrolledTable(self.entryFrame, rows=0, columns=3, title='Entries')
        self.entryFrame.grid(row=3, column=1, sticky='nswe', columnspan=4)
        self.entryTableFrame = self.entryFrame.interior
        self.entryTableFrame.addRow(value=['Key', 'Action', 'Action Data'], readonly=True)

        entries = []
        for entry in entries:
            self.entryTableFrame.addRow(value=entry) 
    
    def addEntry( self ):
        self.entryTableFrame.addRow(value=["", "", ""])

    def save(self):
        # remove the rules from the currently selected table, and then add the rules in the table to the switch

        selectedTable = self.combobox.get()
        if selectedTable == "":
            return
        
        # clear rules off the switch, and replace them with rules from the table
        self.clearTable(selectedTable)
        self.addEntries(selectedTable)

    def getEntries(self):
        # add rows to table interface

        # populate list with entries that are currently in the tables
        self.updateEntries()

        # get rid of previous rows
        self.entryTableFrame.clear()
        self.entryTableFrame.addRow(value=['Key', 'Action', 'Action Data'], readonly=True)
    
        # get selected table
        selected_table = self.combobox.get()
        if selected_table == "":
            return
        else:
            # add rows to table
            for t in range(len(self.tableList)):
                if self.tableList[t]["table"] == selected_table:
                    for entry in self.tableList[t]["entries"]:
                        # append all keys together
                        keys = ""
                        for key in entry["keys"]:
                            keys = keys + (key + ", ")
                        # append all action data together
                        allActionData = ""
                        for actionData in entry["action_data"]:
                            allActionData = allActionData + (actionData + ", ")
                        # add row to table
                        self.entryTableFrame.addRow(value=[keys[:-2], entry["action"], allActionData[:-2]])
                    break
            
    def getTables(self):
        # open process on node and enter simple_switch_CLI
        process = self.node.popen("simple_switch_CLI", stdin=-1, stdout=-1, stderr=-1)
        # get run show_tables command on process and get output
        out, _ = process.communicate(input=b"show_tables")
        process.kill()
        # parse output and get list of tables and metadata
        tables = decode(out).split("\n")[3:-2]
        tables[0] = tables[0][12:]
        tableList = []
        for i in range(len(tables)):
            tableList.append({"table": tables[i].split()[0], "metadata": " ".join(tables[i].split()[1:]), "entries": []})
        return tableList

    def updateEntries(self):

        # get entries currently present in each table

        # get rid of old entries
        for table in self.tableList:
            table['entries'] = []
     
        # get new entries
        for t in range(len(self.tableList)):
            process = self.node.popen("simple_switch_CLI", stdin=-1, stdout=-1, stderr=-1)
            out, _ = process.communicate(input=bytes(f"table_dump {self.tableList[t]['table']}", 'utf-8'))
            process.kill()
            lines = out.decode().split("\n")
            for i in range(len(lines)):
                if lines[i] == "**********":
                    number = lines[i + 1].split()[2]
                    i += 3
                    keys = []
                    while lines[i].split()[0] == "*":
                        if len(lines[i].split()) == 5:
                            keys.append(lines[i].split()[1] + " : " + lines[i].split()[3] + " " + lines[i].split()[4])
                        elif len(lines[i].split()) == 4:
                            keys.append(lines[i].split()[1][:-1] + " : " + lines[i].split()[2] + " " + lines[i].split()[3])
                        i += 1
                    action = lines[i].split()[2]
                    action_data = []
                    try:
                        if len(lines[i].split()) == 5:
                            action_data.append(lines[i].split()[4])
                        elif len(lines[i].split()) > 5:
                            j = 4
                            while j < len(lines[i].split()) - 1:
                                action_data.append(lines[i].split()[j][:-1])
                                j += 1
                            action_data.append(lines[i].split()[j])
                    except:
                        pass
                    self.tableList[t]["entries"].append({"number": number, "keys": keys, "action": action, "action_data": action_data})
        
        
    def okAction(self):
        self.apply()
        self.top.destroy()

    def clearTable(self, table):
        # clear the entries of a table
        process = self.node.popen("simple_switch_CLI", stdin=-1, stdout=-1, stderr=-1)
        _, _ = process.communicate(input=bytes(f"table_clear {table}", "utf-8"))
        process.kill()

    def addEntries(self, table):

        # if there are no rules in table, return
        if len(self.entryTableFrame._widgets) <= 1:
            return

        errors = False

        # add all rules currently in the table to the switch
        for row in self.entryTableFrame._widgets[1:]:
            if (not row[0].get().isspace() and not row[1].get().isspace() and not row[2].get().isspace()) and (not row[0].get() == "" and not row[1].get() == "" and not row[2].get() == ""):
                action = row[1].get()
                key = ""
                for i in row[0].get().split(", "):
                    key = key + ("0x" + i.split()[3] + " ")
                key = key[:-1]
                
                actionData = ""
                for i in row[2].get().split(", "):
                    actionData = actionData + ("0x" + i + " ")
                actionData = actionData[:-1]

                # start process and enter simple_switch_CLI
                process = self.node.popen("simple_switch_CLI", stdin=-1, stdout=-1, stderr=-1)
                print("running command:", f"table_add {table} {action} {key} => {actionData}")
                out, _ = process.communicate(input=bytes(f"table_add {table} {action} {key} => {actionData}", "utf-8"))
                print(out.decode())
                if 'Entry has been added' not in out.decode():
                    errors = True
                process.kill()

        if not errors:
            showinfo(title="MiniEdit", message=f'Rules have successfully been saved to switch.')
            self.updateEntries()
        else:
            showwarning(title="MiniEdit", message=f'Errors may have occured when saving rules to switch. Please see the command line output for more information.')

            

    def addEntriesFromFile(self):
        # add new entries to a table from a file
        myFormats = [
            ('All Files','*'),
        ]
        self.f = tkFileDialog.askopenfile(filetypes=myFormats, mode='rb')
        if self.f is None:
            return

        print("Selected file", str(self.f.name))

        errors = False
        
        # open file in read only mode
        f = open(self.f.name, 'r')
        for line in f:
            if not line.isspace():
                process = self.node.popen("simple_switch_CLI", stdin=-1, stdout=-1, stderr=-1)
                out, _ = process.communicate(input=bytes(line, "utf-8"))
                print(out.decode())
                if 'Entry has been added' not in out.decode():
                    errors = True
                process.kill()
        # close file    
        f.close()
        
        if not errors:
            showinfo(title="MiniEdit", message=f'Rules have successfully been added to switch.')
        else:
            showwarning(title="MiniEdit", message=f'Errors may have occured when adding rules to switch. Please see the command line output for more information.')


                

class VerticalScrolledTable(LabelFrame):
    """A pure Tkinter scrollable frame that actually works!

    * Use the 'interior' attribute to place widgets inside the scrollable frame
    * Construct and pack/place/grid normally
    * This frame only allows vertical scrolling

    """
    def __init__(self, parent, rows=2, columns=2, title=None, **kw):
        LabelFrame.__init__(self, parent, text=title, padx=5, pady=5, **kw)

        # create a canvas object and a vertical scrollbar for scrolling it
        vscrollbar = Scrollbar(self, orient=VERTICAL)
        vscrollbar.pack(fill=Y, side=RIGHT, expand=FALSE)
        canvas = Canvas(self, bd=0, highlightthickness=0,
                        yscrollcommand=vscrollbar.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=TRUE)
        vscrollbar.config(command=canvas.yview)

        # reset the view
        canvas.xview_moveto(0)
        canvas.yview_moveto(0)

        # create a frame inside the canvas which will be scrolled with it
        self.interior = interior = TableFrame(canvas, rows=rows, columns=columns)
        interior_id = canvas.create_window(0, 0, window=interior,
                                           anchor=NW)

        # track changes to the canvas and frame width and sync them,
        # also updating the scrollbar
        def _configure_interior(_event):
        # update the scrollbars to match the size of the inner frame
            size = (interior.winfo_reqwidth(), interior.winfo_reqheight())
            canvas.config(scrollregion="0 0 %s %s" % size)
            if interior.winfo_reqwidth() != canvas.winfo_width():
            # update the canvas's width to fit the inner frame
                canvas.config(width=interior.winfo_reqwidth())
        interior.bind('<Configure>', _configure_interior)

        def _configure_canvas(_event):
            if interior.winfo_reqwidth() != canvas.winfo_width():
                # update the inner frame's width to fill the canvas
                canvas.itemconfigure(interior_id, width=canvas.winfo_width())
        canvas.bind('<Configure>', _configure_canvas)

class TableFrame(Frame):
    def __init__(self, parent, rows=2, columns=2):

        Frame.__init__(self, parent, background="black")
        self._widgets = []
        self.rows = rows
        self.columns = columns
        for row in range(rows):
            current_row = []
            for column in range(columns):
                label = Entry(self, borderwidth=0)
                label.grid(row=row, column=column, sticky="wens", padx=1, pady=1)
                current_row.append(label)
            self._widgets.append(current_row)

    def set(self, row, column, value):
        widget = self._widgets[row][column]
        widget.insert(0, value)

    def get(self, row, column):
        widget = self._widgets[row][column]
        return widget.get()

    def addRow( self, value=None, readonly=False ):
        # debug( "Adding row " + str(self.rows +1), '\n' )
        current_row = []
        for column in range(self.columns):
            if column == 0:
                label = Entry(self, width=50, borderwidth=0)
            elif type(value[column]) == list:
                if len(value[column]) >= 2:
                    label = Combobox(self, values=value[column])
                else:
                    label = Entry(self, borderwidth=0)
                    value[column] = value[column][0]
            else:
                label = Entry(self, borderwidth=0)
            label.grid(row=self.rows, column=column, sticky="wens", padx=1, pady=1)
            if value is not None and type(value[column]) is list:
                label.insert(0, value[column][0])
            elif value is not None:
                label.insert(0, value[column])
            if readonly:
                label.configure(state='readonly', justify=CENTER)
            current_row.append(label)
        self._widgets.append(current_row)
        self.update_idletasks()
        self.rows += 1

    def clear(self):
        for widget in self._widgets:
            for w in widget:
                w.grid_forget()
        self._widgets = []
        self.rows = 0
        self.update_idletasks()



class LinkDialog(tkSimpleDialog.Dialog):

    def __init__(self, parent, title, linkDefaults):

        self.linkValues = linkDefaults

        tkSimpleDialog.Dialog.__init__(self, parent, title)

    def body(self, master):

        self.var = StringVar(master)
        Label(master, text="Bandwidth:").grid(row=0, sticky=E)
        self.e1 = Entry(master)
        self.e1.grid(row=0, column=1)
        Label(master, text="Mbit").grid(row=0, column=2, sticky=W)
        if 'bw' in self.linkValues:
            self.e1.insert(0,str(self.linkValues['bw']))

        Label(master, text="Delay:").grid(row=1, sticky=E)
        self.e2 = Entry(master)
        self.e2.grid(row=1, column=1)
        if 'delay' in self.linkValues:
            self.e2.insert(0, self.linkValues['delay'])

        Label(master, text="Loss:").grid(row=2, sticky=E)
        self.e3 = Entry(master)
        self.e3.grid(row=2, column=1)
        Label(master, text="%").grid(row=2, column=2, sticky=W)
        if 'loss' in self.linkValues:
            self.e3.insert(0, str(self.linkValues['loss']))

        Label(master, text="Max Queue size:").grid(row=3, sticky=E)
        self.e4 = Entry(master)
        self.e4.grid(row=3, column=1)
        if 'max_queue_size' in self.linkValues:
            self.e4.insert(0, str(self.linkValues['max_queue_size']))

        Label(master, text="Jitter:").grid(row=4, sticky=E)
        self.e5 = Entry(master)
        self.e5.grid(row=4, column=1)
        if 'jitter' in self.linkValues:
            self.e5.insert(0, self.linkValues['jitter'])

        Label(master, text="Speedup:").grid(row=5, sticky=E)
        self.e6 = Entry(master)
        self.e6.grid(row=5, column=1)
        if 'speedup' in self.linkValues:
            self.e6.insert(0, str(self.linkValues['speedup']))

        return self.e1 # initial focus

    def apply(self):
        self.result = {}
        if len(self.e1.get()) > 0:
            self.result['bw'] = int(self.e1.get())
        if len(self.e2.get()) > 0:
            self.result['delay'] = self.e2.get()
        if len(self.e3.get()) > 0:
            self.result['loss'] = int(self.e3.get())
        if len(self.e4.get()) > 0:
            self.result['max_queue_size'] = int(self.e4.get())
        if len(self.e5.get()) > 0:
            self.result['jitter'] = self.e5.get()
        if len(self.e6.get()) > 0:
            self.result['speedup'] = int(self.e6.get())

class ControllerDialog(tkSimpleDialog.Dialog):

    def __init__(self, parent, title, ctrlrDefaults=None):

        if ctrlrDefaults:
            self.ctrlrValues = ctrlrDefaults

        tkSimpleDialog.Dialog.__init__(self, parent, title)

    def body(self, master):

        self.var = StringVar(master)
        self.protcolvar = StringVar(master)

        rowCount=0
        # Field for Hostname
        Label(master, text="Name:").grid(row=rowCount, sticky=E)
        self.hostnameEntry = Entry(master)
        self.hostnameEntry.grid(row=rowCount, column=1)
        self.hostnameEntry.insert(0, self.ctrlrValues['hostname'])
        rowCount+=1

        # Field for Remove Controller Port
        Label(master, text="Controller Port:").grid(row=rowCount, sticky=E)
        self.e2 = Entry(master)
        self.e2.grid(row=rowCount, column=1)
        self.e2.insert(0, self.ctrlrValues['remotePort'])
        rowCount+=1

        # Field for Controller Type
        Label(master, text="Controller Type:").grid(row=rowCount, sticky=E)
        controllerType = self.ctrlrValues['controllerType']
        self.o1 = OptionMenu(master, self.var, "Remote Controller", "In-Band Controller", "OpenFlow Reference", "OVS Controller")
        self.o1.grid(row=rowCount, column=1, sticky=W)
        if controllerType == 'ref':
            self.var.set("OpenFlow Reference")
        elif controllerType == 'inband':
            self.var.set("In-Band Controller")
        elif controllerType == 'remote':
            self.var.set("Remote Controller")
        else:
            self.var.set("OVS Controller")
        rowCount+=1

        # Field for Controller Protcol
        Label(master, text="Protocol:").grid(row=rowCount, sticky=E)
        if 'controllerProtocol' in self.ctrlrValues:
            controllerProtocol = self.ctrlrValues['controllerProtocol']
        else:
            controllerProtocol = 'tcp'
        self.protcol = OptionMenu(master, self.protcolvar, "TCP", "SSL")
        self.protcol.grid(row=rowCount, column=1, sticky=W)
        if controllerProtocol == 'ssl':
            self.protcolvar.set("SSL")
        else:
            self.protcolvar.set("TCP")
        rowCount+=1

        # Field for Remove Controller IP
        remoteFrame= LabelFrame(master, text='Remote/In-Band Controller', padx=5, pady=5)
        remoteFrame.grid(row=rowCount, column=0, columnspan=2, sticky=W)

        Label(remoteFrame, text="IP Address:").grid(row=0, sticky=E)
        self.e1 = Entry(remoteFrame)
        self.e1.grid(row=0, column=1)
        self.e1.insert(0, self.ctrlrValues['remoteIP'])
        rowCount+=1

        return self.hostnameEntry # initial focus

    def apply(self):
        self.result = { 'hostname': self.hostnameEntry.get(),
                        'remoteIP': self.e1.get(),
                        'remotePort': int(self.e2.get())}

        controllerType = self.var.get()
        if controllerType == 'Remote Controller':
            self.result['controllerType'] = 'remote'
        elif controllerType == 'In-Band Controller':
            self.result['controllerType'] = 'inband'
        elif controllerType == 'OpenFlow Reference':
            self.result['controllerType'] = 'ref'
        else:
            self.result['controllerType'] = 'ovsc'
        controllerProtocol = self.protcolvar.get()
        if controllerProtocol == 'SSL':
            self.result['controllerProtocol'] = 'ssl'
        else:
            self.result['controllerProtocol'] = 'tcp'

class ToolTip(object):

    def __init__(self, widget):
        self.widget = widget
        self.tipwindow = None
        self.id = None
        self.x = self.y = 0

    def showtip(self, text):
        "Display text in tooltip window"
        self.text = text
        if self.tipwindow or not self.text:
            return
        x, y, _cx, cy = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 27
        y = y + cy + self.widget.winfo_rooty() +27
        self.tipwindow = tw = Toplevel(self.widget)
        tw.wm_overrideredirect(1)
        tw.wm_geometry("+%d+%d" % (x, y))
        try:
            # For Mac OS
            # pylint: disable=protected-access
            tw.tk.call("::tk::unsupported::MacWindowStyle",
                       "style", tw._w,
                       "help", "noActivates")
            # pylint: enable=protected-access
        except TclError:
            pass
        label = Label(tw, text=self.text, justify=LEFT,
                      background="#ffffe0", relief=SOLID, borderwidth=1,
                      font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)

    def hidetip(self):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()

class MiniEdit( Frame ):

    "A simple network editor for Mininet."

    def __init__( self, parent=None, cheight=600, cwidth=1000 ):

        self.defaultIpBase='10.0.0.0/8'

        self.nflowDefaults = {'nflowTarget':'',
                              'nflowTimeout':'600',
                              'nflowAddId':'0'}
        self.sflowDefaults = {'sflowTarget':'',
                              'sflowSampling':'400',
                              'sflowHeader':'128',
                              'sflowPolling':'30'}

        self.appPrefs={
            "ipBase": self.defaultIpBase,
            "startCLI": "0",
            "terminalType": 'xterm',
            "switchType": 'ovs',
            "dpctl": '',
            'sflow':self.sflowDefaults,
            'netflow':self.nflowDefaults,
            'openFlowVersions':{'ovsOf10':'1',
                                'ovsOf11':'0',
                                'ovsOf12':'0',
                                'ovsOf13':'0'}

        }


        Frame.__init__( self, parent )
        self.action = None
        self.appName = 'MiniEdit'
        self.fixedFont = tkFont.Font ( family="DejaVu Sans Mono", size="14" )

        # Style
        self.font = ( 'Geneva', 9 )
        self.smallFont = ( 'Geneva', 7 )
        self.bg = 'white'

        # Title
        self.top = self.winfo_toplevel()
        self.top.title( self.appName )

        # Menu bar
        self.createMenubar()

        # Editing canvas
        self.cheight, self.cwidth = cheight, cwidth
        self.cframe, self.canvas = self.createCanvas()

        # Toolbar
        self.controllers = {}

        # Toolbar
        self.images = miniEditImages()
        self.buttons = {}
        self.active = None
        self.tools = ( 'Select', 'Host', 'P4Switch', 'HardwareSwitch', 'Switch', 'LegacySwitch', 'LegacyRouter', 'NetLink', 'Controller')
        self.customColors = { 'Switch': 'darkGreen', 'Host': 'blue' }
        self.toolbar = self.createToolbar()

        # Layout
        self.toolbar.grid( column=0, row=0, sticky='nsew')
        self.cframe.grid( column=1, row=0 )
        self.columnconfigure( 1, weight=1 )
        self.rowconfigure( 0, weight=1 )
        self.pack( expand=True, fill='both' )

        # About box
        self.aboutBox = None

        # Initialize node data
        self.nodeBindings = self.createNodeBindings()
        self.nodePrefixes = { 'LegacyRouter': 'r', 'LegacySwitch': 's', 'Switch': 's', 'Host': 'h' , 'Controller': 'c', 'P4Switch': 'p', 'HardwareSwitch': 'w'}
        self.widgetToItem = {}
        self.itemToWidget = {}

        # Initialize external interfaces
        # get list of external interfaces that begin with "enp" from command line
        self.externalInterfaces = os.listdir('/sys/class/net/')
        for intf in self.externalInterfaces:
            if not re.match('^enp.*', intf):
                self.externalInterfaces.remove(intf)
        
        # Initialize external interface bindings
        self.externalInterfaceBindings = {}

        # Initialize counter for connections to hardware switch
        self.hwConnectionsCounter = 0

        # Initialize counter for hardware switches
        # (right now only one is allowed)
        self.hwSwitches = 0

        # Initialize link tool
        self.link = self.linkWidget = None

        # Selection support
        self.selection = None

        # Keyboard bindings
        self.bind( '<Control-q>', lambda event: self.quit() )
        self.bind( '<KeyPress-Delete>', self.deleteSelection )
        self.bind( '<KeyPress-BackSpace>', self.deleteSelection )
        self.focus()

        self.hostPopup = Menu(self.top, tearoff=0)
        self.hostPopup.add_command(label='Host Options', font=self.font)
        self.hostPopup.add_separator()
        self.hostPopup.add_command(label='Properties', font=self.font, command=self.hostDetails )

        self.hostRunPopup = Menu(self.top, tearoff=0)
        self.hostRunPopup.add_command(label='Host Options', font=self.font)
        self.hostRunPopup.add_separator()
        self.hostRunPopup.add_command(label='Terminal', font=self.font, command=self.xterm )

        self.legacyRouterRunPopup = Menu(self.top, tearoff=0)
        self.legacyRouterRunPopup.add_command(label='Router Options', font=self.font)
        self.legacyRouterRunPopup.add_separator()
        self.legacyRouterRunPopup.add_command(label='Terminal', font=self.font, command=self.xterm )

        self.switchPopup = Menu(self.top, tearoff=0)
        self.switchPopup.add_command(label='Switch Options', font=self.font)
        self.switchPopup.add_separator()
        self.switchPopup.add_command(label='Properties', font=self.font, command=self.switchDetails )

        self.switchRunPopup = Menu(self.top, tearoff=0)
        self.switchRunPopup.add_command(label='Switch Options', font=self.font)
        self.switchRunPopup.add_separator()
        self.switchRunPopup.add_command(label='List bridge details', font=self.font, command=self.listBridge )

        self.p4SwitchPopup = Menu(self.top, tearoff=0)
        self.p4SwitchPopup.add_command(label='Docker Options', font=self.font)
        self.p4SwitchPopup.add_separator()
        self.p4SwitchPopup.add_command(label='Properties', font=self.font, command=self.p4SwitchDetails )

        self.p4SwitchRunPopup = Menu(self.top, tearoff=0)
        self.p4SwitchRunPopup.add_command(label='Table Options', font=self.font, command=self.p4SwitchOptions )
        self.p4SwitchRunPopup.add_separator()
        self.p4SwitchRunPopup.add_command(label='Terminal', font=self.font, command=self.xterm )

        self.hardwareSwitchRunPopup = Menu(self.top, tearoff=0)
        self.hardwareSwitchRunPopup.add_command(label='Table Options', font=self.font, command=self.hardwareSwitchOptions)

        self.linkPopup = Menu(self.top, tearoff=0)
        self.linkPopup.add_command(label='Link Options', font=self.font)
        self.linkPopup.add_separator()
        self.linkPopup.add_command(label='Properties', font=self.font, command=self.linkDetails )

        self.linkRunPopup = Menu(self.top, tearoff=0)
        self.linkRunPopup.add_command(label='Link Options', font=self.font)
        self.linkRunPopup.add_separator()
        self.linkRunPopup.add_command(label='Link Up', font=self.font, command=self.linkUp )
        self.linkRunPopup.add_command(label='Link Down', font=self.font, command=self.linkDown )

        self.controllerPopup = Menu(self.top, tearoff=0)
        self.controllerPopup.add_command(label='Controller Options', font=self.font)
        self.controllerPopup.add_separator()
        self.controllerPopup.add_command(label='Properties', font=self.font, command=self.controllerDetails )


        # Event handling initalization
        self.linkx = self.linky = self.linkItem = None
        self.lastSelection = None

        # Model initialization
        self.links = {}
        self.hostOpts = {}
        self.switchOpts = {}
        self.hostCount = 0
        self.switchCount = 0
        self.controllerCount = 0
        self.net = None

        # Close window gracefully
        Wm.wm_protocol( self.top, name='WM_DELETE_WINDOW', func=self.quit )

    def quit( self ):
        "Stop our network, if any, then quit."
        self.stop()
        Frame.quit( self )

    def createMenubar( self ):
        "Create our menu bar."

        font = self.font

        mbar = Menu( self.top, font=font )
        self.top.configure( menu=mbar )


        fileMenu = Menu( mbar, tearoff=False )
        mbar.add_cascade( label="File", font=font, menu=fileMenu )
        fileMenu.add_command( label="New", font=font, command=self.newTopology )
        fileMenu.add_command( label="Open", font=font, command=self.loadTopology )
        fileMenu.add_command( label="Save", font=font, command=self.saveTopology )
        fileMenu.add_command( label="Export Level 2 Script", font=font, command=self.exportScript )
        fileMenu.add_separator()
        fileMenu.add_command( label='Quit', command=self.quit, font=font )

        editMenu = Menu( mbar, tearoff=False )
        mbar.add_cascade( label="Edit", font=font, menu=editMenu )
        editMenu.add_command( label="Cut", font=font,
                              command=lambda: self.deleteSelection( None ) )
        editMenu.add_command( label="Preferences", font=font, command=self.prefDetails)

        runMenu = Menu( mbar, tearoff=False )
        mbar.add_cascade( label="Run", font=font, menu=runMenu )
        runMenu.add_command( label="Run", font=font, command=self.doRun )
        runMenu.add_command( label="Stop", font=font, command=self.doStop )
        fileMenu.add_separator()
        runMenu.add_command( label='Show OVS Summary', font=font, command=self.ovsShow )
        runMenu.add_command( label='Root Terminal', font=font, command=self.rootTerminal )

        # Application menu
        appMenu = Menu( mbar, tearoff=False )
        mbar.add_cascade( label="Help", font=font, menu=appMenu )
        appMenu.add_command( label='About MiniEdit', command=self.about,
                             font=font)
    # Canvas

    def createCanvas( self ):
        "Create and return our scrolling canvas frame."
        f = Frame( self )

        canvas = Canvas( f, width=self.cwidth, height=self.cheight,
                         bg=self.bg )

        # Scroll bars
        xbar = Scrollbar( f, orient='horizontal', command=canvas.xview )
        ybar = Scrollbar( f, orient='vertical', command=canvas.yview )
        canvas.configure( xscrollcommand=xbar.set, yscrollcommand=ybar.set )

        # Resize box
        resize = Label( f, bg='white' )

        # Layout
        canvas.grid( row=0, column=1, sticky='nsew')
        ybar.grid( row=0, column=2, sticky='ns')
        xbar.grid( row=1, column=1, sticky='ew' )
        resize.grid( row=1, column=2, sticky='nsew' )

        # Resize behavior
        f.rowconfigure( 0, weight=1 )
        f.columnconfigure( 1, weight=1 )
        f.grid( row=0, column=0, sticky='nsew' )
        f.bind( '<Configure>', lambda event: self.updateScrollRegion() )

        # Mouse bindings
        canvas.bind( '<ButtonPress-1>', self.clickCanvas )
        canvas.bind( '<B1-Motion>', self.dragCanvas )
        canvas.bind( '<ButtonRelease-1>', self.releaseCanvas )

        return f, canvas

    def updateScrollRegion( self ):
        "Update canvas scroll region to hold everything."
        bbox = self.canvas.bbox( 'all' )
        if bbox is not None:
            self.canvas.configure( scrollregion=( 0, 0, bbox[ 2 ],
                                   bbox[ 3 ] ) )

    def canvasx( self, x_root ):
        "Convert root x coordinate to canvas coordinate."
        c = self.canvas
        return c.canvasx( x_root ) - c.winfo_rootx()

    def canvasy( self, y_root ):
        "Convert root y coordinate to canvas coordinate."
        c = self.canvas
        return c.canvasy( y_root ) - c.winfo_rooty()

    # Toolbar

    def activate( self, toolName ):
        "Activate a tool and press its button."
        # Adjust button appearance
        if self.active:
            self.buttons[ self.active ].configure( relief='raised' )
        self.buttons[ toolName ].configure( relief='sunken' )
        # Activate dynamic bindings
        self.active = toolName


    @staticmethod
    def createToolTip(widget, text):
        toolTip = ToolTip(widget)
        def enter(_event):
            toolTip.showtip(text)
        def leave(_event):
            toolTip.hidetip()
        widget.bind('<Enter>', enter)
        widget.bind('<Leave>', leave)

    def createToolbar( self ):
        "Create and return our toolbar frame."

        toolbar = Frame( self )

        # Tools
        for tool in self.tools:
            cmd = partial( self.activate, tool )
            b = Button( toolbar, text=tool, font=self.smallFont, command=cmd)
            if tool in self.images:
                b.config( height=35, image=self.images[ tool ] )
                self.createToolTip(b, str(tool))
                # b.config( compound='top' )
            b.pack( fill='x' )
            self.buttons[ tool ] = b
        self.activate( self.tools[ 0 ] )

        # Spacer
        Label( toolbar, text='' ).pack()

        # Commands
        for cmd, color in [ ( 'Stop', 'darkRed' ), ( 'Run', 'darkGreen' ) ]:
            doCmd = getattr( self, 'do' + cmd )
            b = Button( toolbar, text=cmd, font=self.smallFont,
                        fg=color, command=doCmd )
            b.pack( fill='x', side='bottom' )

        return toolbar

    def doRun( self ):
        
        if not self.validateP4Switches():
            return

        "Run command."
        self.activate( 'Select' )
        for tool in self.tools:
            self.buttons[ tool ].config( state='disabled' )
        self.start()

    def validateP4Switches( self ):

        "Ensure at all P4 Switches on canvas have a specified JSON config file."

        for widget, item in self.widgetToItem.items():
            name = widget[ 'text' ]
            tags = self.canvas.gettags( item )
            if "P4Switch" in tags and 'jsonPath' not in self.switchOpts[name]:
                print(f"P4 Switch '{name}' does not have a specified JSON config file path, please specify one before running network.")
                showerror(title='Miniedit',
                          message=f"P4 Switch '{name}' does not have a specified JSON config file path, please specifiy one before running network.")
                return False
            
        return True


    def doStop( self ):
        "Stop command."
        self.stop()
        for tool in self.tools:
            self.buttons[ tool ].config( state='normal' )

    def addNode( self, node, nodeNum, x, y, name=None):
        "Add a new node to our canvas."
        if node == 'Switch':
            self.switchCount += 1
        if node == 'Host':
            self.hostCount += 1
        if node == 'Controller':
            self.controllerCount += 1
        if name is None:
            name = self.nodePrefixes[ node ] + nodeNum
        self.addNamedNode(node, name, x, y)

    def addNamedNode( self, node, name, x, y):
        "Add a new node to our canvas."
        icon = self.nodeIcon( node, name )
        item = self.canvas.create_window( x, y, anchor='c', window=icon,
                                          tags=node )
        self.widgetToItem[ icon ] = item
        self.itemToWidget[ item ] = icon
        icon.links = {}

    def convertJsonUnicode(self, text):
        "Some part of Mininet don't like Unicode"
        unicode = globals().get( 'unicode', str )
        if isinstance(text, dict):
            return {self.convertJsonUnicode(key): self.convertJsonUnicode(value) for key, value in text.items()}
        if isinstance(text, list):
            return [self.convertJsonUnicode(element) for element in text]
        if isinstance(text, unicode):  # pylint: disable=undefined-variable
            return text.encode('utf-8')
        return text

    def loadTopology( self ):
        "Load command."
        c = self.canvas

        myFormats = [
            ('Mininet Topology','*.mn'),
            ('All Files','*'),
        ]
        f = tkFileDialog.askopenfile(filetypes=myFormats, mode='rb')
        if f is None:
            return
        self.newTopology()
        #loadedTopology = self.convertJsonUnicode(json.load(f))
        loadedTopology = json.load(f)

        # Load application preferences
        if 'application' in loadedTopology:
            self.appPrefs.update(loadedTopology['application'])
            if "ovsOf10" not in self.appPrefs["openFlowVersions"]:
                self.appPrefs["openFlowVersions"]["ovsOf10"] = '0'
            if "ovsOf11" not in self.appPrefs["openFlowVersions"]:
                self.appPrefs["openFlowVersions"]["ovsOf11"] = '0'
            if "ovsOf12" not in self.appPrefs["openFlowVersions"]:
                self.appPrefs["openFlowVersions"]["ovsOf12"] = '0'
            if "ovsOf13" not in self.appPrefs["openFlowVersions"]:
                self.appPrefs["openFlowVersions"]["ovsOf13"] = '0'
            if "sflow" not in self.appPrefs:
                self.appPrefs["sflow"] = self.sflowDefaults
            if "netflow" not in self.appPrefs:
                self.appPrefs["netflow"] = self.nflowDefaults

        # Load controllers
        if 'controllers' in loadedTopology:
            if loadedTopology['version'] == '1':
                # This is old location of controller info
                hostname = 'c0'
                self.controllers = {}
                self.controllers[hostname] = loadedTopology['controllers']['c0']
                self.controllers[hostname]['hostname'] = hostname
                self.addNode('Controller', 0, float(30), float(30), name=hostname)
                icon = self.findWidgetByName(hostname)
                icon.bind('<Button-3>', self.do_controllerPopup )
            else:
                controllers = loadedTopology['controllers']
                for controller in controllers:
                    hostname = controller['opts']['hostname']
                    x = controller['x']
                    y = controller['y']
                    self.addNode('Controller', 0, float(x), float(y), name=hostname)
                    self.controllers[hostname] = controller['opts']
                    icon = self.findWidgetByName(hostname)
                    icon.bind('<Button-3>', self.do_controllerPopup )

        # Load hosts
        hosts = loadedTopology['hosts']
        for host in hosts:
            nodeNum = host['number']
            hostname = 'h'+nodeNum
            if 'hostname' in host['opts']:
                hostname = host['opts']['hostname']
            else:
                host['opts']['hostname'] = hostname
            if 'nodeNum' not in host['opts']:
                host['opts']['nodeNum'] = int(nodeNum)
            x = host['x']
            y = host['y']
            self.addNode('Host', nodeNum, float(x), float(y), name=hostname)

            # Fix JSON converting tuple to list when saving
            if 'privateDirectory' in host['opts']:
                newDirList = []
                for privateDir in host['opts']['privateDirectory']:
                    if isinstance( privateDir, list ):
                        newDirList.append((privateDir[0],privateDir[1]))
                    else:
                        newDirList.append(privateDir)
                host['opts']['privateDirectory'] = newDirList
            self.hostOpts[hostname] = host['opts']
            icon = self.findWidgetByName(hostname)
            icon.bind('<Button-3>', self.do_hostPopup )

        # Load switches
        switches = loadedTopology['switches']
        for switch in switches:
            nodeNum = switch['number']
            hostname = 's'+nodeNum
            if 'controllers' not in switch['opts']:
                switch['opts']['controllers'] = []
            if 'switchType' not in switch['opts']:
                switch['opts']['switchType'] = 'default'
            if 'hostname' in switch['opts']:
                hostname = switch['opts']['hostname']
            else:
                switch['opts']['hostname'] = hostname
            if 'nodeNum' not in switch['opts']:
                switch['opts']['nodeNum'] = int(nodeNum)
            x = switch['x']
            y = switch['y']
            if switch['opts']['switchType'] == "legacyRouter":
                self.addNode('LegacyRouter', nodeNum, float(x), float(y), name=hostname)
                icon = self.findWidgetByName(hostname)
                icon.bind('<Button-3>', self.do_legacyRouterPopup )
            elif switch['opts']['switchType'] == "legacySwitch":
                self.addNode('LegacySwitch', nodeNum, float(x), float(y), name=hostname)
                icon = self.findWidgetByName(hostname)
                icon.bind('<Button-3>', self.do_legacySwitchPopup )
            elif switch['opts']['switchType'] == "p4Switch":
                self.addNode('P4Switch', nodeNum, float(x), float(y), name=hostname)
                icon = self.findWidgetByName(hostname)
                icon.bind('<Button-3>', self.do_p4SwitchPopup )
            elif switch['opts']['switchType'] == 'hardwareSwitch':
                self.addNode('HardwareSwitch', nodeNum, float(x), float(y), name=hostname)
                icon = self.findWidgetByName(hostname)
                icon.bind('<Button-3>', self.do_hardwareSwitchPopup)
            else:
                self.addNode('Switch', nodeNum, float(x), float(y), name=hostname)
                icon = self.findWidgetByName(hostname)
                icon.bind('<Button-3>', self.do_switchPopup )
            self.switchOpts[hostname] = switch['opts']

            # create links to controllers
            if int(loadedTopology['version']) > 1:
                controllers = self.switchOpts[hostname]['controllers']
                for controller in controllers:
                    dest = self.findWidgetByName(controller)
                    dx, dy = self.canvas.coords( self.widgetToItem[ dest ] )
                    self.link = self.canvas.create_line(float(x),
                                                        float(y),
                                                        dx,
                                                        dy,
                                                        width=4,
                                                        fill='red',
                                                        dash=(6, 4, 2, 4),
                                                        tag='link' )
                    c.itemconfig(self.link, tags=c.gettags(self.link)+('control',))
                    self.addLink( icon, dest, linktype='control' )
                    self.createControlLinkBindings()
                    self.link = self.linkWidget = None
            else:
                dest = self.findWidgetByName('c0')
                dx, dy = self.canvas.coords( self.widgetToItem[ dest ] )
                self.link = self.canvas.create_line(float(x),
                                                    float(y),
                                                    dx,
                                                    dy,
                                                    width=4,
                                                    fill='red',
                                                    dash=(6, 4, 2, 4),
                                                    tag='link' )
                c.itemconfig(self.link, tags=c.gettags(self.link)+('control',))
                self.addLink( icon, dest, linktype='control' )
                self.createControlLinkBindings()
                self.link = self.linkWidget = None

        # Load links
        links = loadedTopology['links']
        for link in links:
            srcNode = link['src']
            src = self.findWidgetByName(srcNode)
            sx, sy = self.canvas.coords( self.widgetToItem[ src ] )

            destNode = link['dest']
            dest = self.findWidgetByName(destNode)
            dx, dy = self.canvas.coords( self.widgetToItem[ dest]  )

            self.link = self.canvas.create_line( sx, sy, dx, dy, width=4,
                                             fill='blue', tag='link' )
            c.itemconfig(self.link, tags=c.gettags(self.link)+('data',))
            self.addLink( src, dest, linkopts=link['opts'] )
            self.createDataLinkBindings()
            self.link = self.linkWidget = None

        f.close()

    def findWidgetByName( self, name ):
        for widget in self.widgetToItem:
            if name ==  widget[ 'text' ]:
                return widget
        return None

    def newTopology( self ):
        "New command."
        for widget in tuple( self.widgetToItem ):
            self.deleteItem( self.widgetToItem[ widget ] )
        self.hostCount = 0
        self.switchCount = 0
        self.controllerCount = 0
        self.links = {}
        self.hostOpts = {}
        self.switchOpts = {}
        self.controllers = {}
        self.appPrefs["ipBase"]= self.defaultIpBase

    def saveTopology( self ):
        "Save command."
        myFormats = [
            ('Mininet Topology','*.mn'),
            ('All Files','*'),
        ]

        savingDictionary = {}
        fileName = tkFileDialog.asksaveasfilename(filetypes=myFormats ,title="Save the topology as...")
        if len(fileName ) > 0:
            # Save Application preferences
            savingDictionary['version'] = '2'

            # Save Switches and Hosts
            hostsToSave = []
            switchesToSave = []
            controllersToSave = []
            for widget, item in self.widgetToItem.items():
                name = widget[ 'text' ]
                tags = self.canvas.gettags( item )
                x1, y1 = self.canvas.coords( item )
                if 'Switch' in tags or 'LegacySwitch' in tags or 'LegacyRouter' in tags or 'P4Switch' in tags or 'HardwareSwitch' in tags:
                    nodeNum = self.switchOpts[name]['nodeNum']
                    nodeToSave = {'number':str(nodeNum),
                                  'x':str(x1),
                                  'y':str(y1),
                                  'opts':self.switchOpts[name] }
                    switchesToSave.append(nodeToSave)
                elif 'Host' in tags:
                    nodeNum = self.hostOpts[name]['nodeNum']
                    nodeToSave = {'number':str(nodeNum),
                                  'x':str(x1),
                                  'y':str(y1),
                                  'opts':self.hostOpts[name] }
                    hostsToSave.append(nodeToSave)
                elif 'Controller' in tags:
                    nodeToSave = {'x':str(x1),
                                  'y':str(y1),
                                  'opts':self.controllers[name] }
                    controllersToSave.append(nodeToSave)
                else:
                    raise Exception( "Cannot create mystery node: " + name )
            savingDictionary['hosts'] = hostsToSave
            savingDictionary['switches'] = switchesToSave
            savingDictionary['controllers'] = controllersToSave

            # Save Links
            linksToSave = []
            for link in self.links.values():
                src = link['src']
                dst = link['dest']
                linkopts = link['linkOpts']

                srcName, dstName = src[ 'text' ], dst[ 'text' ]
                linkToSave = {'src':srcName,
                              'dest':dstName,
                              'opts':linkopts}
                if link['type'] == 'data':
                    linksToSave.append(linkToSave)
            savingDictionary['links'] = linksToSave

            # Save Application preferences
            savingDictionary['application'] = self.appPrefs

            try:
                with open(fileName, 'w') as f:
                    f.write(
                        json.dumps(savingDictionary,
                                   sort_keys=True,
                                   indent=4, separators=(',', ': ')))
            except Exception as er:  # pylint: disable=broad-except
                warn( er, '\n' )

    def exportScript( self ):
        "Export command."
        myFormats = [
            ('Mininet Custom Topology','*.py'),
            ('All Files','*'),
        ]

        fileName = tkFileDialog.asksaveasfilename(filetypes=myFormats ,title="Export the topology as...")
        if len(fileName ) > 0:
            # debug( "Now saving under %s\n" % fileName )
            f = open(fileName, 'w')  # pylint: disable=consider-using-with

            f.write("#!/usr/bin/env python\n")
            f.write("\n")
            f.write("from mininet.net import Mininet\n")
            f.write("from mininet.node import Controller, RemoteController, OVSController\n")
            f.write("from mininet.node import CPULimitedHost, Host, Node\n")
            f.write("from mininet.node import OVSKernelSwitch, UserSwitch\n")
            if StrictVersion(MININET_VERSION) > StrictVersion('2.0'):
                f.write("from mininet.node import IVSSwitch\n")
            f.write("from mininet.cli import CLI\n")
            f.write("from mininet.log import setLogLevel, info\n")
            f.write("from mininet.link import TCLink, Intf\n")
            f.write("from subprocess import call\n")

            inBandCtrl = False
            for widget, item in self.widgetToItem.items():
                name = widget[ 'text' ]
                tags = self.canvas.gettags( item )

                if 'Controller' in tags:
                    opts = self.controllers[name]
                    controllerType = opts['controllerType']
                    if controllerType == 'inband':
                        inBandCtrl = True

            if inBandCtrl:
                f.write("\n")
                f.write("class InbandController( RemoteController ):\n")
                f.write("\n")
                f.write("    def checkListening( self ):\n")
                f.write("        \"Overridden to do nothing.\"\n")
                f.write("        return\n")

            f.write("\n")
            f.write("def myNetwork():\n")
            f.write("\n")
            f.write("    net = Mininet( topo=None,\n")
            if len(self.appPrefs['dpctl']) > 0:
                f.write("                   listenPort="+self.appPrefs['dpctl']+",\n")
            f.write("                   build=False,\n")
            f.write("                   ipBase='"+self.appPrefs['ipBase']+"')\n")
            f.write("\n")
            f.write("    info( '*** Adding controller\\n' )\n")
            for widget, item in self.widgetToItem.items():
                name = widget[ 'text' ]
                tags = self.canvas.gettags( item )

                if 'Controller' in tags:
                    opts = self.controllers[name]
                    controllerType = opts['controllerType']
                    if 'controllerProtocol' in opts:
                        controllerProtocol = opts['controllerProtocol']
                    else:
                        controllerProtocol = 'tcp'
                    controllerIP = opts['remoteIP']
                    controllerPort = opts['remotePort']


                    f.write("    "+name+"=net.addController(name='"+name+"',\n")

                    if controllerType == 'remote':
                        f.write("                      controller=RemoteController,\n")
                        f.write("                      ip='"+controllerIP+"',\n")
                    elif controllerType == 'inband':
                        f.write("                      controller=InbandController,\n")
                        f.write("                      ip='"+controllerIP+"',\n")
                    elif controllerType == 'ovsc':
                        f.write("                      controller=OVSController,\n")
                    else:
                        f.write("                      controller=Controller,\n")

                    f.write("                      protocol='"+controllerProtocol+"',\n")
                    f.write("                      port="+str(controllerPort)+")\n")
                    f.write("\n")

            # Save Switches and Hosts
            f.write("    info( '*** Add switches\\n')\n")
            for widget, item in self.widgetToItem.items():
                name = widget[ 'text' ]
                tags = self.canvas.gettags( item )
                if 'LegacyRouter' in tags:
                    f.write("    "+name+" = net.addHost('"+name+"', cls=Node, ip='0.0.0.0')\n")
                    f.write("    "+name+".cmd('sysctl -w net.ipv4.ip_forward=1')\n")
                if 'LegacySwitch' in tags:
                    f.write("    "+name+" = net.addSwitch('"+name+"', cls=OVSKernelSwitch, failMode='standalone')\n")
                if 'Switch' in tags:
                    opts = self.switchOpts[name]
                    nodeNum = opts['nodeNum']
                    f.write("    "+name+" = net.addSwitch('"+name+"'")
                    if opts['switchType'] == 'default':
                        if self.appPrefs['switchType'] == 'ivs':
                            f.write(", cls=IVSSwitch")
                        elif self.appPrefs['switchType'] == 'user':
                            f.write(", cls=UserSwitch")
                        elif self.appPrefs['switchType'] == 'userns':
                            f.write(", cls=UserSwitch, inNamespace=True")
                        else:
                            f.write(", cls=OVSKernelSwitch")
                    elif opts['switchType'] == 'ivs':
                        f.write(", cls=IVSSwitch")
                    elif opts['switchType'] == 'user':
                        f.write(", cls=UserSwitch")
                    elif opts['switchType'] == 'userns':
                        f.write(", cls=UserSwitch, inNamespace=True")
                    else:
                        f.write(", cls=OVSKernelSwitch")
                    if 'dpctl' in opts:
                        f.write(", listenPort="+opts['dpctl'])
                    if 'dpid' in opts:
                        f.write(", dpid='"+opts['dpid']+"'")
                    f.write(")\n")
                    if 'externalInterfaces' in opts:
                        for extInterface in opts['externalInterfaces']:
                            f.write("    Intf( '"+extInterface+"', node="+name+" )\n")

            f.write("\n")
            f.write("    info( '*** Add hosts\\n')\n")
            for widget, item in self.widgetToItem.items():
                name = widget[ 'text' ]
                tags = self.canvas.gettags( item )
                if 'Host' in tags:
                    opts = self.hostOpts[name]
                    ip = None
                    defaultRoute = None
                    if 'defaultRoute' in opts and len(opts['defaultRoute']) > 0:
                        defaultRoute = "'via "+opts['defaultRoute']+"'"
                    else:
                        defaultRoute = 'None'
                    if 'ip' in opts and len(opts['ip']) > 0:
                        ip = opts['ip']
                    else:
                        nodeNum = self.hostOpts[name]['nodeNum']
                        ipBaseNum, prefixLen = netParse( self.appPrefs['ipBase'] )
                        ip = ipAdd(i=nodeNum, prefixLen=prefixLen, ipBaseNum=ipBaseNum)

                    if 'cores' in opts or 'cpu' in opts:
                        f.write("    "+name+" = net.addHost('"+name+"', cls=CPULimitedHost, ip='"+ip+"', defaultRoute="+defaultRoute+")\n")
                        if 'cores' in opts:
                            f.write("    "+name+".setCPUs(cores='"+opts['cores']+"')\n")
                        if 'cpu' in opts:
                            f.write("    "+name+".setCPUFrac(f="+str(opts['cpu'])+", sched='"+opts['sched']+"')\n")
                    else:
                        f.write("    "+name+" = net.addHost('"+name+"', cls=Host, ip='"+ip+"', defaultRoute="+defaultRoute+")\n")
                    if 'externalInterfaces' in opts:
                        for extInterface in opts['externalInterfaces']:
                            f.write("    Intf( '"+extInterface+"', node="+name+" )\n")
            f.write("\n")

            # Save Links
            f.write("    info( '*** Add links\\n')\n")
            for key,linkDetail in self.links.items():
                tags = self.canvas.gettags(key)
                if 'data' in tags:
                    optsExist = False
                    src = linkDetail['src']
                    dst = linkDetail['dest']
                    linkopts = linkDetail['linkOpts']
                    srcName, dstName = src[ 'text' ], dst[ 'text' ]
                    bw = ''
                    # delay = ''
                    # loss = ''
                    # max_queue_size = ''
                    linkOpts = "{"
                    if 'bw' in linkopts:
                        bw =  linkopts['bw']
                        linkOpts = linkOpts + "'bw':"+str(bw)
                        optsExist = True
                    if 'delay' in linkopts:
                        # delay =  linkopts['delay']
                        if optsExist:
                            linkOpts = linkOpts + ","
                        linkOpts = linkOpts + "'delay':'"+linkopts['delay']+"'"
                        optsExist = True
                    if 'loss' in linkopts:
                        if optsExist:
                            linkOpts = linkOpts + ","
                        linkOpts = linkOpts + "'loss':"+str(linkopts['loss'])
                        optsExist = True
                    if 'max_queue_size' in linkopts:
                        if optsExist:
                            linkOpts = linkOpts + ","
                        linkOpts = linkOpts + "'max_queue_size':"+str(linkopts['max_queue_size'])
                        optsExist = True
                    if 'jitter' in linkopts:
                        if optsExist:
                            linkOpts = linkOpts + ","
                        linkOpts = linkOpts + "'jitter':'"+linkopts['jitter']+"'"
                        optsExist = True
                    if 'speedup' in linkopts:
                        if optsExist:
                            linkOpts = linkOpts + ","
                        linkOpts = linkOpts + "'speedup':"+str(linkopts['speedup'])
                        optsExist = True

                    linkOpts = linkOpts + "}"
                    if optsExist:
                        f.write("    "+srcName+dstName+" = "+linkOpts+"\n")
                    f.write("    net.addLink("+srcName+", "+dstName)
                    if optsExist:
                        f.write(", cls=TCLink , **"+srcName+dstName)
                    f.write(")\n")

            f.write("\n")
            f.write("    info( '*** Starting network\\n')\n")
            f.write("    net.build()\n")

            f.write("    info( '*** Starting controllers\\n')\n")
            f.write("    for controller in net.controllers:\n")
            f.write("        controller.start()\n")
            f.write("\n")

            f.write("    info( '*** Starting switches\\n')\n")
            for widget, item in self.widgetToItem.items():
                name = widget[ 'text' ]
                tags = self.canvas.gettags( item )
                if 'Switch' in tags or 'LegacySwitch' in tags:
                    opts = self.switchOpts[name]
                    ctrlList = ",".join(opts['controllers'])
                    f.write("    net.get('"+name+"').start(["+ctrlList+"])\n")

            f.write("\n")

            f.write("    info( '*** Post configure switches and hosts\\n')\n")
            for widget, item in self.widgetToItem.items():
                name = widget[ 'text' ]
                tags = self.canvas.gettags( item )
                if 'Switch' in tags:
                    opts = self.switchOpts[name]
                    if opts['switchType'] == 'default':
                        if self.appPrefs['switchType'] == 'user':
                            if 'switchIP' in opts:
                                if len(opts['switchIP']) > 0:
                                    f.write("    "+name+".cmd('ifconfig "+name+" "+opts['switchIP']+"')\n")
                        elif self.appPrefs['switchType'] == 'userns':
                            if 'switchIP' in opts:
                                if len(opts['switchIP']) > 0:
                                    f.write("    "+name+".cmd('ifconfig lo "+opts['switchIP']+"')\n")
                        elif self.appPrefs['switchType'] == 'ovs':
                            if 'switchIP' in opts:
                                if len(opts['switchIP']) > 0:
                                    f.write("    "+name+".cmd('ifconfig "+name+" "+opts['switchIP']+"')\n")
                    elif opts['switchType'] == 'user':
                        if 'switchIP' in opts:
                            if len(opts['switchIP']) > 0:
                                f.write("    "+name+".cmd('ifconfig "+name+" "+opts['switchIP']+"')\n")
                    elif opts['switchType'] == 'userns':
                        if 'switchIP' in opts:
                            if len(opts['switchIP']) > 0:
                                f.write("    "+name+".cmd('ifconfig lo "+opts['switchIP']+"')\n")
                    elif opts['switchType'] == 'ovs':
                        if 'switchIP' in opts:
                            if len(opts['switchIP']) > 0:
                                f.write("    "+name+".cmd('ifconfig "+name+" "+opts['switchIP']+"')\n")
            for widget, item in self.widgetToItem.items():
                name = widget[ 'text' ]
                tags = self.canvas.gettags( item )
                if 'Host' in tags:
                    opts = self.hostOpts[name]
                    # Attach vlan interfaces
                    if 'vlanInterfaces' in opts:
                        for vlanInterface in opts['vlanInterfaces']:
                            f.write("    "+name+".cmd('vconfig add "+name+"-eth0 "+vlanInterface[1]+"')\n")
                            f.write("    "+name+".cmd('ifconfig "+name+"-eth0."+vlanInterface[1]+" "+vlanInterface[0]+"')\n")
                    # Run User Defined Start Command
                    if 'startCommand' in opts:
                        f.write("    "+name+".cmdPrint('"+opts['startCommand']+"')\n")
                if 'Switch' in tags:
                    opts = self.switchOpts[name]
                    # Run User Defined Start Command
                    if 'startCommand' in opts:
                        f.write("    "+name+".cmdPrint('"+opts['startCommand']+"')\n")

            # Configure NetFlow
            nflowValues = self.appPrefs['netflow']
            if len(nflowValues['nflowTarget']) > 0:
                nflowEnabled = False
                nflowSwitches = ''
                for widget, item in self.widgetToItem.items():
                    name = widget[ 'text' ]
                    tags = self.canvas.gettags( item )

                    if 'Switch' in tags:
                        opts = self.switchOpts[name]
                        if 'netflow' in opts:
                            if opts['netflow'] == '1':
                                nflowSwitches = nflowSwitches+' -- set Bridge '+name+' netflow=@MiniEditNF'
                                nflowEnabled=True
                if nflowEnabled:
                    nflowCmd = 'ovs-vsctl -- --id=@MiniEditNF create NetFlow '+ 'target=\\\"'+nflowValues['nflowTarget']+'\\\" '+ 'active-timeout='+nflowValues['nflowTimeout']
                    if nflowValues['nflowAddId'] == '1':
                        nflowCmd = nflowCmd + ' add_id_to_interface=true'
                    else:
                        nflowCmd = nflowCmd + ' add_id_to_interface=false'
                    f.write("    \n")
                    f.write("    call('"+nflowCmd+nflowSwitches+"', shell=True)\n")

            # Configure sFlow
            sflowValues = self.appPrefs['sflow']
            if len(sflowValues['sflowTarget']) > 0:
                sflowEnabled = False
                sflowSwitches = ''
                for widget, item in self.widgetToItem.items():
                    name = widget[ 'text' ]
                    tags = self.canvas.gettags( item )

                    if 'Switch' in tags:
                        opts = self.switchOpts[name]
                        if 'sflow' in opts:
                            if opts['sflow'] == '1':
                                sflowSwitches = sflowSwitches+' -- set Bridge '+name+' sflow=@MiniEditSF'
                                sflowEnabled=True
                if sflowEnabled:
                    sflowCmd = 'ovs-vsctl -- --id=@MiniEditSF create sFlow '+ 'target=\\\"'+sflowValues['sflowTarget']+'\\\" '+ 'header='+sflowValues['sflowHeader']+' '+ 'sampling='+sflowValues['sflowSampling']+' '+ 'polling='+sflowValues['sflowPolling']
                    f.write("    \n")
                    f.write("    call('"+sflowCmd+sflowSwitches+"', shell=True)\n")

            f.write("\n")
            f.write("    CLI(net)\n")
            for widget, item in self.widgetToItem:
                name = widget[ 'text' ]
                tags = self.canvas.gettags( item )
                if 'Host' in tags:
                    opts = self.hostOpts[name]
                    # Run User Defined Stop Command
                    if 'stopCommand' in opts:
                        f.write("    "+name+".cmdPrint('"+opts['stopCommand']+"')\n")
                if 'Switch' in tags:
                    opts = self.switchOpts[name]
                    # Run User Defined Stop Command
                    if 'stopCommand' in opts:
                        f.write("    "+name+".cmdPrint('"+opts['stopCommand']+"')\n")

            f.write("    net.stop()\n")
            f.write("\n")
            f.write("if __name__ == '__main__':\n")
            f.write("    setLogLevel( 'info' )\n")
            f.write("    myNetwork()\n")
            f.write("\n")


            f.close()


    # Generic canvas handler
    #
    # We could have used bindtags, as in nodeIcon, but
    # the dynamic approach used here
    # may actually require less code. In any case, it's an
    # interesting introspection-based alternative to bindtags.

    def canvasHandle( self, eventName, event ):
        "Generic canvas event handler"
        if self.active is None:
            return
        toolName = self.active
        handler = getattr( self, eventName + toolName, None )
        if handler is not None:
            handler( event )

    def clickCanvas( self, event ):
        "Canvas click handler."
        self.canvasHandle( 'click', event )

    def dragCanvas( self, event ):
        "Canvas drag handler."
        self.canvasHandle( 'drag', event )

    def releaseCanvas( self, event ):
        "Canvas mouse up handler."
        self.canvasHandle( 'release', event )

    # Currently the only items we can select directly are
    # links. Nodes are handled by bindings in the node icon.

    def findItem( self, x, y ):
        "Find items at a location in our canvas."
        items = self.canvas.find_overlapping( x, y, x, y )
        if len( items ) == 0:
            return None
        else:
            return items[ 0 ]

    # Canvas bindings for Select, Host, Switch and Link tools

    def clickSelect( self, event ):
        "Select an item."
        self.selectItem( self.findItem( event.x, event.y ) )

    def deleteItem( self, item ):
        "Delete an item."
        # Don't delete while network is running
        if self.buttons[ 'Select' ][ 'state' ] == 'disabled':
            return
        # Delete from model
        if item in self.links:
            self.deleteLink( item )
        if item in self.itemToWidget:
            self.deleteNode( item )
        # Delete from view
        self.canvas.delete( item )

    def deleteSelection( self, _event ):
        "Delete the selected item."
        if self.selection is not None:
            self.deleteItem( self.selection )
        self.selectItem( None )

    def nodeIcon( self, node, name ):
        "Create a new node icon."
        icon = Button( self.canvas, image=self.images[ node ],
                       text=name, compound='top' )
        # Unfortunately bindtags wants a tuple
        bindtags = [ str( self.nodeBindings ) ]
        bindtags += list( icon.bindtags() )
        icon.bindtags( tuple( bindtags ) )
        return icon

    def newNode( self, node, event ):
        "Add a new node to our canvas."
        c = self.canvas
        x, y = c.canvasx( event.x ), c.canvasy( event.y )
        name = self.nodePrefixes[ node ]
        if node == 'Switch':
            self.switchCount += 1
            name = self.nodePrefixes[ node ] + str( self.switchCount )
            self.switchOpts[name] = {}
            self.switchOpts[name]['nodeNum']=self.switchCount
            self.switchOpts[name]['hostname']=name
            self.switchOpts[name]['switchType']='default'
            self.switchOpts[name]['controllers']=[]
        if node == 'LegacyRouter':
            self.switchCount += 1
            name = self.nodePrefixes[ node ] + str( self.switchCount )
            self.switchOpts[name] = {}
            self.switchOpts[name]['nodeNum']=self.switchCount
            self.switchOpts[name]['hostname']=name
            self.switchOpts[name]['switchType']='legacyRouter'
        if node == 'LegacySwitch':
            self.switchCount += 1
            name = self.nodePrefixes[ node ] + str( self.switchCount )
            self.switchOpts[name] = {}
            self.switchOpts[name]['nodeNum']=self.switchCount
            self.switchOpts[name]['hostname']=name
            self.switchOpts[name]['switchType']='legacySwitch'
            self.switchOpts[name]['controllers']=[]
        if node == 'P4Switch':
            self.switchCount += 1
            name = self.nodePrefixes[ node ] + str( self.switchCount )
            self.switchOpts[name] = {}
            self.switchOpts[name]['nodeNum']=self.switchCount
            self.switchOpts[name]['hostname']=name
            self.switchOpts[name]['switchType']='p4Switch'
            self.switchOpts[name]['controllers']=[]
        if node == 'HardwareSwitch':
            self.switchCount += 1
            name = self.nodePrefixes[ node ] + str( self.switchCount )
            self.switchOpts[name] = {}
            self.switchOpts[name]['nodeNum']=self.switchCount
            self.switchOpts[name]['hostname']=name
            self.switchOpts[name]['switchType']='hardwareSwitch'
            self.switchOpts[name]['controllers']=[]
        if node == 'Host':
            self.hostCount += 1
            name = self.nodePrefixes[ node ] + str( self.hostCount )
            self.hostOpts[name] = {'sched':'host'}
            self.hostOpts[name]['nodeNum']=self.hostCount
            self.hostOpts[name]['hostname']=name
        if node == 'Controller':
            name = self.nodePrefixes[ node ] + str( self.controllerCount )
            ctrlr = { 'controllerType': 'ref',
                      'hostname': name,
                      'controllerProtocol': 'tcp',
                      'remoteIP': '127.0.0.1',
                      'remotePort': 6633}
            self.controllers[name] = ctrlr
            # We want to start controller count at 0
            self.controllerCount += 1

        icon = self.nodeIcon( node, name )
        item = self.canvas.create_window( x, y, anchor='c', window=icon,
                                          tags=node )
        self.widgetToItem[ icon ] = item
        self.itemToWidget[ item ] = icon
        self.selectItem( item )
        icon.links = {}
        if node == 'Switch':
            icon.bind('<Button-3>', self.do_switchPopup )
        if node == 'LegacyRouter':
            icon.bind('<Button-3>', self.do_legacyRouterPopup )
        if node == 'LegacySwitch':
            icon.bind('<Button-3>', self.do_legacySwitchPopup )
        if node == 'Host':
            icon.bind('<Button-3>', self.do_hostPopup )
        if node == 'Controller':
            icon.bind('<Button-3>', self.do_controllerPopup )
        if node == 'P4Switch':
            icon.bind('<Button-3>', self.do_p4SwitchPopup )
        if node == 'HardwareSwitch':
            icon.bind('<Button-3>', self.do_hardwareSwitchPopup)


    def clickController( self, event ):
        "Add a new Controller to our canvas."
        self.newNode( 'Controller', event )

    def clickHost( self, event ):
        "Add a new host to our canvas."
        self.newNode( 'Host', event )

    def clickLegacyRouter( self, event ):
        "Add a new switch to our canvas."
        self.newNode( 'LegacyRouter', event )

    def clickLegacySwitch( self, event ):
        "Add a new switch to our canvas."
        self.newNode( 'LegacySwitch', event )

    def clickSwitch( self, event ):
        "Add a new switch to our canvas."
        self.newNode( 'Switch', event )

    def clickP4Switch( self, event ):
        "Add a new P4 Switch to our canvas."
        self.newNode( 'P4Switch', event )

    def clickHardwareSwitch( self, event ):
        "Add a new hardware switch to our canvas."
        if self.hwSwitches < 1:
            self.hwSwitches += 1
            self.newNode( 'HardwareSwitch', event )

    def dragNetLink( self, event ):
        "Drag a link's endpoint to another node."
        if self.link is None:
            return
        # Since drag starts in widget, we use root coords
        x = self.canvasx( event.x_root )
        y = self.canvasy( event.y_root )
        c = self.canvas
        c.coords( self.link, self.linkx, self.linky, x, y )

    def releaseNetLink( self, _event ):
        "Give up on the current link."
        if self.link is not None:
            self.canvas.delete( self.link )
        self.linkWidget = self.linkItem = self.link = None

    # Generic node handlers

    def createNodeBindings( self ):
        "Create a set of bindings for nodes."
        bindings = {
            '<ButtonPress-1>': self.clickNode,
            '<B1-Motion>': self.dragNode,
            '<ButtonRelease-1>': self.releaseNode,
            '<Enter>': self.enterNode,
            '<Leave>': self.leaveNode
        }
        l = Label()  # lightweight-ish owner for bindings
        for event, binding in bindings.items():
            l.bind( event, binding )
        return l

    def selectItem( self, item ):
        "Select an item and remember old selection."
        self.lastSelection = self.selection
        self.selection = item

    def enterNode( self, event ):
        "Select node on entry."
        self.selectNode( event )

    def leaveNode( self, _event ):
        "Restore old selection on exit."
        self.selectItem( self.lastSelection )

    def clickNode( self, event ):
        "Node click handler."
        if self.active == 'NetLink':
            self.startLink( event )
        else:
            self.selectNode( event )
        return 'break'

    def dragNode( self, event ):
        "Node drag handler."
        if self.active == 'NetLink':
            self.dragNetLink( event )
        else:
            self.dragNodeAround( event )

    def releaseNode( self, event ):
        "Node release handler."
        if self.active == 'NetLink':
            self.finishLink( event )

    # Specific node handlers

    def selectNode( self, event ):
        "Select the node that was clicked on."
        item = self.widgetToItem.get( event.widget, None )
        self.selectItem( item )

    def dragNodeAround( self, event ):
        "Drag a node around on the canvas."
        c = self.canvas
        # Convert global to local coordinates;
        # Necessary since x, y are widget-relative
        x = self.canvasx( event.x_root )
        y = self.canvasy( event.y_root )
        w = event.widget
        # Adjust node position
        item = self.widgetToItem[ w ]
        c.coords( item, x, y )
        # Adjust link positions
        for dest in w.links:
            link = w.links[ dest ]
            item = self.widgetToItem[ dest ]
            x1, y1 = c.coords( item )
            c.coords( link, x, y, x1, y1 )
        self.updateScrollRegion()

    def createControlLinkBindings( self ):
        "Create a set of bindings for nodes."
        # Link bindings
        # Selection still needs a bit of work overall
        # Callbacks ignore event

        def select( _event, link=self.link ):
            "Select item on mouse entry."
            self.selectItem( link )

        def highlight( _event, link=self.link ):
            "Highlight item on mouse entry."
            self.selectItem( link )
            self.canvas.itemconfig( link, fill='green' )

        def unhighlight( _event, link=self.link ):
            "Unhighlight item on mouse exit."
            self.canvas.itemconfig( link, fill='red' )
            #self.selectItem( None )

        self.canvas.tag_bind( self.link, '<Enter>', highlight )
        self.canvas.tag_bind( self.link, '<Leave>', unhighlight )
        self.canvas.tag_bind( self.link, '<ButtonPress-1>', select )

    def createDataLinkBindings( self ):
        "Create a set of bindings for nodes."
        # Link bindings
        # Selection still needs a bit of work overall
        # Callbacks ignore event

        def select( _event, link=self.link ):
            "Select item on mouse entry."
            self.selectItem( link )

        def highlight( _event, link=self.link ):
            "Highlight item on mouse entry."
            self.selectItem( link )
            self.canvas.itemconfig( link, fill='green' )

        def unhighlight( _event, link=self.link ):
            "Unhighlight item on mouse exit."
            self.canvas.itemconfig( link, fill='blue' )
            #self.selectItem( None )

        self.canvas.tag_bind( self.link, '<Enter>', highlight )
        self.canvas.tag_bind( self.link, '<Leave>', unhighlight )
        self.canvas.tag_bind( self.link, '<ButtonPress-1>', select )
        self.canvas.tag_bind( self.link, '<Button-3>', self.do_linkPopup )


    def startLink( self, event ):
        "Start a new link."
        if event.widget not in self.widgetToItem:
            # Didn't click on a node
            return

        w = event.widget
        item = self.widgetToItem[ w ]
        x, y = self.canvas.coords( item )
        self.link = self.canvas.create_line( x, y, x, y, width=4,
                                             fill='blue', tag='link' )
        self.linkx, self.linky = x, y
        self.linkWidget = w
        self.linkItem = item


    def finishLink( self, event ):
        "Finish creating a link"
        if self.link is None:
            return
        source = self.linkWidget
        c = self.canvas
        # Since we dragged from the widget, use root coords
        x, y = self.canvasx( event.x_root ), self.canvasy( event.y_root )
        target = self.findItem( x, y )
        dest = self.itemToWidget.get( target, None )
        if ( source is None or dest is None or source == dest
                or dest in source.links or source in dest.links ):
            self.releaseNetLink( event )
            return
        
        # For now, don't allow hosts to be directly linked
        # For now, only allow hardware switch to be connected to host
        stags = self.canvas.gettags( self.widgetToItem[ source ] )
        dtags = self.canvas.gettags( target )
        # TODO: Make this less confusing
        # pylint: disable=too-many-boolean-expressions
        if (('Host' in stags and 'Host' in dtags) or
           ('Controller' in dtags and 'LegacyRouter' in stags) or
           ('Controller' in stags and 'LegacyRouter' in dtags) or
           ('Controller' in dtags and 'LegacySwitch' in stags) or
           ('Controller' in stags and 'LegacySwitch' in dtags) or
           ('Controller' in dtags and 'Host' in stags) or
           ('Controller' in stags and 'Host' in dtags) or
           ('Controller' in stags and 'Controller' in dtags) or
           ('HardwareSwitch' in stags and 'Host' not in dtags) or
           ('HardwareSwitch' in dtags and 'Host' not in stags)):
            self.releaseNetLink( event )
            return

        # make sure that there cannot be more links to the hardware switch than external interfaces
        if 'HardwareSwitch' in stags or 'HardwareSwitch' in dtags:
            if self.hwConnectionsCounter < len(self.externalInterfaces):
                # get name of host
                hostName = ""
                if source['text'][0] == 'h':
                    hostName = source['text']
                else:
                    hostName = dest['text']

                iselector = InterfaceSelector(self, title="Interface Selector", hostName=hostName, 
                                              externalInterfaces=self.externalInterfaces, 
                                              externalInterfaceBindings=self.externalInterfaceBindings)
                self.master.wait_window(iselector.top)
                if iselector.result:
                    self.externalInterfaceBindings[iselector.result] = hostName
                    self.hostOpts[hostName]['externalInterfaces'] = [iselector.result]

                    showinfo(title="MiniEdit", message=f"Connected {hostName} interface {iselector.result} to hardware switch.")
                    print(f"Bound {hostName} to {iselector.result}")


                self.hwConnectionsCounter += 1
            else:
                self.releaseNetLink(event)
                return


        # Set link type
        linkType='data'
        if 'Controller' in stags or 'Controller' in dtags:
            linkType='control'
            c.itemconfig(self.link, dash=(6, 4, 2, 4), fill='red')
            self.createControlLinkBindings()
        else:
            linkType='data'
            self.createDataLinkBindings()
        c.itemconfig(self.link, tags=c.gettags(self.link)+(linkType,))

        x, y = c.coords( target )
        c.coords( self.link, self.linkx, self.linky, x, y )
        self.addLink( source, dest, linktype=linkType )
        if linkType == 'control':
            controllerName = ''
            switchName = ''
            if 'Controller' in stags:
                controllerName = source[ 'text' ]
                switchName = dest[ 'text' ]
            else:
                controllerName = dest[ 'text' ]
                switchName = source[ 'text' ]

            self.switchOpts[switchName]['controllers'].append(controllerName)

        # We're done
        self.link = self.linkWidget = None

    # Menu handlers

    def about( self ):
        "Display about box."
        about = self.aboutBox
        if about is None:
            bg = 'white'
            about = Toplevel( bg='white' )
            about.title( 'About' )
            desc = self.appName + ': a simple network editor for MiniNet'
            version = 'MiniEdit '+MINIEDIT_VERSION
            author = 'Originally by: Bob Lantz <rlantz@cs>, April 2010'
            enhancements = 'Enhancements by: Gregory Gee, Since July 2013'
            www = 'http://gregorygee.wordpress.com/category/miniedit/'
            line1 = Label( about, text=desc, font='Helvetica 10 bold', bg=bg )
            line2 = Label( about, text=version, font='Helvetica 9', bg=bg )
            line3 = Label( about, text=author, font='Helvetica 9', bg=bg )
            line4 = Label( about, text=enhancements, font='Helvetica 9', bg=bg )
            line5 = Entry( about, font='Helvetica 9', bg=bg, width=len(www), justify=CENTER )
            line5.insert(0, www)
            line5.configure(state='readonly')
            line1.pack( padx=20, pady=10 )
            line2.pack(pady=10 )
            line3.pack(pady=10 )
            line4.pack(pady=10 )
            line5.pack(pady=10 )
            def hide():
                about.withdraw()
            self.aboutBox = about
            # Hide on close rather than destroying window
            Wm.wm_protocol( about, name='WM_DELETE_WINDOW', func=hide )
        # Show (existing) window
        about.deiconify()

    def createToolImages( self ):
        "Create toolbar (and icon) images."

    @staticmethod
    def checkIntf( intf ):
        "Make sure intf exists and is not configured."
        if ( ' %s:' % intf ) not in quietRun( 'ip link show' ):
            showerror(title="Error",
                      message='External interface ' +intf + ' does not exist! Skipping.')
            return False
        ips = re.findall( r'\d+\.\d+\.\d+\.\d+', quietRun( 'ifconfig ' + intf ) )
        if ips:
            showerror(title="Error",
                      message= intf + ' has an IP address and is probably in use! Skipping.' )
            return False
        return True

    def hostDetails( self, _ignore=None ):
        if ( self.selection is None or
             self.net is not None or
             self.selection not in self.itemToWidget ):
            return
        widget = self.itemToWidget[ self.selection ]
        name = widget[ 'text' ]
        tags = self.canvas.gettags( self.selection )
        if 'Host' not in tags:
            return

        prefDefaults = self.hostOpts[name]
        hostBox = HostDialog(self, title='Host Details', prefDefaults=prefDefaults)
        self.master.wait_window(hostBox.top)
        if hostBox.result:
            newHostOpts = {'nodeNum':self.hostOpts[name]['nodeNum']}
            newHostOpts['sched'] = hostBox.result['sched']
            if len(hostBox.result['startCommand']) > 0:
                newHostOpts['startCommand'] = hostBox.result['startCommand']
            if len(hostBox.result['stopCommand']) > 0:
                newHostOpts['stopCommand'] = hostBox.result['stopCommand']
            if len(hostBox.result['cpu']) > 0:
                newHostOpts['cpu'] = float(hostBox.result['cpu'])
            if len(hostBox.result['cores']) > 0:
                newHostOpts['cores'] = hostBox.result['cores']
            if len(hostBox.result['hostname']) > 0:
                newHostOpts['hostname'] = hostBox.result['hostname']
                name = hostBox.result['hostname']
                widget[ 'text' ] = name
            if len(hostBox.result['defaultRoute']) > 0:
                newHostOpts['defaultRoute'] = hostBox.result['defaultRoute']
            if len(hostBox.result['ip']) > 0:
                newHostOpts['ip'] = hostBox.result['ip']
            if len(hostBox.result['mac']) > 0:
                newHostOpts['mac'] = hostBox.result['mac']
            if len(hostBox.result['externalInterfaces']) > 0:
                newHostOpts['externalInterfaces'] = hostBox.result['externalInterfaces']
            if len(hostBox.result['vlanInterfaces']) > 0:
                newHostOpts['vlanInterfaces'] = hostBox.result['vlanInterfaces']
            if len(hostBox.result['privateDirectory']) > 0:
                newHostOpts['privateDirectory'] = hostBox.result['privateDirectory']
            self.hostOpts[name] = newHostOpts
            info( 'New host details for ' + name + ' = ' + str(newHostOpts), '\n' )

    def switchDetails( self, _ignore=None ):
        if ( self.selection is None or
             self.net is not None or
             self.selection not in self.itemToWidget ):
            return
        widget = self.itemToWidget[ self.selection ]
        name = widget[ 'text' ]
        tags = self.canvas.gettags( self.selection )
        if 'Switch' not in tags:
            return

        prefDefaults = self.switchOpts[name]
        switchBox = SwitchDialog(self, title='Switch Details', prefDefaults=prefDefaults)
        self.master.wait_window(switchBox.top)
        if switchBox.result:
            newSwitchOpts = {'nodeNum':self.switchOpts[name]['nodeNum']}
            newSwitchOpts['switchType'] = switchBox.result['switchType']
            newSwitchOpts['controllers'] = self.switchOpts[name]['controllers']
            if len(switchBox.result['startCommand']) > 0:
                newSwitchOpts['startCommand'] = switchBox.result['startCommand']
            if len(switchBox.result['stopCommand']) > 0:
                newSwitchOpts['stopCommand'] = switchBox.result['stopCommand']
            if len(switchBox.result['dpctl']) > 0:
                newSwitchOpts['dpctl'] = switchBox.result['dpctl']
            if len(switchBox.result['dpid']) > 0:
                newSwitchOpts['dpid'] = switchBox.result['dpid']
            if len(switchBox.result['hostname']) > 0:
                newSwitchOpts['hostname'] = switchBox.result['hostname']
                name = switchBox.result['hostname']
                widget[ 'text' ] = name
            if len(switchBox.result['externalInterfaces']) > 0:
                newSwitchOpts['externalInterfaces'] = switchBox.result['externalInterfaces']
            newSwitchOpts['switchIP'] = switchBox.result['switchIP']
            newSwitchOpts['sflow'] = switchBox.result['sflow']
            newSwitchOpts['netflow'] = switchBox.result['netflow']
            self.switchOpts[name] = newSwitchOpts
            info( 'New switch details for ' + name + ' = ' + str(newSwitchOpts), '\n' )

    def p4SwitchDetails( self, _ignore=None ):
        if ( self.selection is None or
             self.net is not None or
             self.selection not in self.itemToWidget ):
            return
        widget = self.itemToWidget[ self.selection ]
        name = widget[ 'text' ]
        tags = self.canvas.gettags( self.selection )
        if 'P4Switch' not in tags:
            return
        
        prefDefaults = self.switchOpts[name]
        p4SwitchBox = P4SwitchDialog(self, title="P4 Switch Details", prefDefaults=prefDefaults)
        self.master.wait_window(p4SwitchBox.top)
        if p4SwitchBox.result:
            newSwitchOpts = {'nodeNum':self.switchOpts[name]['nodeNum']}
            newSwitchOpts['switchType'] = self.switchOpts[name]['switchType']
            newSwitchOpts['controllers'] = self.switchOpts[name]['controllers']
            
            if len(p4SwitchBox.result['hostname']) > 0:
                newSwitchOpts['hostname'] = p4SwitchBox.result['hostname']
                name = p4SwitchBox.result['hostname']
                widget[ 'text' ] = name
            if len(p4SwitchBox.result['jsonPath']) > 0:
                newSwitchOpts['jsonPath'] = p4SwitchBox.result['jsonPath']
                
            self.switchOpts[name] = newSwitchOpts
            info( 'New switch details for ' + name + ' = ' + str(newSwitchOpts), '\n' )

    def p4SwitchOptions( self, _ignore=None ):
        if ( self.selection is None or
             self.net is None or
             self.selection not in self.itemToWidget ):
            return
        
        widget = self.itemToWidget[ self.selection ]
        name = widget[ 'text' ]
        if name not in self.net.nameToNode:
            return
        tags = self.canvas.gettags( self.selection )
        if 'P4Switch' not in tags:
            return

        TableOptionsDialog(self, title="P4 Switch Options", node=self.net.nameToNode[ name ])

    def hardwareSwitchOptions(self, _ignore=None):
        if (self.selection is None or
            self.net is None or
            self.selection not in self.itemToWidget):
            return
        
        HardwareTableOptionsDialog(self, title="P4 Switch Options")


    def linkUp( self ):
        if ( self.selection is None or
             self.net is None):
            return
        link = self.selection
        linkDetail =  self.links[link]
        src = linkDetail['src']
        dst = linkDetail['dest']
        srcName, dstName = src[ 'text' ], dst[ 'text' ]
        self.net.configLinkStatus(srcName, dstName, 'up')
        self.canvas.itemconfig(link, dash=())

    def linkDown( self ):
        if ( self.selection is None or
             self.net is None):
            return
        link = self.selection
        linkDetail =  self.links[link]
        src = linkDetail['src']
        dst = linkDetail['dest']
        srcName, dstName = src[ 'text' ], dst[ 'text' ]
        self.net.configLinkStatus(srcName, dstName, 'down')
        self.canvas.itemconfig(link, dash=(4, 4))

    def linkDetails( self, _ignore=None ):
        if ( self.selection is None or
             self.net is not None):
            return
        link = self.selection

        linkDetail =  self.links[link]
        linkopts = linkDetail['linkOpts']
        linkBox = LinkDialog(self, title='Link Details', linkDefaults=linkopts)
        if linkBox.result is not None:
            linkDetail['linkOpts'] = linkBox.result
            info( 'New link details = ' + str(linkBox.result), '\n' )

    def prefDetails( self ):
        prefDefaults = self.appPrefs
        prefBox = PrefsDialog(self, title='Preferences', prefDefaults=prefDefaults)
        info( 'New Prefs = ' + str(prefBox.result), '\n' )
        if prefBox.result:
            self.appPrefs = prefBox.result


    def controllerDetails( self ):
        if ( self.selection is None or
             self.net is not None or
             self.selection not in self.itemToWidget ):
            return
        widget = self.itemToWidget[ self.selection ]
        name = widget[ 'text' ]
        tags = self.canvas.gettags( self.selection )
        oldName = name
        if 'Controller' not in tags:
            return

        ctrlrBox = ControllerDialog(self, title='Controller Details', ctrlrDefaults=self.controllers[name])
        if ctrlrBox.result:
            # debug( 'Controller is ' + ctrlrBox.result[0], '\n' )
            if len(ctrlrBox.result['hostname']) > 0:
                name = ctrlrBox.result['hostname']
                widget[ 'text' ] = name
            else:
                ctrlrBox.result['hostname'] = name
            self.controllers[name] = ctrlrBox.result
            info( 'New controller details for ' + name + ' = ' + str(self.controllers[name]), '\n' )
            # Find references to controller and change name
            if oldName != name:
                for widget, item in self.widgetToItem.items():
                    switchName = widget[ 'text' ]
                    tags = self.canvas.gettags( item )
                    if 'Switch' in tags:
                        switch = self.switchOpts[switchName]
                        if oldName in switch['controllers']:
                            switch['controllers'].remove(oldName)
                            switch['controllers'].append(name)


    def listBridge( self, _ignore=None ):
        if ( self.selection is None or
             self.net is None or
             self.selection not in self.itemToWidget ):
            return
        name = self.itemToWidget[ self.selection ][ 'text' ]
        tags = self.canvas.gettags( self.selection )

        if name not in self.net.nameToNode:
            return
        if 'Switch' in tags or 'LegacySwitch' in tags:
            call(["xterm -T 'Bridge Details' -sb -sl 2000 -e 'ovs-vsctl list bridge " + name + "; read -p \"Press Enter to close\"' &"], shell=True)

    @staticmethod
    def ovsShow( _ignore=None ):
        call(["xterm -T 'OVS Summary' -sb -sl 2000 -e 'ovs-vsctl show; read -p \"Press Enter to close\"' &"], shell=True)

    @staticmethod
    def rootTerminal( _ignore=None ):
        call(["xterm -T 'Root Terminal' -sb -sl 2000 &"], shell=True)

    # Model interface
    #
    # Ultimately we will either want to use a topo or
    # mininet object here, probably.

    def addLink( self, source, dest, linktype='data', linkopts=None ):
        "Add link to model."
        if linkopts is None:
            linkopts = {}
        source.links[ dest ] = self.link
        dest.links[ source ] = self.link
        self.links[ self.link ] = {'type':linktype,
                                   'src':source,
                                   'dest':dest,
                                   'linkOpts':linkopts}

    def deleteLink( self, link ):
        "Delete link from model."
        pair = self.links.get( link, None )
        if pair is not None:
            source=pair['src']
            dest=pair['dest']
            del source.links[ dest ]
            del dest.links[ source ]
            stags = self.canvas.gettags( self.widgetToItem[ source ] )
            dtags = self.canvas.gettags( self.widgetToItem[ dest ] )
            ltags = self.canvas.gettags( link )

            if 'HardwareSwitch' in stags or 'HardwareSwitch' in dtags:
                # decrement number of links connected to hardware switch
                self.hwConnectionsCounter -= 1

            if 'control' in ltags:
                controllerName = ''
                switchName = ''
                if 'Controller' in stags:
                    controllerName = source[ 'text' ]
                    switchName = dest[ 'text' ]
                else:
                    controllerName = dest[ 'text' ]
                    switchName = source[ 'text' ]

                if controllerName in self.switchOpts[switchName]['controllers']:
                    self.switchOpts[switchName]['controllers'].remove(controllerName)


        if link is not None:
            del self.links[ link ]

    def deleteNode( self, item ):
        "Delete node (and its links) from model."

        widget = self.itemToWidget[ item ]
        tags = self.canvas.gettags(item)
        if 'HardwareSwitch' in tags:
            # decrement hardware switch counter
            self.hwSwitches -= 1
        if 'Controller' in tags:
            # remove from switch controller lists
            for searchwidget, searchitem in self.widgetToItem.items():
                name = searchwidget[ 'text' ]
                tags = self.canvas.gettags( searchitem )
                if 'Switch' in tags:
                    if widget['text'] in self.switchOpts[name]['controllers']:
                        self.switchOpts[name]['controllers'].remove(widget['text'])
        for link in tuple( widget.links.values() ):
            # Delete from view and model
            self.deleteItem( link )
        del self.itemToWidget[ item ]
        del self.widgetToItem[ widget ]

    def buildNodes( self, net):
        # Make nodes
        info( "Getting Hosts and Switches.\n" )
        for widget, item in self.widgetToItem.items():
            name = widget[ 'text' ]
            tags = self.canvas.gettags( item )
            # debug( name+' has '+str(tags), '\n' )

            if 'Switch' in tags:
                opts = self.switchOpts[name]
                # debug( str(opts), '\n' )

                # Create the correct switch class
                switchClass = customOvs
                switchParms={}
                if 'dpctl' in opts:
                    switchParms['listenPort']=int(opts['dpctl'])
                if 'dpid' in opts:
                    switchParms['dpid']=opts['dpid']
                if opts['switchType'] == 'default':
                    if self.appPrefs['switchType'] == 'ivs':
                        switchClass = IVSSwitch
                    elif self.appPrefs['switchType'] == 'user':
                        switchClass = CustomUserSwitch
                    elif self.appPrefs['switchType'] == 'userns':
                        switchParms['inNamespace'] = True
                        switchClass = CustomUserSwitch
                    else:
                        switchClass = customOvs
                elif opts['switchType'] == 'user':
                    switchClass = CustomUserSwitch
                elif opts['switchType'] == 'userns':
                    switchClass = CustomUserSwitch
                    switchParms['inNamespace'] = True
                elif opts['switchType'] == 'ivs':
                    switchClass = IVSSwitch
                else:
                    switchClass = customOvs

                if switchClass == customOvs:
                    # Set OpenFlow versions
                    self.openFlowVersions = []
                    if self.appPrefs['openFlowVersions']['ovsOf10'] == '1':
                        self.openFlowVersions.append('OpenFlow10')
                    if self.appPrefs['openFlowVersions']['ovsOf11'] == '1':
                        self.openFlowVersions.append('OpenFlow11')
                    if self.appPrefs['openFlowVersions']['ovsOf12'] == '1':
                        self.openFlowVersions.append('OpenFlow12')
                    if self.appPrefs['openFlowVersions']['ovsOf13'] == '1':
                        self.openFlowVersions.append('OpenFlow13')
                    protoList = ",".join(self.openFlowVersions)
                    switchParms['protocols'] = protoList
                newSwitch = net.addSwitch( name , cls=switchClass, **switchParms)

                # Some post startup config
                if switchClass == CustomUserSwitch:
                    if 'switchIP' in opts:
                        if len(opts['switchIP']) > 0:
                            newSwitch.setSwitchIP(opts['switchIP'])
                if switchClass == customOvs:
                    if 'switchIP' in opts:
                        if len(opts['switchIP']) > 0:
                            newSwitch.setSwitchIP(opts['switchIP'])

                # Attach external interfaces
                if 'externalInterfaces' in opts:
                    for extInterface in opts['externalInterfaces']:
                        if self.checkIntf(extInterface):
                            Intf( extInterface, node=newSwitch )

            elif 'LegacySwitch' in tags:
                newSwitch = net.addSwitch( name , cls=LegacySwitch)
            elif 'P4Switch' in tags:
                newSwitch = net.addSwitch( name , cls=P4Switch, sw_path='simple_switch', json_path=self.switchOpts[name]['jsonPath'], thrift_port=9090)
            elif 'HardwareSwitch' in tags:
                pass
            elif 'LegacyRouter' in tags:
                newSwitch = net.addHost( name , cls=LegacyRouter)
            elif 'Host' in tags:
                opts = self.hostOpts[name]
                # debug( str(opts), '\n' )
                ip = None
                defaultRoute = None
                if 'defaultRoute' in opts and len(opts['defaultRoute']) > 0:
                    defaultRoute = 'via '+opts['defaultRoute']
                if 'ip' in opts and len(opts['ip']) > 0:
                    ip = opts['ip']
                else:
                    nodeNum = self.hostOpts[name]['nodeNum']
                    ipBaseNum, prefixLen = netParse( self.appPrefs['ipBase'] )
                    ip = ipAdd(i=nodeNum, prefixLen=prefixLen, ipBaseNum=ipBaseNum)                    

                # Create the correct host class
                if 'cores' in opts or 'cpu' in opts:
                    if 'privateDirectory' in opts:
                        hostCls = partial( CPULimitedHost,
                                           privateDirs=opts['privateDirectory'] )
                    else:
                        hostCls=CPULimitedHost
                else:
                    if 'privateDirectory' in opts:
                        hostCls = partial( Host,
                                           privateDirs=opts['privateDirectory'] )
                    else:
                        hostCls=Host
                #hostCls=P4Host
                debug( hostCls, '\n' )

                if 'mac' in opts and len(opts['mac']) > 0:
                    newHost = net.addHost( name,
                                            cls=hostCls,
                                            ip=ip,
                                            mac=opts['mac'],
                                            defaultRoute=defaultRoute
                                            )
                else:
                    newHost = net.addHost( name,
                                            cls=hostCls,
                                            ip=ip,
                                            defaultRoute=defaultRoute
                                            )

                # Set the CPULimitedHost specific options
                if 'cores' in opts:
                    newHost.setCPUs(cores = opts['cores'])
                if 'cpu' in opts:
                    newHost.setCPUFrac(f=opts['cpu'], sched=opts['sched'])

                # Attach external interfaces
                if 'externalInterfaces' in opts:
                    for extInterface in opts['externalInterfaces']:
                        if self.checkIntf(extInterface):
                            print("linking interface", extInterface)
                            Intf( extInterface, node=newHost )
                        else:
                            print("no")
                if 'vlanInterfaces' in opts:
                    if len(opts['vlanInterfaces']) > 0:
                        info( 'Checking that OS is VLAN prepared\n' )
                        self.pathCheck('vconfig', moduleName='vlan package')
                        moduleDeps( add='8021q' )
            elif 'Controller' in tags:
                opts = self.controllers[name]

                # Get controller info from panel
                controllerType = opts['controllerType']
                if 'controllerProtocol' in opts:
                    controllerProtocol = opts['controllerProtocol']
                else:
                    controllerProtocol = 'tcp'
                    opts['controllerProtocol'] = 'tcp'
                controllerIP = opts['remoteIP']
                controllerPort = opts['remotePort']

                # Make controller
                info( 'Getting controller selection:'+controllerType, '\n' )
                if controllerType == 'remote':
                    net.addController(name=name,
                                      controller=RemoteController,
                                      ip=controllerIP,
                                      protocol=controllerProtocol,
                                      port=controllerPort)
                elif controllerType == 'inband':
                    net.addController(name=name,
                                      controller=InbandController,
                                      ip=controllerIP,
                                      protocol=controllerProtocol,
                                      port=controllerPort)
                elif controllerType == 'ovsc':
                    net.addController(name=name,
                                      controller=OVSController,
                                      protocol=controllerProtocol,
                                      port=controllerPort)
                else:
                    net.addController(name=name,
                                      controller=Controller,
                                      protocol=controllerProtocol,
                                      port=controllerPort)

            else:
                raise Exception( "Cannot create mystery node: " + name )

    @staticmethod
    def pathCheck( *args, **kwargs ):
        "Make sure each program in *args can be found in $PATH."
        moduleName = kwargs.get( 'moduleName', 'it' )
        for arg in args:
            if not quietRun( 'which ' + arg ):
                showerror(title="Error",
                      message= 'Cannot find required executable %s.\n' % arg +
                       'Please make sure that %s is installed ' % moduleName +
                       'and available in your $PATH.' )

    def buildLinks( self, net):
        # Make links
        info( "Getting Links.\n" )
        for key,link in self.links.items():
            tags = self.canvas.gettags(key)
            if 'data' in tags:
                src=link['src']
                dst=link['dest']
                linkopts=link['linkOpts']
                srcName, dstName = src[ 'text' ], dst[ 'text' ]
                if srcName[0] == 'w' or dstName[0] == 'w':
                    # we don't actually need to add hardware switch links to the network
                    break
                srcNode, dstNode = net.nameToNode[ srcName ], net.nameToNode[ dstName ]
                if linkopts:
                    net.addLink(srcNode, dstNode, cls=TCLink, **linkopts)
                else:
                    # debug( str(srcNode) )
                    # debug( str(dstNode), '\n' )
                    net.addLink(srcNode, dstNode)
                self.canvas.itemconfig(key, dash=())


    def build( self ):
        "Build network based on our topology."

        dpctl = None
        if len(self.appPrefs['dpctl']) > 0:
            dpctl = int(self.appPrefs['dpctl'])
        net = Mininet( topo=None,
                       listenPort=dpctl,
                       build=False,
                       ipBase=self.appPrefs['ipBase'] )

        self.buildNodes(net)
        self.buildLinks(net)

        # Build network (we have to do this separately at the moment )
        net.build()

        return net


    def postStartSetup( self ):

        # Setup host details
        for widget, item in self.widgetToItem.items():
            name = widget[ 'text' ]
            tags = self.canvas.gettags( item )
            if 'Host' in tags:
                newHost = self.net.get(name)
                opts = self.hostOpts[name]
                # Attach vlan interfaces
                if 'vlanInterfaces' in opts:
                    for vlanInterface in opts['vlanInterfaces']:
                        info( 'adding vlan interface '+vlanInterface[1], '\n' )
                        newHost.cmdPrint('ifconfig '+name+'-eth0.'+vlanInterface[1]+' '+vlanInterface[0])
                # Run User Defined Start Command
                if 'startCommand' in opts:
                    newHost.cmdPrint(opts['startCommand'])
                # Run other user defined commands
                if 'commands' in opts:
                    for command in opts['commands']:
                        newHost.cmdPrint(command)
            if 'Switch' in tags:
                newNode = self.net.get(name)
                opts = self.switchOpts[name]
                # Run User Defined Start Command
                if 'startCommand' in opts:
                    newNode.cmdPrint(opts['startCommand'])


        # Configure NetFlow
        nflowValues = self.appPrefs['netflow']
        if len(nflowValues['nflowTarget']) > 0:
            nflowEnabled = False
            nflowSwitches = ''
            for widget, item in self.widgetToItem.items():
                name = widget[ 'text' ]
                tags = self.canvas.gettags( item )

                if 'Switch' in tags:
                    opts = self.switchOpts[name]
                    if 'netflow' in opts:
                        if opts['netflow'] == '1':
                            info( name+' has Netflow enabled\n' )
                            nflowSwitches = nflowSwitches+' -- set Bridge '+name+' netflow=@MiniEditNF'
                            nflowEnabled=True
            if nflowEnabled:
                nflowCmd = 'ovs-vsctl -- --id=@MiniEditNF create NetFlow '+ 'target=\\\"'+nflowValues['nflowTarget']+'\\\" '+ 'active-timeout='+nflowValues['nflowTimeout']
                if nflowValues['nflowAddId'] == '1':
                    nflowCmd = nflowCmd + ' add_id_to_interface=true'
                else:
                    nflowCmd = nflowCmd + ' add_id_to_interface=false'
                info( 'cmd = '+nflowCmd+nflowSwitches, '\n' )
                call(nflowCmd+nflowSwitches, shell=True)

            else:
                info( 'No switches with Netflow\n' )
        else:
            info( 'No NetFlow targets specified.\n' )

        # Configure sFlow
        sflowValues = self.appPrefs['sflow']
        if len(sflowValues['sflowTarget']) > 0:
            sflowEnabled = False
            sflowSwitches = ''
            for widget, item in self.widgetToItem.items():
                name = widget[ 'text' ]
                tags = self.canvas.gettags( item )

                if 'Switch' in tags:
                    opts = self.switchOpts[name]
                    if 'sflow' in opts:
                        if opts['sflow'] == '1':
                            info( name+' has sflow enabled\n' )
                            sflowSwitches = sflowSwitches+' -- set Bridge '+name+' sflow=@MiniEditSF'
                            sflowEnabled=True
            if sflowEnabled:
                sflowCmd = 'ovs-vsctl -- --id=@MiniEditSF create sFlow '+ 'target=\\\"'+sflowValues['sflowTarget']+'\\\" '+ 'header='+sflowValues['sflowHeader']+' '+ 'sampling='+sflowValues['sflowSampling']+' '+ 'polling='+sflowValues['sflowPolling']
                info( 'cmd = '+sflowCmd+sflowSwitches, '\n' )
                call(sflowCmd+sflowSwitches, shell=True)

            else:
                info( 'No switches with sflow\n' )
        else:
            info( 'No sFlow targets specified.\n' )

        ## NOTE: MAKE SURE THIS IS LAST THING CALLED
        # Start the CLI if enabled
        if self.appPrefs['startCLI'] == '1':
            info( "\n\n NOTE: PLEASE REMEMBER TO EXIT THE CLI BEFORE YOU PRESS THE STOP BUTTON. Not exiting will prevent MiniEdit from quitting and will prevent you from starting the network again during this session.\n\n")
            CLI(self.net)

    def getLinks(self):
        # get links
        links = []
        for key,link in self.links.items():
            tags = self.canvas.gettags(key)
            if 'data' in tags:
                src=link['src']
                dst=link['dest']
                srcName, dstName = src[ 'text' ], dst[ 'text' ]
                links.append([srcName, dstName])
        return links

    def start( self ):
        "Start network."

        if self.net is None:
            self.net = self.build()

            # Since I am going to inject per switch controllers.
            # I can't call net.start().  I have to replicate what it
            # does and add the controller options.
            #self.net.start()
            info( '**** Starting %s controllers\n' % len( self.net.controllers ) )
            for controller in self.net.controllers:
                info( str(controller) + ' ')
                controller.start()
            info('\n')
            info( '**** Starting %s switches\n' % len( self.net.switches ) )
            #for switch in self.net.switches:
            #    info( switch.name + ' ')
            #    switch.start( self.net.controllers )
            for widget, item in self.widgetToItem.items():
                name = widget[ 'text' ]
                tags = self.canvas.gettags( item )
                if 'Switch' in tags:
                    opts = self.switchOpts[name]
                    switchControllers = []
                    for ctrl in opts['controllers']:
                        switchControllers.append(self.net.get(ctrl))
                    info( name + ' ')
                    # Figure out what controllers will manage this switch
                    self.net.get(name).start( switchControllers )
                if 'LegacySwitch' in tags:
                    self.net.get(name).start( [] )
                    info( name + ' ')
                if 'P4Switch' in tags:
                    self.net.get(name).start( [] )
                    info( name + ' ')
            info('\n')

            self.postStartSetup()

    def stop( self ):
        "Stop network."
        if self.net is not None:
            # Stop host details
            for widget, item in self.widgetToItem.items():
                name = widget[ 'text' ]
                tags = self.canvas.gettags( item )
                if 'Host' in tags:
                    newHost = self.net.get(name)
                    opts = self.hostOpts[name]
                    # Run User Defined Stop Command
                    if 'stopCommand' in opts:
                        newHost.cmdPrint(opts['stopCommand'])
                if 'Switch' in tags:
                    newNode = self.net.get(name)
                    opts = self.switchOpts[name]
                    # Run User Defined Stop Command
                    if 'stopCommand' in opts:
                        newNode.cmdPrint(opts['stopCommand'])

            self.net.stop()
        cleanUpScreens()
        self.net = None

    def do_linkPopup(self, event):
        # display the popup menu
        if self.net is None:
            try:
                self.linkPopup.tk_popup(event.x_root, event.y_root, 0)
            finally:
                # make sure to release the grab (Tk 8.0a1 only)
                self.linkPopup.grab_release()
        else:
            try:
                self.linkRunPopup.tk_popup(event.x_root, event.y_root, 0)
            finally:
                # make sure to release the grab (Tk 8.0a1 only)
                self.linkRunPopup.grab_release()

    def do_controllerPopup(self, event):
        # display the popup menu
        if self.net is None:
            try:
                self.controllerPopup.tk_popup(event.x_root, event.y_root, 0)
            finally:
                # make sure to release the grab (Tk 8.0a1 only)
                self.controllerPopup.grab_release()

    def do_legacyRouterPopup(self, event):
        # display the popup menu
        if self.net is not None:
            try:
                self.legacyRouterRunPopup.tk_popup(event.x_root, event.y_root, 0)
            finally:
                # make sure to release the grab (Tk 8.0a1 only)
                self.legacyRouterRunPopup.grab_release()

    def do_hostPopup(self, event):
        # display the popup menu
        if self.net is None:
            try:
                self.hostPopup.tk_popup(event.x_root, event.y_root, 0)
            finally:
                # make sure to release the grab (Tk 8.0a1 only)
                self.hostPopup.grab_release()
        else:
            try:
                self.hostRunPopup.tk_popup(event.x_root, event.y_root, 0)
            finally:
                # make sure to release the grab (Tk 8.0a1 only)
                self.hostRunPopup.grab_release()

    def do_legacySwitchPopup(self, event):
        # display the popup menu
        if self.net is not None:
            try:
                self.switchRunPopup.tk_popup(event.x_root, event.y_root, 0)
            finally:
                # make sure to release the grab (Tk 8.0a1 only)
                self.switchRunPopup.grab_release()

    def do_switchPopup(self, event):
        # display the popup menu
        if self.net is None:
            try:
                self.switchPopup.tk_popup(event.x_root, event.y_root, 0)
            finally:
                # make sure to release the grab (Tk 8.0a1 only)
                self.switchPopup.grab_release()
        else:
            try:
                self.switchRunPopup.tk_popup(event.x_root, event.y_root, 0)
            finally:
                # make sure to release the grab (Tk 8.0a1 only)
                self.switchRunPopup.grab_release()

    def do_p4SwitchPopup(self, event):
        # display the popup menu
        if self.net is None:
        # Mininet is not running
            try:
                self.p4SwitchPopup.tk_popup(event.x_root, event.y_root, 0)
            finally:
                self.p4SwitchPopup.grab_release()
        else:
        # Mininet is running
            try:
                self.p4SwitchRunPopup.tk_popup(event.x_root, event.y_root, 0)
            finally:
                self.p4SwitchRunPopup.grab_release()

    def do_hardwareSwitchPopup(self, event):
        # display the popup menu
        if not self.net is None:
        # Mininet is running
            try:
                self.hardwareSwitchRunPopup.tk_popup(event.x_root, event.y_root, 0)
            finally:
                self.hardwareSwitchRunPopup.grab_release()
        

    def xterm( self, _ignore=None ):
        "Make an xterm when a button is pressed."
        if ( self.selection is None or
             self.net is None or
             self.selection not in self.itemToWidget ):
            return
        name = self.itemToWidget[ self.selection ][ 'text' ]
        if name not in self.net.nameToNode:
            return
        term = makeTerm( self.net.nameToNode[ name ], 'Host', term=self.appPrefs['terminalType'] )
        if StrictVersion(MININET_VERSION) > StrictVersion('2.0'):
            self.net.terms += term
        else:
            self.net.terms.append(term)

    def iperf( self, _ignore=None ):
        "Make an xterm when a button is pressed."
        if ( self.selection is None or
             self.net is None or
             self.selection not in self.itemToWidget ):
            return
        name = self.itemToWidget[ self.selection ][ 'text' ]
        if name not in self.net.nameToNode:
            return
        self.net.nameToNode[ name ].cmd( 'iperf -s -p 5001 &' )

    ### BELOW HERE IS THE TOPOLOGY IMPORT CODE ###

    def parseArgs( self ):
        """Parse command-line args and return options object.
           returns: opts parse options dict"""

        if '--custom' in sys.argv:
            index = sys.argv.index( '--custom' )
            if len( sys.argv ) > index + 1:
                filename = sys.argv[ index + 1 ]
                self.parseCustomFile( filename )
            else:
                raise Exception( 'Custom file name not found' )

        desc = ( "The %prog utility creates Mininet network from the\n"
                 "command line. It can create parametrized topologies,\n"
                 "invoke the Mininet CLI, and run tests." )

        usage = ( '%prog [options]\n'
                  '(type %prog -h for details)' )

        opts = OptionParser( description=desc, usage=usage )

        addDictOption( opts, TOPOS, TOPODEF, 'topo' )
        addDictOption( opts, LINKS, LINKDEF, 'link' )

        opts.add_option( '--custom', type='string', default=None,
                         help='read custom topo and node params from .py ' +
                         'file' )

        self.options, self.args = opts.parse_args()
        # We don't accept extra arguments after the options
        if self.args:
            opts.print_help()
            exit()

    def setCustom( self, name, value ):
        "Set custom parameters for MininetRunner."
        if name in ( 'topos', 'switches', 'hosts', 'controllers' ):
            # Update dictionaries
            param = name.upper()
            globals()[ param ].update( value )
        elif name == 'validate':
            # Add custom validate function
            self.validate = value
        else:
            # Add or modify global variable or class
            globals()[ name ] = value

    def parseCustomFile( self, fileName ):
        "Parse custom file and add params before parsing cmd-line options."
        customs = {}
        if os.path.isfile( fileName ):
            with open( fileName, 'r' ) as f:
                exec( f.read() )  # pylint: disable=exec-used
            for name, val in customs.items():
                self.setCustom( name, val )
        else:
            raise Exception( 'could not find custom file: %s' % fileName )

    def importTopo( self ):
        info( 'topo='+self.options.topo, '\n' )
        if self.options.topo == 'none':
            return
        self.newTopology()
        topo = buildTopo( TOPOS, self.options.topo )
        link = customClass( LINKS, self.options.link )
        importNet = Mininet(topo=topo, build=False, link=link)
        importNet.build()

        c = self.canvas
        rowIncrement = 100
        currentY = 100

        # Add Controllers
        info( 'controllers:'+str(len(importNet.controllers)), '\n' )
        for controller in importNet.controllers:
            name = controller.name
            x = self.controllerCount*100+100
            self.addNode('Controller', self.controllerCount,
                 float(x), float(currentY), name=name)
            icon = self.findWidgetByName(name)
            icon.bind('<Button-3>', self.do_controllerPopup )
            ctrlr = { 'controllerType': 'ref',
                      'hostname': name,
                      'controllerProtocol': controller.protocol,
                      'remoteIP': controller.ip,
                      'remotePort': controller.port}
            self.controllers[name] = ctrlr



        currentY = currentY + rowIncrement

        # Add switches
        info( 'switches:'+str(len(importNet.switches)), '\n' )
        columnCount = 0
        for switch in importNet.switches:
            name = switch.name
            self.switchOpts[name] = {}
            self.switchOpts[name]['nodeNum']=self.switchCount
            self.switchOpts[name]['hostname']=name
            self.switchOpts[name]['switchType']='default'
            self.switchOpts[name]['controllers']=[]

            x = columnCount*100+100
            self.addNode('Switch', self.switchCount,
                 float(x), float(currentY), name=name)
            icon = self.findWidgetByName(name)
            icon.bind('<Button-3>', self.do_switchPopup )
            # Now link to controllers
            for controller in importNet.controllers:
                self.switchOpts[name]['controllers'].append(controller.name)
                dest = self.findWidgetByName(controller.name)
                dx, dy = c.coords( self.widgetToItem[ dest ] )
                self.link = c.create_line(float(x),
                                          float(currentY),
                                          dx,
                                          dy,
                                          width=4,
                                          fill='red',
                                          dash=(6, 4, 2, 4),
                                          tag='link' )
                c.itemconfig(self.link, tags=c.gettags(self.link)+('control',))
                self.addLink( icon, dest, linktype='control' )
                self.createControlLinkBindings()
                self.link = self.linkWidget = None
            if columnCount == 9:
                columnCount = 0
                currentY = currentY + rowIncrement
            else:
                columnCount =columnCount+1


        currentY = currentY + rowIncrement
        # Add hosts
        info( 'hosts:'+str(len(importNet.hosts)), '\n' )
        columnCount = 0
        for host in importNet.hosts:
            name = host.name
            self.hostOpts[name] = {'sched':'host'}
            self.hostOpts[name]['nodeNum']=self.hostCount
            self.hostOpts[name]['hostname']=name
            self.hostOpts[name]['ip']=host.IP()

            x = columnCount*100+100
            self.addNode('Host', self.hostCount,
                 float(x), float(currentY), name=name)
            icon = self.findWidgetByName(name)
            icon.bind('<Button-3>', self.do_hostPopup )
            if columnCount == 9:
                columnCount = 0
                currentY = currentY + rowIncrement
            else:
                columnCount =columnCount+1

        info( 'links:'+str(len(topo.links())), '\n' )
        #[('h1', 's3'), ('h2', 's4'), ('s3', 's4')]
        for link in topo.links():
            info( str(link), '\n' )
            srcNode = link[0]
            src = self.findWidgetByName(srcNode)
            sx, sy = self.canvas.coords( self.widgetToItem[ src ] )

            destNode = link[1]
            dest = self.findWidgetByName(destNode)
            dx, dy = self.canvas.coords( self.widgetToItem[ dest]  )

            params = topo.linkInfo( srcNode, destNode )
            info( 'Link Parameters='+str(params), '\n' )

            self.link = self.canvas.create_line( sx, sy, dx, dy, width=4,
                                             fill='blue', tag='link' )
            c.itemconfig(self.link, tags=c.gettags(self.link)+('data',))
            self.addLink( src, dest, linkopts=params )
            self.createDataLinkBindings()
            self.link = self.linkWidget = None

        importNet.stop()

def miniEditImages():
    "Create and return images for MiniEdit."

    # Image data. Git will be unhappy. However, the alternative
    # is to keep track of separate binary files, which is also
    # unappealing.

    return {
        'Select': BitmapImage(
            file='/usr/include/X11/bitmaps/left_ptr' ),

        'Switch': PhotoImage( data=r"""
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
            """),

        'LegacySwitch': PhotoImage( data=r"""
R0lGODlhMgAYAPcAAAEBAXmDjbe4uAE5cjF7xwFWq2Sa0S9biSlrrdTW1k2Ly02a5xUvSQFHjmep
6bfI2Q5SlQIYLwFfvj6M3Jaan8fHyDuFzwFp0Vah60uU3AEiRhFgrgFRogFr10N9uTFrpytHYQFM
mGWt9wIwX+bm5kaT4gtFgR1cnJPF9yt80CF0yAIMGHmp2c/P0AEoUb/P4Fei7qK4zgpLjgFkyQlf
t1mf5jKD1WWJrQ86ZwFAgBhYmVOa4MPV52uv8y+A0iR3ywFbtUyX5ECI0Q1UmwIcOUGQ3RBXoQI0
aRJbpr3BxVeJvQUJDafH5wIlS2aq7xBmv52lr7fH12el5Wml3097ph1ru7vM3HCz91Ke6lid40KQ
4GSQvgQGClFnfwVJjszMzVCX3hljrdPT1AFLlBRnutPf6yd5zjeI2QE9eRBdrBNVl+3v70mV4ydf
lwMVKwErVlul8AFChTGB1QE3bsTFxQImTVmAp0FjiUSM1k+b6QQvWQ1SlxMgLgFixEqU3xJhsgFT
pn2Xs5OluZ+1yz1Xb6HN+Td9wy1zuYClykV5r0x2oeDh4qmvt8LDwxhuxRlLfyRioo2124mft9bi
71mDr7fT79nl8Z2hpQs9b7vN4QMQIOPj5XOPrU2Jx32z6xtvwzeBywFFikFnjwcPFa29yxJjuFmP
xQFv3qGxwRc/Z8vb6wsRGBNqwqmpqTdvqQIbNQFPngMzZAEfP0mQ13mHlQFYsAFnznOXu2mPtQxj
vQ1Vn4Ot1+/x8my0/CJgnxNNh8DT5CdJaWyx+AELFWmt8QxPkxBZpwMFB015pgFduGCNuyx7zdnZ
2WKm6h1xyOPp8aW70QtPkUmM0LrCyr/FyztljwFPm0OJzwFny7/L1xFjswE/e12i50iR2VR8o2Gf
3xszS2eTvz2BxSlloQdJiwMHDzF3u7bJ3T2I1WCp8+Xt80FokQFJklef6mORw2ap7SJ1y77Q47nN
3wFfu1Kb5cXJyxdhrdDR0wlNkTSF11Oa4yp4yQEuW0WQ3QIDBQI7dSH5BAEAAAAALAAAAAAyABgA
Bwj/AAEIHDjKF6SDvhImPMHwhA6HOiLqUENRDYSLEIplxBcNHz4Z5GTI8BLKS5OBA1Ply2fDhxwf
PlLITGFmmRkzP+DlVKHCmU9nnz45csSqKKsn9gileZKrVC4aRFACOGZu5UobNuRohRkzhc2b+36o
qCaqrFmzZEV1ERBg3BOmMl5JZTBhwhm7ZyycYZnvJdeuNl21qkCHTiPDhxspTtKoQgUKCJ6wehMV
5QctWupeo6TkjOd8e1lmdQkTGbTTMaDFiDGINeskX6YhEicUiQa5A/kUKaFFwQ0oXzjZ8Tbcm3Hj
irwpMtTSgg9QMJf5WEZ9375AiED19ImpSQSUB4Kw/8HFSMyiRWJaqG/xhf2X91+oCbmq1e/MFD/2
EcApVkWVJhp8J9AqsywQxDfAbLJJPAy+kMkL8shjxTkUnhOJZ5+JVp8cKfhwxwdf4fQLgG4MFAwW
KOZRAxM81EAPPQvoE0QQfrDhx4399OMBMjz2yCMVivCoCAWXKLKMTPvoUYcsKwi0RCcwYCAlFjU0
A6OBM4pXAhsl8FYELYWFWZhiZCbRQgIC2AGTLy408coxAoEDx5wwtGPALTVg0E4NKC7gp4FsBKoA
Ki8U+oIVmVih6DnZPMBMAlGwIARWOLiggSYC+ZNIOulwY4AkSZCyxaikbqHMqaeaIp4+rAaxQxBg
2P+IozuRzvLZIS4syYVAfMAhwhSC1EPCGoskIIYY9yS7Hny75OFnEIAGyiVvWkjjRxF11fXIG3WU
KNA6wghDTCW88PKMJZOkm24Z7LarSjPtoIjFn1lKyyVmmBVhwRtvaDDMgFL0Eu4VhaiDwhXCXNFD
D8QQw7ATEDsBw8RSxotFHs7CKJ60XWrRBj91EOGPQCA48c7J7zTjSTPctOzynjVkkYU+O9S8Axg4
Z6BzBt30003Ps+AhNB5C4PCGC5gKJMMTZJBRytOl/CH1HxvQkMbVVxujtdZGGKGL17rsEfYQe+xR
zNnFcGQCv7LsKlAtp8R9Sgd0032BLXjPoPcMffTd3YcEgAMOxOBA1GJ4AYgXAMjiHDTgggveCgRI
3RfcnffefgcOeDKEG3444osDwgEspMNiTQhx5FoOShxcrrfff0uQjOycD+554qFzMHrpp4cwBju/
5+CmVNbArnntndeCO+O689777+w0IH0o1P/TRJMohRA4EJwn47nyiocOSOmkn/57COxE3wD11Mfh
fg45zCGyVF4Ufvvyze8ewv5jQK9++6FwXxzglwM0GPAfR8AeSo4gwAHCbxsQNCAa/kHBAVhwAHPI
4BE2eIRYeHAEIBwBP0Y4Qn41YWRSCQgAOw==
            """),

        'LegacyRouter': PhotoImage( data=r"""
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
gGPLHwLwcMIo12Qxu0ABAQA7
            """),

        'Controller': PhotoImage( data=r"""
            R0lGODlhMAAwAPcAAAEBAWfNAYWFhcfHx+3t6/f390lJUaWlpfPz8/Hx72lpaZGRke/v77m5uc0B
            AeHh4e/v7WNjY3t7e5eXlyMjI4mJidPT0+3t7f///09PT7Ozs/X19fHx8ZWTk8HBwX9/fwAAAAAA
            AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
            AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
            AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
            AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
            AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
            AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
            AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
            AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
            AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
            AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
            AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
            AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACH5BAEAAAAALAAAAAAwADAA
            Bwj/AAEIHEiwoMGDCBMqXMiwocOHECNKnEixosWLGAEIeMCxo8ePHwVkBGABg8mTKFOmtDByAIYN
            MGPCRCCzQIENNzEMGOkBAwIKQIMKpYCgKAIHCDB4GNkAA4OnUJ9++CDhQ1QGFzA0GKkBA4GvYMOK
            BYtBA1cNaNOqXcuWq8q3b81m7Cqzbk2bMMu6/Tl0qFEEAZLKxdj1KlSqVA3rnet1rOOwiwmznUzZ
            LdzLJgdfpIv3pmebN2Pm1GyRbocNp1PLNMDaAM3Im1/alQk4gO28pCt2RdCBt+/eRg8IP1AUdmmf
            f5MrL56bYlcOvaP7Xo6Ag3HdGDho3869u/YE1507t+3AgLz58ujPMwg/sTBUCAzgy49PH0LW5u0x
            XFiwvz////5dcJ9bjxVIAHsSdUXAAgs2yOCDDn6FYEQaFGDgYxNCpEFfHHKIX4IDhCjiiCSS+CGF
            FlCmogYpcnVABTDGKGOMAlRQYwUHnKjhAjX2aOOPN8LImgAL6PiQBhLMqCSNAThQgQRGOqRBBD1W
            aaOVAggnQARRNqRBBxmEKeaYZIrZQZcMKbDiigqM5OabcMYp55x01ilnQAA7
            """),

        'Host': PhotoImage( data=r"""
            R0lGODlhIAAYAPcAMf//////zP//mf//Zv//M///AP/M///MzP/M
            mf/MZv/MM//MAP+Z//+ZzP+Zmf+ZZv+ZM/+ZAP9m//9mzP9mmf9m
            Zv9mM/9mAP8z//8zzP8zmf8zZv8zM/8zAP8A//8AzP8Amf8AZv8A
            M/8AAMz//8z/zMz/mcz/Zsz/M8z/AMzM/8zMzMzMmczMZszMM8zM
            AMyZ/8yZzMyZmcyZZsyZM8yZAMxm/8xmzMxmmcxmZsxmM8xmAMwz
            /8wzzMwzmcwzZswzM8wzAMwA/8wAzMwAmcwAZswAM8wAAJn//5n/
            zJn/mZn/Zpn/M5n/AJnM/5nMzJnMmZnMZpnMM5nMAJmZ/5mZzJmZ
            mZmZZpmZM5mZAJlm/5lmzJlmmZlmZplmM5lmAJkz/5kzzJkzmZkz
            ZpkzM5kzAJkA/5kAzJkAmZkAZpkAM5kAAGb//2b/zGb/mWb/Zmb/
            M2b/AGbM/2bMzGbMmWbMZmbMM2bMAGaZ/2aZzGaZmWaZZmaZM2aZ
            AGZm/2ZmzGZmmWZmZmZmM2ZmAGYz/2YzzGYzmWYzZmYzM2YzAGYA
            /2YAzGYAmWYAZmYAM2YAADP//zP/zDP/mTP/ZjP/MzP/ADPM/zPM
            zDPMmTPMZjPMMzPMADOZ/zOZzDOZmTOZZjOZMzOZADNm/zNmzDNm
            mTNmZjNmMzNmADMz/zMzzDMzmTMzZjMzMzMzADMA/zMAzDMAmTMA
            ZjMAMzMAAAD//wD/zAD/mQD/ZgD/MwD/AADM/wDMzADMmQDMZgDM
            MwDMAACZ/wCZzACZmQCZZgCZMwCZAABm/wBmzABmmQBmZgBmMwBm
            AAAz/wAzzAAzmQAzZgAzMwAzAAAA/wAAzAAAmQAAZgAAM+4AAN0A
            ALsAAKoAAIgAAHcAAFUAAEQAACIAABEAAADuAADdAAC7AACqAACI
            AAB3AABVAABEAAAiAAARAAAA7gAA3QAAuwAAqgAAiAAAdwAAVQAA
            RAAAIgAAEe7u7t3d3bu7u6qqqoiIiHd3d1VVVURERCIiIhEREQAA
            ACH5BAEAAAAALAAAAAAgABgAAAiNAAH8G0iwoMGDCAcKTMiw4UBw
            BPXVm0ixosWLFvVBHFjPoUeC9Tb+6/jRY0iQ/8iVbHiS40CVKxG2
            HEkQZsyCM0mmvGkw50uePUV2tEnOZkyfQA8iTYpTKNOgKJ+C3AhO
            p9SWVaVOfWj1KdauTL9q5UgVbFKsEjGqXVtP40NwcBnCjXtw7tx/
            C8cSBBAQADs=
        """ ),

        'P4Switch': PhotoImage(data="""iVBORw0KGgoAAAANSUhEUgAAA
            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
            K5CYII=
        """),

        'HardwareSwitch': PhotoImage(data=r"""iVBORw0KGgoAAAANSU
            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
            SuQmCC"""),


        'OldSwitch': PhotoImage( data=r"""
            R0lGODlhIAAYAPcAMf//////zP//mf//Zv//M///AP/M///MzP/M
            mf/MZv/MM//MAP+Z//+ZzP+Zmf+ZZv+ZM/+ZAP9m//9mzP9mmf9m
            Zv9mM/9mAP8z//8zzP8zmf8zZv8zM/8zAP8A//8AzP8Amf8AZv8A
            M/8AAMz//8z/zMz/mcz/Zsz/M8z/AMzM/8zMzMzMmczMZszMM8zM
            AMyZ/8yZzMyZmcyZZsyZM8yZAMxm/8xmzMxmmcxmZsxmM8xmAMwz
            /8wzzMwzmcwzZswzM8wzAMwA/8wAzMwAmcwAZswAM8wAAJn//5n/
            zJn/mZn/Zpn/M5n/AJnM/5nMzJnMmZnMZpnMM5nMAJmZ/5mZzJmZ
            mZmZZpmZM5mZAJlm/5lmzJlmmZlmZplmM5lmAJkz/5kzzJkzmZkz
            ZpkzM5kzAJkA/5kAzJkAmZkAZpkAM5kAAGb//2b/zGb/mWb/Zmb/
            M2b/AGbM/2bMzGbMmWbMZmbMM2bMAGaZ/2aZzGaZmWaZZmaZM2aZ
            AGZm/2ZmzGZmmWZmZmZmM2ZmAGYz/2YzzGYzmWYzZmYzM2YzAGYA
            /2YAzGYAmWYAZmYAM2YAADP//zP/zDP/mTP/ZjP/MzP/ADPM/zPM
            zDPMmTPMZjPMMzPMADOZ/zOZzDOZmTOZZjOZMzOZADNm/zNmzDNm
            mTNmZjNmMzNmADMz/zMzzDMzmTMzZjMzMzMzADMA/zMAzDMAmTMA
            ZjMAMzMAAAD//wD/zAD/mQD/ZgD/MwD/AADM/wDMzADMmQDMZgDM
            MwDMAACZ/wCZzACZmQCZZgCZMwCZAABm/wBmzABmmQBmZgBmMwBm
            AAAz/wAzzAAzmQAzZgAzMwAzAAAA/wAAzAAAmQAAZgAAM+4AAN0A
            ALsAAKoAAIgAAHcAAFUAAEQAACIAABEAAADuAADdAAC7AACqAACI
            AAB3AABVAABEAAAiAAARAAAA7gAA3QAAuwAAqgAAiAAAdwAAVQAA
            RAAAIgAAEe7u7t3d3bu7u6qqqoiIiHd3d1VVVURERCIiIhEREQAA
            ACH5BAEAAAAALAAAAAAgABgAAAhwAAEIHEiwoMGDCBMqXMiwocOH
            ECNKnEixosWB3zJq3Mixo0eNAL7xG0mypMmTKPl9Cznyn8uWL/m5
            /AeTpsyYI1eKlBnO5r+eLYHy9Ck0J8ubPmPOrMmUpM6UUKMa/Ui1
            6saLWLNq3cq1q9evYB0GBAA7
        """ ),

        'NetLink': PhotoImage( data=r"""
            R0lGODlhFgAWAPcAMf//////zP//mf//Zv//M///AP/M///MzP/M
            mf/MZv/MM//MAP+Z//+ZzP+Zmf+ZZv+ZM/+ZAP9m//9mzP9mmf9m
            Zv9mM/9mAP8z//8zzP8zmf8zZv8zM/8zAP8A//8AzP8Amf8AZv8A
            M/8AAMz//8z/zMz/mcz/Zsz/M8z/AMzM/8zMzMzMmczMZszMM8zM
            AMyZ/8yZzMyZmcyZZsyZM8yZAMxm/8xmzMxmmcxmZsxmM8xmAMwz
            /8wzzMwzmcwzZswzM8wzAMwA/8wAzMwAmcwAZswAM8wAAJn//5n/
            zJn/mZn/Zpn/M5n/AJnM/5nMzJnMmZnMZpnMM5nMAJmZ/5mZzJmZ
            mZmZZpmZM5mZAJlm/5lmzJlmmZlmZplmM5lmAJkz/5kzzJkzmZkz
            ZpkzM5kzAJkA/5kAzJkAmZkAZpkAM5kAAGb//2b/zGb/mWb/Zmb/
            M2b/AGbM/2bMzGbMmWbMZmbMM2bMAGaZ/2aZzGaZmWaZZmaZM2aZ
            AGZm/2ZmzGZmmWZmZmZmM2ZmAGYz/2YzzGYzmWYzZmYzM2YzAGYA
            /2YAzGYAmWYAZmYAM2YAADP//zP/zDP/mTP/ZjP/MzP/ADPM/zPM
            zDPMmTPMZjPMMzPMADOZ/zOZzDOZmTOZZjOZMzOZADNm/zNmzDNm
            mTNmZjNmMzNmADMz/zMzzDMzmTMzZjMzMzMzADMA/zMAzDMAmTMA
            ZjMAMzMAAAD//wD/zAD/mQD/ZgD/MwD/AADM/wDMzADMmQDMZgDM
            MwDMAACZ/wCZzACZmQCZZgCZMwCZAABm/wBmzABmmQBmZgBmMwBm
            AAAz/wAzzAAzmQAzZgAzMwAzAAAA/wAAzAAAmQAAZgAAM+4AAN0A
            ALsAAKoAAIgAAHcAAFUAAEQAACIAABEAAADuAADdAAC7AACqAACI
            AAB3AABVAABEAAAiAAARAAAA7gAA3QAAuwAAqgAAiAAAdwAAVQAA
            RAAAIgAAEe7u7t3d3bu7u6qqqoiIiHd3d1VVVURERCIiIhEREQAA
            ACH5BAEAAAAALAAAAAAWABYAAAhIAAEIHEiwoEGBrhIeXEgwoUKG
            Cx0+hGhQoiuKBy1irChxY0GNHgeCDAlgZEiTHlFuVImRJUWXEGEy
            lBmxI8mSNknm1Dnx5sCAADs=
        """ )

    }

def addDictOption( opts, choicesDict, default, name, helpStr=None ):
    """Convenience function to add choices dicts to OptionParser.
       opts: OptionParser instance
       choicesDict: dictionary of valid choices, must include default
       default: default choice key
       name: long option name
       help: string"""
    if default not in choicesDict:
        raise Exception( 'Invalid  default %s for choices dict: %s' %
                         ( default, name ) )
    if not helpStr:
        helpStr = ( '|'.join( sorted( choicesDict.keys() ) ) +
                    '[,param=value...]' )
    opts.add_option( '--' + name,
                     type='string',
                     default = default,
                     help = helpStr )

if __name__ == '__main__':
    setLogLevel( 'info' )
    app = MiniEdit()
    app.parseArgs()
    ### import topology if specified ###
    app.importTopo()
    app.mainloop()
