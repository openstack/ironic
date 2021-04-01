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

from oslo_config import cfg

from ironic.common import release_mappings

CONF = cfg.CONF

# This is the version 1 API
BASE_VERSION = 1

# Here goes a short log of changes in every version.
# Refer to doc/source/contributor/webapi-version-history.rst for a detailed
# explanation of what each version contains.
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
# v1.35: Add ability to provide configdrive when rebuilding node.
# v1.36: Add Ironic Python Agent version support.
# v1.37: Add node traits.
# v1.38: Add rescue and unrescue provision states
# v1.39: Add inspect wait provision state.
# v1.40: Add bios.properties.
#        Add bios_interface to the node object.
# v1.41: Add inspection abort support.
# v1.42: Expose fault field to node.
# v1.43: Add detail=True flag to all API endpoints
# v1.44: Add node deploy_step field
# v1.45: reset_interfaces parameter to node's PATCH
# v1.46: Add conductor_group to the node object.
# v1.47: Add automated_clean to the node object.
# v1.48: Add protected to the node object.
# v1.49: Add conductor to the node object and /v1/conductors.
# v1.50: Add owner to the node object.
# v1.51: Add description to the node object.
# v1.52: Add allocation API.
# v1.53: Add support for Smart NIC port
# v1.54: Add events support.
# v1.55: Add deploy templates API.
# v1.56: Add support for building configdrives.
# v1.57: Add support for updating an exisiting allocation.
# v1.58: Add support for backfilling allocations.
# v1.59: Add support vendor data in configdrives.
# v1.60: Add owner to the allocation object.
# v1.61: Add retired and retired_reason to the node object.
# v1.62: Add agent_token support for agent communication.
# v1.63: Add support for indicators
# v1.64: Add network_type to port.local_link_connection
# v1.65: Add lessee to the node object.
# v1.66: Add support for node network_data field.
# v1.67: Add support for port_uuid/portgroup_uuid in node vif_attach
# v1.68: Add agent_verify_ca to heartbeat.
# v1.69: Add deploy_steps to provisioning
# v1.70: Add disable_ramdisk to manual cleaning.
# v1.71: Add signifier for Scope based roles.
# v1.72: Add agent_status and agent_status_message to /v1/heartbeat

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
MINOR_35_REBUILD_CONFIG_DRIVE = 35
MINOR_36_AGENT_VERSION_HEARTBEAT = 36
MINOR_37_NODE_TRAITS = 37
MINOR_38_RESCUE_INTERFACE = 38
MINOR_39_INSPECT_WAIT = 39
MINOR_40_BIOS_INTERFACE = 40
MINOR_41_INSPECTION_ABORT = 41
MINOR_42_FAULT = 42
MINOR_43_ENABLE_DETAIL_QUERY = 43
MINOR_44_NODE_DEPLOY_STEP = 44
MINOR_45_RESET_INTERFACES = 45
MINOR_46_NODE_CONDUCTOR_GROUP = 46
MINOR_47_NODE_AUTOMATED_CLEAN = 47
MINOR_48_NODE_PROTECTED = 48
MINOR_49_CONDUCTORS = 49
MINOR_50_NODE_OWNER = 50
MINOR_51_NODE_DESCRIPTION = 51
MINOR_52_ALLOCATION = 52
MINOR_53_PORT_SMARTNIC = 53
MINOR_54_EVENTS = 54
MINOR_55_DEPLOY_TEMPLATES = 55
MINOR_56_BUILD_CONFIGDRIVE = 56
MINOR_57_ALLOCATION_UPDATE = 57
MINOR_58_ALLOCATION_BACKFILL = 58
MINOR_59_CONFIGDRIVE_VENDOR_DATA = 59
MINOR_60_ALLOCATION_OWNER = 60
MINOR_61_NODE_RETIRED = 61
MINOR_62_AGENT_TOKEN = 62
MINOR_63_INDICATORS = 63
MINOR_64_LOCAL_LINK_CONNECTION_NETWORK_TYPE = 64
MINOR_65_NODE_LESSEE = 65
MINOR_66_NODE_NETWORK_DATA = 66
MINOR_67_NODE_VIF_ATTACH_PORT = 67
MINOR_68_HEARTBEAT_VERIFY_CA = 68
MINOR_69_DEPLOY_STEPS = 69
MINOR_70_CLEAN_DISABLE_RAMDISK = 70
MINOR_71_RBAC_SCOPES = 71
MINOR_72_HEARTBEAT_STATUS = 72

# When adding another version, update:
# - MINOR_MAX_VERSION
# - doc/source/contributor/webapi-version-history.rst with a detailed
#   explanation of what changed in the new version
# - common/release_mappings.py, RELEASE_MAPPING['master']['api']

MINOR_MAX_VERSION = MINOR_72_HEARTBEAT_STATUS

# String representations of the minor and maximum versions
_MIN_VERSION_STRING = '{}.{}'.format(BASE_VERSION, MINOR_1_INITIAL_VERSION)
_MAX_VERSION_STRING = '{}.{}'.format(BASE_VERSION, MINOR_MAX_VERSION)


def min_version_string():
    """Returns the minimum supported API version (as a string)"""
    return _MIN_VERSION_STRING


def max_version_string():
    """Returns the maximum supported API version (as a string).

    If the service is pinned, the maximum API version is the pinned
    version. Otherwise, it is the maximum supported API version.
    """
    release_ver = release_mappings.RELEASE_MAPPING.get(
        CONF.pin_release_version)
    if release_ver:
        return release_ver['api']
    else:
        return _MAX_VERSION_STRING
