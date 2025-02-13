#!/bin/bash
for intf in $(ls /sys/class/net | grep -E "^br-.*"); do
    ip link del $intf
done