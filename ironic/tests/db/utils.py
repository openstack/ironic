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

from ironic.db.sqlalchemy import models
from ironic.openstack.common import jsonutils as json


_control_info = json.dumps(
        {
            "ipmi_address": "1.2.3.4",
            "ipmi_username": "admin",
            "ipmi_password": "fake",
         })

_deploy_info = json.dumps(
        {
            "image_path": "/path/to/image.qcow2",
            "image_source": "glance://image-uuid",
            "deploy_image_source": "glance://deploy-image-uuid",
        })

_properties = json.dumps(
        {
            "cpu_arch": "x86_64",
            "cpu_num": 8,
            "storage": 1024,
            "memory": 4096,
        })


def get_test_node(**kw):
    node = models.Node()

    node.id = kw.get('id', 123)
    node.uuid = kw.get('uuid', '1be26c0b-03f2-4d2e-ae87-c02d7f33c123')
    node.task_state = kw.get('task_state', 'NOSTATE')
    node.instance_uuid = kw.get('instance_uuid',
                                '8227348d-5f1d-4488-aad1-7c92b2d42504')

    node.control_driver = kw.get('control_driver', 'ipmi')
    node.control_info = kw.get('control_info', _control_info)

    node.deploy_driver = kw.get('deploy_driver', 'pxe')
    node.deploy_info = kw.get('deploy_info', _deploy_info)

    node.properties = kw.get('properties', _properties)

    return node


def get_test_iface(**kw):
    iface = models.Iface()
    iface.id = kw.get('id', 987)
    iface.node_id = kw.get('node_id', 123)
    iface.address = kw.get('address', '52:54:00:cf:2d:31')

    return iface
