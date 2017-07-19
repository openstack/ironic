# Copyright (c) 2015 Intel Corporation
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

# This is the version 1 API
BASE_VERSION = 1

# Here goes a short log of changes in every version.
# Refer to doc/source/dev/webapi-version-history.rst for a detailed explanation
# of what each version contains.
#
# v1.0: corresponds to Juno API, not supported since Kilo
# v1.1: API at the point in time when versioning support was added,
# covers the following commits from Kilo cycle:
#   827db7fe: Add Node.maintenance_reason
#   68eed82b: Add API endpoint to set/unset the node maintenance mode
#   bc973889: Add sync and async support for passthru methods
#   e03f443b: Vendor endpoints to support different HTTP methods
#   e69e5309: Make vendor methods discoverable via the Ironic API
#   edf532db: Add logic to store the config drive passed by Nova
# v1.2: Renamed NOSTATE ("None") to AVAILABLE ("available")
# v1.3: Add node.driver_internal_info
# v1.4: Add MANAGEABLE state
# v1.5: Add logical node names
# v1.6: Add INSPECT* states
# v1.7: Add node.clean_step
# v1.8: Add ability to return a subset of resource fields
# v1.9: Add ability to filter nodes by provision state
# v1.10: Logical node names support RFC 3986 unreserved characters
# v1.11: Nodes appear in ENROLL state by default
# v1.12: Add support for RAID
# v1.13: Add 'abort' verb to CLEANWAIT
# v1.14: Make the following endpoints discoverable via API:
#        1. '/v1/nodes/<uuid>/states'
#        2. '/v1/drivers/<driver-name>/properties'
# v1.15: Add ability to do manual cleaning of nodes
# v1.16: Add ability to filter nodes by driver.
# v1.17: Add 'adopt' verb for ADOPTING active nodes.
# v1.18: Add port.internal_info.
# v1.19: Add port.local_link_connection and port.pxe_enabled.
# v1.20: Add node.network_interface
# v1.21: Add node.resource_class
# v1.22: Ramdisk lookup and heartbeat endpoints.
# v1.23: Add portgroup support.
# v1.24: Add subcontrollers: node.portgroup, portgroup.ports.
#        Add port.portgroup_uuid field.
# v1.25: Add possibility to unset chassis_uuid from node.
# v1.26: Add portgroup.mode and portgroup.properties.
# v1.27: Add soft reboot, soft power off and timeout.
# v1.28: Add vifs subcontroller to node
# v1.29: Add inject nmi.
# v1.30: Add dynamic driver interactions.
# v1.31: Add dynamic interfaces fields to node.
# v1.32: Add volume support.
# v1.33: Add node storage interface
# v1.34: Add physical network field to port.

MINOR_0_JUNO = 0
MINOR_1_INITIAL_VERSION = 1
MINOR_2_AVAILABLE_STATE = 2
MINOR_3_DRIVER_INTERNAL_INFO = 3
MINOR_4_MANAGEABLE_STATE = 4
MINOR_5_NODE_NAME = 5
MINOR_6_INSPECT_STATE = 6
MINOR_7_NODE_CLEAN = 7
MINOR_8_FETCHING_SUBSET_OF_FIELDS = 8
MINOR_9_PROVISION_STATE_FILTER = 9
MINOR_10_UNRESTRICTED_NODE_NAME = 10
MINOR_11_ENROLL_STATE = 11
MINOR_12_RAID_CONFIG = 12
MINOR_13_ABORT_VERB = 13
MINOR_14_LINKS_NODESTATES_DRIVERPROPERTIES = 14
MINOR_15_MANUAL_CLEAN = 15
MINOR_16_DRIVER_FILTER = 16
MINOR_17_ADOPT_VERB = 17
MINOR_18_PORT_INTERNAL_INFO = 18
MINOR_19_PORT_ADVANCED_NET_FIELDS = 19
MINOR_20_NETWORK_INTERFACE = 20
MINOR_21_RESOURCE_CLASS = 21
MINOR_22_LOOKUP_HEARTBEAT = 22
MINOR_23_PORTGROUPS = 23
MINOR_24_PORTGROUPS_SUBCONTROLLERS = 24
MINOR_25_UNSET_CHASSIS_UUID = 25
MINOR_26_PORTGROUP_MODE_PROPERTIES = 26
MINOR_27_SOFT_POWER_OFF = 27
MINOR_28_VIFS_SUBCONTROLLER = 28
MINOR_29_INJECT_NMI = 29
MINOR_30_DYNAMIC_DRIVERS = 30
MINOR_31_DYNAMIC_INTERFACES = 31
MINOR_32_VOLUME = 32
MINOR_33_STORAGE_INTERFACE = 33
MINOR_34_PORT_PHYSICAL_NETWORK = 34

# When adding another version, update MINOR_MAX_VERSION and also update
# doc/source/dev/webapi-version-history.rst with a detailed explanation of
# what the version has changed.
MINOR_MAX_VERSION = MINOR_34_PORT_PHYSICAL_NETWORK

# String representations of the minor and maximum versions
MIN_VERSION_STRING = '{}.{}'.format(BASE_VERSION, MINOR_1_INITIAL_VERSION)
MAX_VERSION_STRING = '{}.{}'.format(BASE_VERSION, MINOR_MAX_VERSION)
