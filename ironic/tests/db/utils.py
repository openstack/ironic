# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
"""Ironic test utilities."""

from ironic.common import states


def get_test_ipmi_info():
    return {
        "ipmi_address": "1.2.3.4",
        "ipmi_username": "admin",
        "ipmi_password": "fake",
    }


def get_test_ssh_info(auth_type='password'):
    result = {
        "ssh_address": "1.2.3.4",
        "ssh_username": "admin",
        "ssh_port": 22,
        "ssh_virt_type": "vbox",
    }
    if 'password' == auth_type:
        result['ssh_password'] = 'fake'
    elif 'file' == auth_type:
        result['ssh_key_filename'] = '/not/real/file'
    elif 'key' == auth_type:
        result['ssh_key_contents'] = '--BEGIN PRIVATE ...blah'
    elif 'too_many' == auth_type:
        result['ssh_password'] = 'fake'
        result['ssh_key_filename'] = '/not/real/file'
    else:
        # No auth details (is invalid)
        pass
    return result


def get_test_pxe_info():
    return {
        "pxe_image_source": "glance://image_uuid",
        "pxe_deploy_kernel": "glance://deploy_kernel_uuid",
        "pxe_deploy_ramdisk": "glance://deploy_ramdisk_uuid",
        "pxe_root_gb": 100,
    }


def get_test_seamicro_info():
    return {
        "seamicro_api_endpoint": "http://1.2.3.4",
        "seamicro_username": "admin",
        "seamicro_password": "fake",
        "seamicro_server_id": "0/0",
    }


def get_test_node(**kw):
    properties = {
        "cpu_arch": "x86_64",
        "cpu_num": "8",
        "storage": "1024",
        "memory": "4096",
    }
    fake_info = {"foo": "bar"}
    return {
        'id': kw.get('id', 123),
        'uuid': kw.get('uuid', '1be26c0b-03f2-4d2e-ae87-c02d7f33c123'),
        'chassis_id': kw.get('chassis_id', 42),
        'power_state': kw.get('power_state', states.NOSTATE),
        'target_power_state': kw.get('target_power_state', states.NOSTATE),
        'provision_state': kw.get('provision_state', states.NOSTATE),
        'target_provision_state': kw.get('target_provision_state',
                                         states.NOSTATE),
        'provision_updated_at': kw.get('provision_updated_at'),
        'last_error': kw.get('last_error'),
        'instance_uuid': kw.get('instance_uuid'),
        'driver': kw.get('driver', 'fake'),
        'driver_info': kw.get('driver_info', fake_info),
        'properties': kw.get('properties', properties),
        'reservation': kw.get('reservation'),
        'maintenance': kw.get('maintenance', False),
        'console_enabled': kw.get('console_enabled', False),
        'extra': kw.get('extra', {}),
        'updated_at': kw.get('created_at'),
        'created_at': kw.get('updated_at'),
    }


def get_test_port(**kw):
    return {
        'id': kw.get('id', 987),
        'uuid': kw.get('uuid', '1be26c0b-03f2-4d2e-ae87-c02d7f33c781'),
        'node_id': kw.get('node_id', 123),
        'address': kw.get('address', '52:54:00:cf:2d:31'),
        'extra': kw.get('extra', {}),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }


def get_test_chassis(**kw):
    return {
        'id': kw.get('id', 42),
        'uuid': kw.get('uuid', 'e74c40e0-d825-11e2-a28f-0800200c9a66'),
        'extra': kw.get('extra', {}),
        'description': kw.get('description', 'data-center-1-chassis'),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }


def get_test_conductor(**kw):
    return {
        'id': kw.get('id', 6),
        'hostname': kw.get('hostname', 'test-conductor-node'),
        'drivers': kw.get('drivers', ['fake-driver', 'null-driver']),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }
