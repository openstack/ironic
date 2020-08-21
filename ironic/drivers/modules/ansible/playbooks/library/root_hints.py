# -*- coding: utf-8 -*-
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

GIB = 1 << 30

EXTRA_PARAMS = set(['wwn', 'serial', 'wwn_with_extension',
                    'wwn_vendor_extension'])

IGNORE_DEVICES = ['sr', 'loop', 'mem', 'fd']


# NOTE: ansible calculates device size as float with 2-digits precision,
# Ironic requires size in GiB, if we will use ansible size parameter
# a bug is possible for devices > 1 TB
def size_gib(device_info):
    sectors = device_info.get('sectors')
    sectorsize = device_info.get('sectorsize')
    if sectors is None or sectorsize is None:
        return '0'

    return str((int(sectors) * int(sectorsize)) // GIB)


def merge_devices_info(devices, devices_wwn):
    merged_info = devices.copy()
    for device in merged_info:
        if device in devices_wwn:
            merged_info[device].update(devices_wwn[device])

        # replace size
        merged_info[device]['size'] = size_gib(merged_info[device])

    return merged_info


def root_hint(hints, devices):
    hint = None
    name = hints.pop('name', None)
    for device in devices:
        if any(x in device for x in IGNORE_DEVICES):
            # NOTE(TheJulia): Devices like CD roms, Loop devices, and ramdisks
            # should not be considered as target devices.
            continue
        for key in hints:
            if hints[key] != devices[device].get(key):
                break
        else:
            # If multiple hints are specified, a device must satisfy all
            # the hints
            dev_name = '/dev/' + device
            if name is None or name == dev_name:
                hint = dev_name
                break

    return hint


def main():
    module = AnsibleModule(  # noqa This is normal for Ansible modules.
        argument_spec=dict(
            root_device_hints=dict(required=True, type='dict'),
            ansible_devices=dict(required=True, type='dict'),
            ansible_devices_wwn=dict(required=True, type='dict')
        ),
        supports_check_mode=True)

    hints = module.params['root_device_hints']
    devices = module.params['ansible_devices']
    devices_wwn = module.params['ansible_devices_wwn']

    if not devices_wwn:
        extra = set(hints) & EXTRA_PARAMS
        if extra:
            module.fail_json(msg='Extra hints (supported by additional ansible'
                             ' module) are set but this information can not be'
                             ' collected. Extra hints: %s' % ', '.join(extra))

    devices_info = merge_devices_info(devices, devices_wwn or {})
    hint = root_hint(hints, devices_info)

    if hint is None:
        module.fail_json(msg='Root device hints are set, but none of the '
                         'devices satisfy them. Collected devices info: %s'
                         % devices_info)

    ret_data = {'ansible_facts': {'ironic_root_device': hint}}
    module.exit_json(**ret_data)


from ansible.module_utils.basic import *  # noqa
if __name__ == '__main__':
    main()
