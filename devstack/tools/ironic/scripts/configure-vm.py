#!/usr/bin/env python3
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
import string
import sys

import jinja2
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
    parser.add_argument('--image', action='append', default=[],
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
    parser.add_argument('--interface-count', default=1, type=int,
                        help='The number of interfaces to add to VM.'),
    parser.add_argument('--mac', default=None,
                        help='The mac for the first interface on the vm')
    parser.add_argument('--console-log',
                        help='File to log console')
    parser.add_argument('--emulator', default=None,
                        help='Path to emulator bin for vm template')
    parser.add_argument('--disk-format', default='qcow2',
                        help='Disk format to use.')
    parser.add_argument('--uefi-loader', default='',
                        help='The absolute path of the UEFI firmware blob.')
    parser.add_argument('--uefi-nvram', default='',
                        help=('The absolute path of the non-volatile memory '
                              'to store the UEFI variables. Should be used '
                              'only when --uefi-loader is also specified.'))
    args = parser.parse_args()

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(templatedir))
    template = env.get_template('vm.xml')

    images = list(zip(args.image, string.ascii_lowercase))
    if not images or len(images) > 6:
        # 6 is an artificial limitation because of the way we generate PCI IDs
        sys.exit("Up to 6 images are required")

    params = {
        'name': args.name,
        'images': images,
        'engine': args.engine,
        'arch': args.arch,
        'memory': args.memory,
        'cpus': args.cpus,
        'bootdev': args.bootdev,
        'interface_count': args.interface_count,
        'mac': args.mac,
        'nicdriver': args.libvirt_nic_driver,
        'emulator': args.emulator,
        'disk_format': args.disk_format,
        'uefi_loader': args.uefi_loader,
        'uefi_nvram': args.uefi_nvram,
    }

    if args.emulator:
        params['emulator'] = args.emulator
    else:
        qemu_kvm_locations = ['/usr/bin/kvm',
                              '/usr/bin/qemu-kvm',
                              '/usr/libexec/qemu-kvm']
        for location in qemu_kvm_locations:
            if os.path.exists(location):
                params['emulator'] = location
                break
        else:
            raise RuntimeError("Unable to find location of kvm executable")

    if args.console_log:
        params['console'] = CONSOLE_LOG % {'console_log': args.console_log}
    else:
        params['console'] = CONSOLE_PTY
    libvirt_template = template.render(**params)
    conn = libvirt.open("qemu:///system")

    a = conn.defineXML(libvirt_template)
    print("Created machine %s with UUID %s" % (args.name, a.UUIDString()))


if __name__ == '__main__':
    main()
