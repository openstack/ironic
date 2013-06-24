# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from ironic.openstack.common import jsonutils as json


fake_info = json.dumps({"foo": "bar"})

ipmi_info = json.dumps(
        {
            'ipmi': {
                "address": "1.2.3.4",
                "username": "admin",
                "password": "fake",
            }
         })

ssh_info = json.dumps(
        {
            'ssh': {
                "address": "1.2.3.4",
                "username": "admin",
                "password": "fake",
                "port": 22,
                "virt_type": "vbox",
                "key_filename": "/not/real/file",
            }
         })

pxe_info = json.dumps(
        {
            'pxe': {
                "image_path": "/path/to/image.qcow2",
                "image_source": "glance://image-uuid",
                "deploy_image_source": "glance://deploy-image-uuid",
            }
        })

pxe_ssh_info = json.dumps(
        dict(json.loads(pxe_info), **json.loads(ssh_info)))

pxe_ipmi_info = json.dumps(
        dict(json.loads(pxe_info), **json.loads(ipmi_info)))

properties = json.dumps(
        {
            "cpu_arch": "x86_64",
            "cpu_num": 8,
            "storage": 1024,
            "memory": 4096,
        })


def get_test_node(**kw):
    node = {
            'id': kw.get('id', 123),
            'uuid': kw.get('uuid', '1be26c0b-03f2-4d2e-ae87-c02d7f33c123'),
            'chassis_id': 5,
            'task_start': None,
            'task_state': kw.get('task_state', 'NOSTATE'),
            'instance_uuid': kw.get('instance_uuid',
                                    '8227348d-5f1d-4488-aad1-7c92b2d42504'),
            'driver': kw.get('driver', 'fake'),
            'driver_info': kw.get('driver_info', fake_info),
            'properties': kw.get('properties', properties),
            'reservation': None,
            'extra': kw.get('extra', {}),
            'updated_at': None,
            'created_at': None,
            }
    return node


def get_test_port(**kw):
    port = {
        'id': kw.get('id', 987),
        'uuid': kw.get('uuid', '1be26c0b-03f2-4d2e-ae87-c02d7f33c781'),
        'node_id': kw.get('node_id', 123),
        'address': kw.get('address', '52:54:00:cf:2d:31'),
        'extra': kw.get('extra', {}),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }

    return port


def get_test_chassis(**kw):
    chassis = {
        'id': kw.get('id', 42),
        'uuid': kw.get('uuid', 'e74c40e0-d825-11e2-a28f-0800200c9a66'),
        'extra': kw.get('extra', {}),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }

    return chassis
