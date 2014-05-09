# coding=utf-8
#
# Copyright 2014 Hewlett-Packard Development Company, L.P.
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
#
"""
Helper classes for Ironic HTTP PATCH creation.
"""

from oslo.config import cfg

from nova.openstack.common import log as logging
from nova import exception

CONF = cfg.CONF
CONF.import_opt('default_ephemeral_format', 'nova.virt.driver')
LOG = logging.getLogger(__name__)


def create(node):
    """Create an instance of the appropriate DriverFields class.

    :param node: a dict containing an Ironic node
    :returns: GenericDriverFields or a subclass thereof, as appropriate
              for the supplied node.
    """
    if 'pxe' in node.driver:
        return PXEDriverFields(node)
    else:
        return GenericDriverFields(node)


class GenericDriverFields(object):

    def __init__(self, node):
        self.node = node

    def get_deploy_patch(self, instance, image_meta, flavor):
        return []

    def get_cleanup_patch(self, instance, network_info):
        return []


class PXEDriverFields(GenericDriverFields):

    def _get_kernel_ramdisk_id(self, flavor):
        values = []
        extra_specs = flavor['extra_specs']
        for key in ['baremetal:deploy_kernel_id',
                    'baremetal:deploy_ramdisk_id']:
            try:
                values.append(extra_specs[key])
            except KeyError:
                msg = (_("'%s' not found in flavor's extra_specs") % key)
                LOG.error(msg)
                raise exception.InvalidParameterValue(message=msg)
        return values

    def get_deploy_patch(self, instance, image_meta, flavor):
        """Build a patch to add the required fields to deploy a node.

        Build a json-patch to add the required fields to deploy a node
        using the PXE driver.

        :param instance: the instance object.
        :param image_meta: the metadata associated with the instance
                            image.
        :param flavor: the flavor object.
        :returns: a json-patch with the fields that needs to be updated.

        """
        patch = []
        deploy_kernel, deploy_ramdisk = self._get_kernel_ramdisk_id(flavor)
        patch.append({'path': '/driver_info/pxe_deploy_kernel', 'op': 'add',
                      'value': deploy_kernel})
        patch.append({'path': '/driver_info/pxe_deploy_ramdisk', 'op': 'add',
                      'value': deploy_ramdisk})
        patch.append({'path': '/driver_info/pxe_image_source', 'op': 'add',
                      'value': image_meta['id']})
        patch.append({'path': '/driver_info/pxe_root_gb', 'op': 'add',
                      'value': str(instance['root_gb'])})
        patch.append({'path': '/driver_info/pxe_swap_mb', 'op': 'add',
                      'value': str(flavor['swap'])})

        if instance.get('ephemeral_gb'):
            patch.append({'path': '/driver_info/pxe_ephemeral_gb',
                          'op': 'add',
                          'value': str(instance['ephemeral_gb'])})
            if CONF.default_ephemeral_format:
                patch.append({'path': '/driver_info/pxe_ephemeral_format',
                              'op': 'add',
                              'value': CONF.default_ephemeral_format})
        return patch

    def get_cleanup_patch(self, instance, network_info):
        """Build a patch to clean up the fields.

        Build a json-patch to remove the fields used to deploy a node
        using the PXE driver.

        :param instance: the instance object.
        :param network_info: the instance network information.
        :returns: a json-patch with the fields that needs to be updated.

        """
        patch = []
        driver_info = self.node.driver_info
        fields = ['pxe_image_source', 'pxe_root_gb', 'pxe_swap_mb',
                  'pxe_deploy_kernel', 'pxe_deploy_ramdisk',
                  'pxe_ephemeral_gb', 'pxe_ephemeral_format',
                  'pxe_preserve_ephemeral']
        for field in fields:
            if field in driver_info:
                patch.append({'op': 'remove',
                              'path': '/driver_info/%s' % field})
        return patch
