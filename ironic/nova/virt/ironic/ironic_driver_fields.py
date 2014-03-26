# coding=utf-8
#
# Copyright 2014 Hewlett-Packard Development Company, L.P.
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
#
#   Values should be a list of dicts. Where each dict is
#    {'ironic_path': '/driver_info', 'ironic_variable': 'pxe_image_source',
#     'nova_object': 'image_meta', 'object_field': "['id']"}

"""
Ironic driver required info mapping.
"""


class FAKE(object):
    """Required and optional field list for ironic's FAKE driver."""
    required = []
    optional = []


class PXE(object):
    """Required and optional field list for ironic's PXE driver."""
    required = [
                {'ironic_path': '/driver_info',
                 'ironic_variable': 'pxe_image_source',
                 'nova_object': 'image_meta',
                 'object_field': 'id'},
                {'ironic_path': '/driver_info',
                 'ironic_variable': 'pxe_root_gb',
                 'nova_object': 'instance',
                 'object_field': 'root_gb'},
                {'ironic_path': '/driver_info',
                 'ironic_variable': 'pxe_swap_mb',
                 'nova_object': 'flavor',
                 'object_field': 'swap'},
                {'ironic_path': '/driver_info',
                 'ironic_variable': 'pxe_deploy_kernel',
                 'nova_object': 'flavor',
                 'object_field': 'extra_specs/'
                                 'baremetal:deploy_kernel_id'},
                {'ironic_path': '/driver_info',
                 'ironic_variable': 'pxe_deploy_ramdisk',
                 'nova_object': 'flavor',
                 'object_field': 'extra_specs/'
                                 'baremetal:deploy_ramdisk_id'}
               ]

    optional = []
