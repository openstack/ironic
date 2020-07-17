# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

import json

from ironic.common import exception
from ironic.common import raid
from ironic.drivers import base as drivers_base
from ironic.tests import base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils
from ironic.tests.unit import raid_constants


class ValidateRaidConfigurationTestCase(base.TestCase):

    def setUp(self):
        with open(drivers_base.RAID_CONFIG_SCHEMA, 'r') as raid_schema_fobj:
            self.schema = json.load(raid_schema_fobj)
        super(ValidateRaidConfigurationTestCase, self).setUp()

    def test_validate_configuration_okay(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_OKAY)
        raid.validate_configuration(
            raid_config, raid_config_schema=self.schema)

    def test_validate_configuration_okay_software(self):
        raid_config = json.loads(raid_constants.RAID_SW_CONFIG_OKAY)
        raid.validate_configuration(
            raid_config, raid_config_schema=self.schema)

    def test_validate_configuration_no_logical_disk(self):
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          {},
                          raid_config_schema=self.schema)

    def test_validate_configuration_zero_logical_disks(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_NO_LOGICAL_DISKS)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_no_raid_level(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_NO_RAID_LEVEL)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_invalid_raid_level(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_INVALID_RAID_LEVEL)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_no_size_gb(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_NO_SIZE_GB)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_zero_size_gb(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_ZERO_SIZE_GB)

        raid.validate_configuration(raid_config,
                                    raid_config_schema=self.schema)

    def test_validate_configuration_max_size_gb(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_MAX_SIZE_GB)
        raid.validate_configuration(raid_config,
                                    raid_config_schema=self.schema)

    def test_validate_configuration_invalid_size_gb(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_INVALID_SIZE_GB)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_invalid_is_root_volume(self):
        raid_config_str = raid_constants.RAID_CONFIG_INVALID_IS_ROOT_VOL
        raid_config = json.loads(raid_config_str)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_invalid_multiple_is_root_volume(self):
        raid_config_str = raid_constants.RAID_CONFIG_MULTIPLE_IS_ROOT_VOL
        raid_config = json.loads(raid_config_str)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_invalid_share_physical_disks(self):
        raid_config_str = raid_constants.RAID_CONFIG_INVALID_SHARE_PHY_DISKS
        raid_config = json.loads(raid_config_str)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_invalid_disk_type(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_INVALID_DISK_TYPE)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_invalid_int_type(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_INVALID_INT_TYPE)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_invalid_number_of_phy_disks(self):
        raid_config_str = raid_constants.RAID_CONFIG_INVALID_NUM_PHY_DISKS
        raid_config = json.loads(raid_config_str)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_invalid_physical_disks(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_INVALID_PHY_DISKS)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_too_few_physical_disks(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_TOO_FEW_PHY_DISKS)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_additional_property(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_ADDITIONAL_PROP)
        self.assertRaises(exception.InvalidParameterValue,
                          raid.validate_configuration,
                          raid_config,
                          raid_config_schema=self.schema)

    def test_validate_configuration_with_jbod_volume(self):
        raid_config = json.loads(raid_constants.RAID_CONFIG_JBOD_VOLUME)
        raid.validate_configuration(raid_config,
                                    raid_config_schema=self.schema)

    def test_validate_configuration_custom_schema(self):
        raid_config = json.loads(raid_constants.CUSTOM_SCHEMA_RAID_CONFIG)
        schema = json.loads(raid_constants.CUSTOM_RAID_SCHEMA)
        raid.validate_configuration(raid_config,
                                    raid_config_schema=schema)


class RaidPublicMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RaidPublicMethodsTestCase, self).setUp()
        self.target_raid_config = {
            "logical_disks": [
                {'size_gb': 200, 'raid_level': 0, 'is_root_volume': True},
                {'size_gb': 200, 'raid_level': 5}
            ]}
        n = {
            'boot_interface': 'pxe',
            'deploy_interface': 'direct',
            'raid_interface': 'agent',
            'target_raid_config': self.target_raid_config,
        }
        self.node = obj_utils.create_test_node(self.context, **n)

    def test_get_logical_disk_properties(self):
        with open(drivers_base.RAID_CONFIG_SCHEMA, 'r') as raid_schema_fobj:
            schema = json.load(raid_schema_fobj)
        logical_disk_properties = raid.get_logical_disk_properties(schema)
        self.assertIn('raid_level', logical_disk_properties)
        self.assertIn('size_gb', logical_disk_properties)
        self.assertIn('volume_name', logical_disk_properties)
        self.assertIn('is_root_volume', logical_disk_properties)
        self.assertIn('share_physical_disks', logical_disk_properties)
        self.assertIn('disk_type', logical_disk_properties)
        self.assertIn('interface_type', logical_disk_properties)
        self.assertIn('number_of_physical_disks', logical_disk_properties)
        self.assertIn('controller', logical_disk_properties)
        self.assertIn('physical_disks', logical_disk_properties)

    def test_get_logical_disk_properties_custom_schema(self):
        raid_schema = json.loads(raid_constants.CUSTOM_RAID_SCHEMA)
        logical_disk_properties = raid.get_logical_disk_properties(
            raid_config_schema=raid_schema)
        self.assertIn('raid_level', logical_disk_properties)
        self.assertIn('size_gb', logical_disk_properties)
        self.assertIn('foo', logical_disk_properties)

    def _test_update_raid_info(self, current_config,
                               capabilities=None,
                               skip_local_gb=False):
        node = self.node
        if capabilities:
            properties = node.properties
            properties['capabilities'] = capabilities
            del properties['local_gb']
            node.properties = properties
        target_raid_config = json.loads(raid_constants.RAID_CONFIG_OKAY)
        node.target_raid_config = target_raid_config
        node.save()
        raid.update_raid_info(node, current_config)
        properties = node.properties
        current = node.raid_config
        target = node.target_raid_config
        self.assertIsNotNone(current['last_updated'])
        self.assertIsInstance(current['logical_disks'][0], dict)
        if current_config['logical_disks'][0].get('is_root_volume'):
            self.assertEqual({'wwn': '600508B100'},
                             properties['root_device'])
            if skip_local_gb:
                self.assertNotIn('local_gb', properties)
            else:
                self.assertEqual(100, properties['local_gb'])
            self.assertIn('raid_level:1', properties['capabilities'])
            if capabilities:
                self.assertIn(capabilities, properties['capabilities'])
        else:
            self.assertNotIn('local_gb', properties)
            self.assertNotIn('root_device', properties)
            if capabilities:
                self.assertNotIn('raid_level:1', properties['capabilities'])

        # Verify node.target_raid_config is preserved.
        self.assertEqual(target_raid_config, target)

    def test_update_raid_info_okay(self):
        current_config = json.loads(raid_constants.CURRENT_RAID_CONFIG)
        self._test_update_raid_info(current_config,
                                    capabilities='boot_mode:bios')

    def test_update_raid_info_okay_no_root_volumes(self):
        current_config = json.loads(raid_constants.CURRENT_RAID_CONFIG)
        del current_config['logical_disks'][0]['is_root_volume']
        del current_config['logical_disks'][0]['root_device_hint']
        self._test_update_raid_info(current_config,
                                    capabilities='boot_mode:bios')

    def test_update_raid_info_okay_current_capabilities_empty(self):
        current_config = json.loads(raid_constants.CURRENT_RAID_CONFIG)
        self._test_update_raid_info(current_config,
                                    capabilities=None)

    def test_update_raid_info_multiple_root_volumes(self):
        current_config = json.loads(raid_constants.RAID_CONFIG_MULTIPLE_ROOT)
        self.assertRaises(exception.InvalidParameterValue,
                          self._test_update_raid_info,
                          current_config)

    def test_update_raid_info_skip_MAX(self):
        current_config = json.loads(raid_constants.CURRENT_RAID_CONFIG)
        current_config['logical_disks'][0]['size_gb'] = 'MAX'
        self._test_update_raid_info(current_config,
                                    capabilities='boot_mode:bios',
                                    skip_local_gb=True)

    def test_filter_target_raid_config(self):
        result = raid.filter_target_raid_config(self.node)
        self.assertEqual(self.node.target_raid_config, result)

    def test_filter_target_raid_config_skip_root(self):
        result = raid.filter_target_raid_config(
            self.node, create_root_volume=False)
        exp_target_raid_config = {
            "logical_disks": [{'size_gb': 200, 'raid_level': 5}]}
        self.assertEqual(exp_target_raid_config, result)

    def test_filter_target_raid_config_skip_nonroot(self):
        result = raid.filter_target_raid_config(
            self.node, create_nonroot_volumes=False)
        exp_target_raid_config = {
            "logical_disks": [{'size_gb': 200,
                               'raid_level': 0,
                               'is_root_volume': True}]}
        self.assertEqual(exp_target_raid_config, result)

    def test_filter_target_raid_config_no_target_raid_config_after_skipping(
            self):
        self.assertRaises(exception.MissingParameterValue,
                          raid.filter_target_raid_config,
                          self.node, create_root_volume=False,
                          create_nonroot_volumes=False)

    def test_filter_target_raid_config_empty_target_raid_config(self):
        self.node.target_raid_config = {}
        self.node.save()
        self.assertRaises(exception.MissingParameterValue,
                          raid.filter_target_raid_config,
                          self.node)
