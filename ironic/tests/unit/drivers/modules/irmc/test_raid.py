# Copyright 2018 FUJITSU LIMITED
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

"""
Test class for IRMC RAID configuration
"""

from unittest import mock

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.irmc import raid
from ironic.tests.unit.drivers.modules.irmc import test_common


class IRMCRaidConfigurationInternalMethodsTestCase(test_common.BaseIRMCTest):

    def setUp(self):
        super(IRMCRaidConfigurationInternalMethodsTestCase, self).setUp()
        self.raid_adapter_profile = {
            "Server": {
                "HWConfigurationIrmc": {
                    "Adapters": {
                        "RAIDAdapter": [
                            {
                                "@AdapterId": "RAIDAdapter0",
                                "@ConfigurationType": "Addressing",
                                "Arrays": None,
                                "LogicalDrives": None,
                                "PhysicalDisks": {
                                    "PhysicalDisk": [
                                        {
                                            "@Number": "0",
                                            "@Action": "None",
                                            "Slot": 0,
                                        },
                                        {
                                            "@Number": "1",
                                            "@Action": "None",
                                            "Slot": 1
                                        },
                                        {
                                            "@Number": "2",
                                            "@Action": "None",
                                            "Slot": 2
                                        },
                                        {
                                            "@Number": "3",
                                            "@Action": "None",
                                            "Slot": 3
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                }
            }
        }

        self.valid_disk_slots = {
            "PhysicalDisk": [
                {
                    "@Number": "0",
                    "Slot": 0,
                    "Size": {
                        "@Unit": "GB",
                        "#text": 1000
                    }
                },
                {
                    "@Number": "1",
                    "Slot": 1,
                    "Size": {
                        "@Unit": "GB",
                        "#text": 1000
                    }
                },
                {
                    "@Number": "2",
                    "Slot": 2,
                    "Size": {
                        "@Unit": "GB",
                        "#text": 1000
                    }
                },
                {
                    "@Number": "3",
                    "Slot": 3,
                    "Size": {
                        "@Unit": "GB",
                        "#text": 1000
                    }
                },
                {
                    "@Number": "4",
                    "Slot": 4,
                    "Size": {
                        "@Unit": "GB",
                        "#text": 1000
                    }
                },
                {
                    "@Number": "5",
                    "Slot": 5,
                    "Size": {
                        "@Unit": "GB",
                        "#text": 1000
                    }
                },
                {
                    "@Number": "6",
                    "Slot": 6,
                    "Size": {
                        "@Unit": "GB",
                        "#text": 1000
                    }
                },
                {
                    "@Number": "7",
                    "Slot": 7,
                    "Size": {
                        "@Unit": "GB",
                        "#text": 1000
                    }
                }
            ]
        }

    @mock.patch('ironic.drivers.modules.irmc.raid._get_physical_disk',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_raid_adapter',
                autospec=True)
    def test___fail_validation_with_none_raid_adapter_profile(
            self, get_raid_adapter_mock, get_physical_disk_mock):
        get_raid_adapter_mock.return_value = None
        target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": "50",
                    "raid_level": "0"
                }
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              raid._validate_physical_disks,
                              task.node, target_raid_config['logical_disks'])

    @mock.patch('ironic.drivers.modules.irmc.raid._get_physical_disk',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_raid_adapter',
                autospec=True)
    def test___fail_validation_without_raid_level(
            self, get_raid_adapter_mock, get_physical_disk_mock):
        get_raid_adapter_mock.return_value = self.raid_adapter_profile
        target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": "50"
                }
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              raid._validate_physical_disks,
                              task.node, target_raid_config['logical_disks'])

    @mock.patch('ironic.drivers.modules.irmc.raid._get_physical_disk',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_raid_adapter',
                autospec=True)
    def test___fail_validation_with_raid_level_is_none(self,
                                                       get_raid_adapter_mock,
                                                       get_physical_disk_mock):
        get_raid_adapter_mock.return_value = self.raid_adapter_profile
        target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": "50",
                    "raid_level": ""
                }
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              raid._validate_physical_disks,
                              task.node, target_raid_config['logical_disks'])

    @mock.patch('ironic.drivers.modules.irmc.raid._get_physical_disk',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_raid_adapter',
                autospec=True)
    def test__fail_validation_without_physical_disks(
            self, get_raid_adapter_mock, get_physical_disk_mock):
        get_raid_adapter_mock.return_value = {
            "Server": {
                "HWConfigurationIrmc": {
                    "Adapters": {
                        "RAIDAdapter": [
                            {
                                "@AdapterId": "RAIDAdapter0",
                                "@ConfigurationType": "Addressing",
                                "Arrays": None,
                                "LogicalDrives": None,
                                "PhysicalDisks": None
                            }
                        ]
                    }
                }
            }
        }

        target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": "50",
                    "raid_level": "1"
                }
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              raid._validate_physical_disks,
                              task.node, target_raid_config['logical_disks'])

    @mock.patch('ironic.drivers.modules.irmc.raid._get_physical_disk',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_raid_adapter',
                autospec=True)
    def test___fail_validation_with_raid_level_outside_list(
            self, get_raid_adapter_mock, get_physical_disk_mock):
        get_raid_adapter_mock.return_value = self.raid_adapter_profile
        target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": "50",
                    "raid_level": "2"
                }
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              raid._validate_physical_disks,
                              task.node, target_raid_config['logical_disks'])

    @mock.patch(
        'ironic.drivers.modules.irmc.raid._validate_logical_drive_capacity',
        autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_physical_disk',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_raid_adapter',
                autospec=True)
    def test__fail_validation_with_not_enough_valid_disks(
            self, get_raid_adapter_mock, get_physical_disk_mock,
            capacity_mock):
        get_raid_adapter_mock.return_value = self.raid_adapter_profile
        target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": "50",
                    "raid_level": "5"
                },
                {
                    "size_gb": "50",
                    "raid_level": "1"
                },
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              raid._validate_physical_disks,
                              task.node, target_raid_config['logical_disks'])

    @mock.patch('ironic.drivers.modules.irmc.raid._get_physical_disk',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_raid_adapter',
                autospec=True)
    def test__fail_validation_with_physical_disk_insufficient(
            self, get_raid_adapter_mock, get_physical_disk_mock):
        get_raid_adapter_mock.return_value = self.raid_adapter_profile
        target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": "50",
                    "raid_level": "1",
                    "physical_disks": [
                        "0",
                        "1",
                        "2"
                    ]
                },
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              raid._validate_physical_disks,
                              task.node, target_raid_config['logical_disks'])

    @mock.patch('ironic.drivers.modules.irmc.raid._get_physical_disk',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_raid_adapter',
                autospec=True)
    def test__fail_validation_with_physical_disk_not_enough_disks(
            self, get_raid_adapter_mock, get_physical_disk_mock):
        get_raid_adapter_mock.return_value = self.raid_adapter_profile
        target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": "50",
                    "raid_level": "5",
                    "physical_disks": [
                        "0",
                        "1"
                    ]
                },
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              raid._validate_physical_disks,
                              task.node, target_raid_config['logical_disks'])

    @mock.patch('ironic.drivers.modules.irmc.raid._get_physical_disk',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_raid_adapter',
                autospec=True)
    def test__fail_validation_with_physical_disk_incorrect_valid_disks(
            self, get_raid_adapter_mock, get_physical_disk_mock):
        get_raid_adapter_mock.return_value = self.raid_adapter_profile
        target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": "50",
                    "raid_level": "10",
                    "physical_disks": [
                        "0",
                        "1",
                        "2",
                        "3",
                        "4"
                    ]
                },
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              raid._validate_physical_disks,
                              task.node, target_raid_config['logical_disks'])

    @mock.patch('ironic.drivers.modules.irmc.raid._get_physical_disk',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_raid_adapter',
                autospec=True)
    def test__fail_validation_with_physical_disk_outside_valid_disks_1(
            self, get_raid_adapter_mock, get_physical_disk_mock):
        get_raid_adapter_mock.return_value = self.raid_adapter_profile
        target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": "50",
                    "raid_level": "1",
                    "physical_disks": [
                        "4",
                        "5"
                    ]
                },
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              raid._validate_physical_disks,
                              task.node, target_raid_config['logical_disks'])

    @mock.patch(
        'ironic.drivers.modules.irmc.raid._validate_logical_drive_capacity',
        autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_physical_disk',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_raid_adapter',
                autospec=True)
    def test__fail_validation_with_physical_disk_outside_valid_slots_2(
            self, get_raid_adapter_mock, get_physical_disk_mock,
            capacity_mock):
        get_raid_adapter_mock.return_value = self.raid_adapter_profile
        target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": "50",
                    "raid_level": "5",
                    "physical_disks": [
                        "0",
                        "1",
                        "2"
                    ]
                },
                {
                    "size_gb": "50",
                    "raid_level": "0",
                    "physical_disks": [
                        "4"
                    ]
                },
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              raid._validate_physical_disks,
                              task.node, target_raid_config['logical_disks'])

    @mock.patch(
        'ironic.drivers.modules.irmc.raid._validate_logical_drive_capacity',
        autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_physical_disk',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._get_raid_adapter',
                autospec=True)
    def test__fail_validation_with_duplicated_physical_disks(
            self, get_raid_adapter_mock, get_physical_disk_mock,
            capacity_mock):
        get_raid_adapter_mock.return_value = self.raid_adapter_profile
        target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": "50",
                    "raid_level": "1",
                    "physical_disks": [
                        "0",
                        "1"
                    ]
                },
                {
                    "size_gb": "50",
                    "raid_level": "1",
                    "physical_disks": [
                        "1",
                        "2"
                    ]
                },
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              raid._validate_physical_disks,
                              task.node, target_raid_config['logical_disks'])

    @mock.patch('ironic.drivers.modules.irmc.raid._get_raid_adapter',
                autospec=True)
    def test__fail_validation_with_difference_physical_disks_type(
            self, get_raid_adapter_mock):
        get_raid_adapter_mock.return_value = {
            "Server": {
                "HWConfigurationIrmc": {
                    "Adapters": {
                        "RAIDAdapter": [
                            {
                                "@AdapterId": "RAIDAdapter0",
                                "@ConfigurationType": "Addressing",
                                "Arrays": None,
                                "LogicalDrives": None,
                                "PhysicalDisks": {
                                    "PhysicalDisk": [
                                        {
                                            "@Number": "0",
                                            "Slot": 0,
                                            "Type": "HDD",
                                        },
                                        {
                                            "@Number": "1",
                                            "Slot": 1,
                                            "Type": "SSD",
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                }
            }
        }
        target_raid_config = {
            "logical_disks": [
                {
                    "size_gb": "50",
                    "raid_level": "1",
                    "physical_disks": [
                        "0",
                        "1"
                    ]
                }
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              raid._validate_physical_disks,
                              task.node, target_raid_config['logical_disks'])

    def test__fail_validate_capacity_raid_0(self):
        disk = {
            "size_gb": 3000,
            "raid_level": "0"
        }
        self.assertRaises(exception.InvalidParameterValue,
                          raid._validate_logical_drive_capacity,
                          disk, self.valid_disk_slots)

    def test__fail_validate_capacity_raid_1(self):
        disk = {
            "size_gb": 3000,
            "raid_level": "1"
        }
        self.assertRaises(exception.InvalidParameterValue,
                          raid._validate_logical_drive_capacity,
                          disk, self.valid_disk_slots)

    def test__fail_validate_capacity_raid_5(self):
        disk = {
            "size_gb": 3000,
            "raid_level": "5"
        }
        self.assertRaises(exception.InvalidParameterValue,
                          raid._validate_logical_drive_capacity,
                          disk, self.valid_disk_slots)

    def test__fail_validate_capacity_raid_6(self):
        disk = {
            "size_gb": 3000,
            "raid_level": "6"
        }
        self.assertRaises(exception.InvalidParameterValue,
                          raid._validate_logical_drive_capacity,
                          disk, self.valid_disk_slots)

    def test__fail_validate_capacity_raid_10(self):
        disk = {
            "size_gb": 3000,
            "raid_level": "10"
        }
        self.assertRaises(exception.InvalidParameterValue,
                          raid._validate_logical_drive_capacity,
                          disk, self.valid_disk_slots)

    def test__fail_validate_capacity_raid_50(self):
        disk = {
            "size_gb": 5000,
            "raid_level": "50"
        }
        self.assertRaises(exception.InvalidParameterValue,
                          raid._validate_logical_drive_capacity,
                          disk, self.valid_disk_slots)

    def test__fail_validate_capacity_with_physical_disk(self):
        disk = {
            "size_gb": 4000,
            "raid_level": "5",
            "physical_disks": [
                "0",
                "1",
                "3",
                "4"
            ]
        }
        self.assertRaises(exception.InvalidParameterValue,
                          raid._validate_logical_drive_capacity,
                          disk, self.valid_disk_slots)

    @mock.patch('ironic.common.raid.update_raid_info', autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid.client.elcm.'
                'get_raid_adapter', autospec=True)
    def test__commit_raid_config_with_logical_drives(
            self, get_raid_adapter_mock, update_raid_info_mock):
        get_raid_adapter_mock.return_value = {
            "Server": {
                "HWConfigurationIrmc": {
                    "Adapters": {
                        "RAIDAdapter": [
                            {
                                "@AdapterId": "RAIDAdapter0",
                                "@ConfigurationType": "Addressing",
                                "Arrays": {
                                    "Array": [
                                        {
                                            "@Number": 0,
                                            "@ConfigurationType": "Addressing",
                                            "PhysicalDiskRefs": {
                                                "PhysicalDiskRef": [
                                                    {
                                                        "@Number": "0"
                                                    },
                                                    {
                                                        "@Number": "1"
                                                    }
                                                ]
                                            }
                                        }
                                    ]
                                },
                                "LogicalDrives": {
                                    "LogicalDrive": [
                                        {
                                            "@Number": 0,
                                            "@Action": "None",
                                            "RaidLevel": "1",
                                            "Name": "LogicalDrive_0",
                                            "Size": {
                                                "@Unit": "GB",
                                                "#text": 465
                                            },
                                            "ArrayRefs": {
                                                "ArrayRef": [
                                                    {
                                                        "@Number": 0
                                                    }
                                                ]
                                            }
                                        }
                                    ]
                                },
                                "PhysicalDisks": {
                                    "PhysicalDisk": [
                                        {
                                            "@Number": "0",
                                            "@Action": "None",
                                            "Slot": 0,
                                            "PDStatus": "Operational"
                                        },
                                        {
                                            "@Number": "1",
                                            "@Action": "None",
                                            "Slot": 1,
                                            "PDStatus": "Operational"
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                }
            }
        }

        expected_raid_config = [
            {'controller': 'RAIDAdapter0'},
            {'irmc_raid_info': {' size': {'#text': 465, '@Unit': 'GB'},
                                'logical_drive_number': 0,
                                'name': 'LogicalDrive_0',
                                'raid_level': '1'}},
            {'physical_drives': {'physical_drive': {'@Action': 'None',
                                                    '@Number': '0',
                                                    'PDStatus': 'Operational',
                                                    'Slot': 0}}},
            {'physical_drives': {'physical_drive': {'@Action': 'None',
                                                    '@Number': '1',
                                                    'PDStatus': 'Operational',
                                                    'Slot': 1}}}]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            raid._commit_raid_config(task)
            get_raid_adapter_mock.assert_called_once_with(
                task.node.driver_info)
            update_raid_info_mock.assert_called_once_with(
                task.node, task.node.raid_config)
            self.assertEqual(task.node.raid_config['logical_disks'],
                             expected_raid_config)


class IRMCRaidConfigurationTestCase(test_common.BaseIRMCTest):

    def setUp(self):
        super(IRMCRaidConfigurationTestCase, self).setUp()
        self.config(enabled_raid_interfaces=['irmc'])
        self.raid_adapter_profile = {
            "Server": {
                "HWConfigurationIrmc": {
                    "Adapters": {
                        "RAIDAdapter": [
                            {
                                "@AdapterId": "RAIDAdapter0",
                                "@ConfigurationType": "Addressing",
                                "Arrays": None,
                                "LogicalDrives": None,
                                "PhysicalDisks": {
                                    "PhysicalDisk": [
                                        {
                                            "@Number": "0",
                                            "@Action": "None",
                                            "Slot": 0,
                                        },
                                        {
                                            "@Number": "1",
                                            "@Action": "None",
                                            "Slot": 1
                                        },
                                        {
                                            "@Number": "2",
                                            "@Action": "None",
                                            "Slot": 2
                                        },
                                        {
                                            "@Number": "3",
                                            "@Action": "None",
                                            "Slot": 3
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                }
            }
        }

    def test_fail_create_raid_without_target_raid_config(self):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            task.node.target_raid_config = {}
            raid_configuration = raid.IRMCRAID()

            self.assertRaises(exception.MissingParameterValue,
                              raid_configuration.create_configuration, task)

    @mock.patch('ironic.drivers.modules.irmc.raid._validate_physical_disks',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._create_raid_adapter',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._commit_raid_config',
                autospec=True)
    def test_create_raid_with_raid_1_and_0(self, commit_mock,
                                           create_raid_mock, validation_mock):
        expected_input = {
            "logical_disks": [
                {
                    "raid_level": "10"
                },
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.target_raid_config = {
                "logical_disks": [
                    {
                        "raid_level": "1+0"
                    },
                ]
            }

            task.driver.raid.create_configuration(task)
            create_raid_mock.assert_called_once_with(task.node)
            validation_mock.assert_called_once_with(
                task.node, expected_input['logical_disks'])
            commit_mock.assert_called_once_with(task)

    @mock.patch('ironic.drivers.modules.irmc.raid._validate_physical_disks',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._create_raid_adapter',
                autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.raid._commit_raid_config',
                autospec=True)
    def test_create_raid_with_raid_5_and_0(self, commit_mock,
                                           create_raid_mock, validation_mock):
        expected_input = {
            "logical_disks": [
                {
                    "raid_level": "50"
                },
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.target_raid_config = {
                "logical_disks": [
                    {
                        "raid_level": "5+0"
                    },
                ]
            }

            task.driver.raid.create_configuration(task)
            create_raid_mock.assert_called_once_with(task.node)
            validation_mock.assert_called_once_with(
                task.node, expected_input['logical_disks'])
            commit_mock.assert_called_once_with(task)

    @mock.patch('ironic.drivers.modules.irmc.raid._delete_raid_adapter',
                autospec=True)
    def test_delete_raid_configuration(self, delete_raid_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.raid.delete_configuration(task)
            delete_raid_mock.assert_called_once_with(task.node)

    @mock.patch('ironic.drivers.modules.irmc.raid._delete_raid_adapter',
                autospec=True)
    def test_delete_raid_configuration_return_cleared_raid_config(
            self, delete_raid_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            expected_raid_config = {}

            task.driver.raid.delete_configuration(task)
            self.assertEqual(expected_raid_config, task.node.raid_config)
            delete_raid_mock.assert_called_once_with(task.node)
