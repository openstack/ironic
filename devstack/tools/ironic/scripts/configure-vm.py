#!/usr/bin/env python
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


import argparse
import os.path

import libvirt

templatedir = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           'templates')


CONSOLE_LOG = """
    <serial type='file'>
      <source path='%(console_log)s'/>
      <target port='0'/>
      <alias name='serial0'/>
    </serial>
    <serial type='pty'>
      <source path='/dev/pts/49'/>
      <target port='1'/>
      <alias name='serial1'/>
    </serial>
    <console type='file'>
      <source path='%(console_log)s'/>
      <target type='serial' port='0'/>
      <alias name='serial0'/>
    </console>
"""


CONSOLE_PTY = """
    <serial type='pty'>
      <target port='0'/>
    </serial>
    <console type='pty'>
      <target type='serial' port='0'/>
    </console>
"""


def main():
    parser = argparse.ArgumentParser(
        description="Configure a kvm virtual machine for the seed image.")
    parser.add_argument('--name', default='seed',
                        help='the name to give the machine in libvirt.')
    parser.add_argument('--image',
                        help='Use a custom image file (must be qcow2).')
    parser.add_argument('--engine', default='qemu',
                        help='The virtualization engine to use')
    parser.add_argument('--arch', default='i686',
                        help='The architecture to use')
    parser.add_argument('--memory', default='2097152',
                        help="Maximum memory for the VM in KB.")
    parser.add_argument('--cpus', default='1',
                        help="CPU count for the VM.")
    parser.add_argument('--bootdev', default='hd',
                        help="What boot device to use (hd/network).")
    parser.add_argument('--libvirt-nic-driver', default='virtio',
                        help='The libvirt network driver to use')
    parser.add_argument('--bridge', default="br-seed",
                        help='The linux bridge name to use for seeding \
                                the baremetal pseudo-node\'s OS image')
    parser.add_argument('--console-log',
                        help='File to log console')
    parser.add_argument('--emulator', default=None,
                        help='Path to emulator bin for vm template')
    parser.add_argument('--disk-format', default='qcow2',
                        help='Disk format to use.')
    args = parser.parse_args()
    with open(templatedir + '/vm.xml', 'rb') as f:
        source_template = f.read()
    params = {
        'name': args.name,
        'imagefile': args.image,
        'engine': args.engine,
        'arch': args.arch,
        'memory': args.memory,
        'cpus': args.cpus,
        'bootdev': args.bootdev,
        'bridge': args.bridge,
        'nicdriver': args.libvirt_nic_driver,
        'emulator': args.emulator,
        'disk_format': args.disk_format
    }

    if args.emulator:
        params['emulator'] = args.emulator
    else:
        if os.path.exists("/usr/bin/kvm"):  # Debian
            params['emulator'] = "/usr/bin/kvm"
        elif os.path.exists("/usr/bin/qemu-kvm"):  # Redhat
            params['emulator'] = "/usr/bin/qemu-kvm"

    if args.console_log:
        params['console'] = CONSOLE_LOG % {'console_log': args.console_log}
    else:
        params['console'] = CONSOLE_PTY
    libvirt_template = source_template % params
    conn = libvirt.open("qemu:///system")

    a = conn.defineXML(libvirt_template)
    print("Created machine %s with UUID %s" % (args.name, a.UUIDString()))

if __name__ == '__main__':
    main()
