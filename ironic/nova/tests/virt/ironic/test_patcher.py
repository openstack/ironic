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

from oslo.config import cfg

from ironic.nova.virt.ironic import patcher
from ironic.nova.tests.virt.ironic import utils as ironic_utils

from nova import exception
from nova import context as nova_context
from nova import test
from nova.objects.flavor import Flavor as flavor_obj
from nova.tests import fake_instance

CONF = cfg.CONF


class IronicDriverFieldsTestCase(test.NoDBTestCase):

    def setUp(self):
        super(IronicDriverFieldsTestCase, self).setUp()
        self.image_meta = ironic_utils.get_test_image_meta()
        self.flavor = ironic_utils.get_test_flavor()
        self.ctx = nova_context.get_admin_context()

    def test_pxe_get_deploy_patch(self):
        node = ironic_utils.get_test_node(driver='pxe_fake')
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)
        extra_specs = self.flavor['extra_specs']
        expected = [{'path': '/driver_info/pxe_deploy_kernel',
                     'value': extra_specs['baremetal:deploy_kernel_id'],
                     'op': 'add'},
                    {'path': '/driver_info/pxe_deploy_ramdisk',
                     'value': extra_specs['baremetal:deploy_ramdisk_id'],
                     'op': 'add'},
                    {'path': '/instance_info/image_source',
                     'value': self.image_meta['id'],
                     'op': 'add'},
                    {'path': '/instance_info/root_gb',
                     'value': str(instance['root_gb']),
                     'op': 'add'},
                    {'path': '/instance_info/swap_mb',
                     'value': str(self.flavor['swap']),
                     'op': 'add'}]
        patch = patcher.create(node).get_deploy_patch(
                instance, self.image_meta, self.flavor)
        self.assertEqual(sorted(expected), sorted(patch))

    def test_pxe_get_deploy_patch_with_ephemeral(self):
        node = ironic_utils.get_test_node(driver='pxe_fake')
        instance = fake_instance.fake_instance_obj(
                        self.ctx, node=node.uuid, ephemeral_gb=10)
        CONF.set_override('default_ephemeral_format', 'testfmt')
        patch = patcher.create(node).get_deploy_patch(
                instance, self.image_meta, self.flavor)
        expected1 = {'path': '/instance_info/ephemeral_gb',
                     'value': '10', 'op': 'add'}
        expected2 = {'path': '/instance_info/ephemeral_format',
                     'value': 'testfmt', 'op': 'add'}
        self.assertIn(expected1, patch)
        self.assertIn(expected2, patch)

    def test_pxe_get_deploy_patch_no_flavor_kernel_ramdisk_ids(self):
        self.flavor = ironic_utils.get_test_flavor(extra_specs={})
        node = ironic_utils.get_test_node(driver='pxe_fake')
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)
        expected = [{'path': '/instance_info/image_source',
                     'value': self.image_meta['id'],
                     'op': 'add'},
                    {'path': '/instance_info/root_gb',
                     'value': str(instance['root_gb']),
                     'op': 'add'},
                    {'path': '/instance_info/swap_mb',
                     'value': str(self.flavor['swap']),
                     'op': 'add'}]
        patch = patcher.create(node).get_deploy_patch(
                instance, self.image_meta, self.flavor)
        self.assertEqual(sorted(expected), sorted(patch))

    def test_pxe_get_cleanup_patch(self):
        driver_info = {'pxe_deploy_kernel': 'fake-kernel-id',
                       'pxe_deploy_ramdisk': 'fake-ramdisk-id'}
        node = ironic_utils.get_test_node(driver='pxe_fake',
                                          driver_info=driver_info)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)
        patch = patcher.create(node).get_cleanup_patch(instance, None,
                                                       self.flavor)
        expected = [{'path': '/driver_info/pxe_deploy_kernel',
                     'op': 'remove'},
                    {'path': '/driver_info/pxe_deploy_ramdisk',
                     'op': 'remove'}]
        self.assertEqual(sorted(expected), sorted(patch))

    def test_pxe_get_cleanup_patch_no_flavor_kernel_ramdisk_ids(self):
        self.flavor = ironic_utils.get_test_flavor(extra_specs={})
        driver_info = {'pxe_deploy_kernel': 'fake-kernel-id',
                       'pxe_deploy_ramdisk': 'fake-ramdisk-id'}
        node = ironic_utils.get_test_node(driver='pxe_fake',
                                          driver_info=driver_info)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)
        patch = patcher.create(node).get_cleanup_patch(instance, None,
                                                       self.flavor)
        self.assertEqual([], patch)
