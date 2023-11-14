# Copyright 2014 Red Hat, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


"""
Mapping of boot devices used when requesting the system to boot
from an alternate device.

The options presented were based on the IPMItool chassis
bootdev command. You can find the documentation at:
http://linux.die.net/man/1/ipmitool

NOTE: This module does not include all the options from ipmitool because
they don't make sense in the limited context of Ironic right now.
"""

PXE = 'pxe'
"Boot from PXE boot"

DISK = 'disk'
"Boot from default Hard-drive"

CDROM = 'cdrom'
"Boot from CD/DVD"

BIOS = 'bios'
"Boot into BIOS setup"

SAFE = 'safe'
"Boot from default Hard-drive, request Safe Mode"

WANBOOT = 'wanboot'
"Boot from Wide Area Network"

ISCSIBOOT = 'iscsiboot'
"Boot from iSCSI volume"

FLOPPY = 'floppy'
"Boot from a floppy drive"

VMEDIA_DEVICES = [DISK, CDROM, FLOPPY]
"""Devices that make sense for virtual media attachment."""

UEFIHTTP = "uefihttp"
"Boot from a UEFI HTTP(s) URL"
