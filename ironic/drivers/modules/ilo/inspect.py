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
iLO Inspect Interface
"""
from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.common import utils
from ironic.conductor import utils as conductor_utils
from ironic.drivers import base
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules import inspect_utils

ilo_error = importutils.try_import('proliantutils.exception')

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

CAPABILITIES_KEYS = {'secure_boot', 'rom_firmware_version',
                     'ilo_firmware_version', 'server_model',
                     'pci_gpu_devices', 'sriov_enabled', 'nic_capacity',
                     'has_ssd', 'has_rotational',
                     'rotational_drive_4800_rpm',
                     'rotational_drive_5400_rpm',
                     'rotational_drive_7200_rpm',
                     'rotational_drive_10000_rpm',
                     'rotational_drive_15000_rpm',
                     'logical_raid_level_0', 'logical_raid_level_1',
                     'logical_raid_level_2', 'logical_raid_level_10',
                     'logical_raid_level_5', 'logical_raid_level_6',
                     'logical_raid_level_50', 'logical_raid_level_60',
                     'cpu_vt', 'hardware_supports_raid', 'has_nvme_ssd',
                     'nvdimm_n', 'logical_nvdimm_n', 'persistent_memory',
                     'overall_security_status', 'security_override_switch',
                     'last_firmware_scan_result'}


def _get_essential_properties(node, ilo_object):
    """Inspects the node and get essential scheduling properties

    :param node: node object.
    :param ilo_object: an instance of proliantutils.ilo.IloClient
    :raises: HardwareInspectionFailure if any of the properties values
             are missing.
    :returns: The dictionary containing properties and MAC data.
              The dictionary possible keys are 'properties' and 'macs'.
              The 'properties' should contain keys as in
              IloInspect.ESSENTIAL_PROPERTIES. The 'macs' is a dictionary
              containing key:value pairs of <port_numbers:mac_addresses>

    """
    try:
        # Retrieve the mandatory properties from hardware
        result = ilo_object.get_essential_properties()
    except ilo_error.IloError as e:
        raise exception.HardwareInspectionFailure(error=e)
    _validate(node, result)
    return result


def _validate(node, data):
    """Validate the received value against the supported keys in ironic.

    :param node: node object.
    :param data: the dictionary received by querying server.
    :raises: HardwareInspectionFailure

    """
    if data.get('properties'):
        if isinstance(data['properties'], dict):
            valid_keys = IloInspect.ESSENTIAL_PROPERTIES
            missing_keys = valid_keys - set(data['properties'])
            if missing_keys:
                error = (_(
                    "Server didn't return the key(s): %(key)s") %
                    {'key': ', '.join(missing_keys)})
                raise exception.HardwareInspectionFailure(error=error)
        else:
            error = (_("Essential properties are expected to be in dictionary "
                       "format, received %(properties)s from node "
                       "%(node)s.") % {"properties": data['properties'],
                                       'node': node.uuid})
            raise exception.HardwareInspectionFailure(error=error)
    else:
        error = (_("The node %s didn't return 'properties' as the key with "
                   "inspection.") % node.uuid)
        raise exception.HardwareInspectionFailure(error=error)

    if data.get('macs'):
        if not isinstance(data['macs'], dict):
            error = (_("Node %(node)s didn't return MACs %(macs)s "
                       "in dictionary format.")
                     % {"macs": data['macs'], 'node': node.uuid})
            raise exception.HardwareInspectionFailure(error=error)
    else:
        error = (_("The node %s didn't return 'macs' as the key with "
                   "inspection.") % node.uuid)
        raise exception.HardwareInspectionFailure(error=error)


def _create_supported_capabilities_dict(capabilities):
    """Creates a capabilities dictionary from supported capabilities in ironic.

    :param capabilities: a dictionary of capabilities as returned by the
                         hardware.
    :returns: a dictionary of the capabilities supported by ironic
              and returned by hardware.

    """
    valid_cap = {}

    # Add the capabilities starting with "gpu_" to the supported capabilities
    # keys set as they are runtime generated keys and cannot be hardcoded.
    for k in capabilities:
        if k.startswith("gpu_"):
            valid_cap[k] = capabilities.get(k)

    for key in CAPABILITIES_KEYS.intersection(capabilities):
        valid_cap[key] = capabilities.get(key)
    return valid_cap


def _get_capabilities(node, ilo_object):
    """inspects hardware and gets additional capabilities.

    :param node: Node object.
    :param ilo_object: an instance of ilo drivers.
    :returns: a string of capabilities like
               'key1:value1,key2:value2,key3:value3'
               or None.

    """
    capabilities = None
    try:
        capabilities = ilo_object.get_server_capabilities()
    except ilo_error.IloError:
        LOG.debug("Node %s did not return any additional capabilities.",
                  node.uuid)

    return capabilities


def _get_security_parameters(node, ilo_object):
    """inspect hardware and gets security parameter information.

    :param node: Node object.
    :param ilo_object: an instance of ilo drivers.
    :returns: a dictionary of security parameters.
    """
    security_params = None
    try:
        security_params = ilo_object.get_security_dashboard_values()
    except ilo_error.IloError:
        LOG.debug("Node %s did not return any security parameters.",
                  node.uuid)

    return security_params


class IloInspect(base.InspectInterface):

    def get_properties(self):
        props = ilo_common.REQUIRED_PROPERTIES.copy()
        props.update(ilo_common.SNMP_PROPERTIES)
        props.update(ilo_common.SNMP_OPTIONAL_PROPERTIES)
        return props

    @METRICS.timer('IloInspect.validate')
    def validate(self, task):
        """Check that 'driver_info' contains required ILO credentials.

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required credentials information.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue if required iLO parameters
                 are not valid.
        :raises: MissingParameterValue if a required parameter is missing.
        """
        node = task.node
        ilo_common.parse_driver_info(node)

    @METRICS.timer('IloInspect.inspect_hardware')
    def inspect_hardware(self, task):
        """Inspect hardware to get the hardware properties.

        Inspects hardware to get the essential and additional hardware
        properties. It fails if any of the essential properties
        are not received from the node.  It doesn't fail if node fails
        to return any capabilities as the capabilities differ from hardware
        to hardware mostly.

        :param task: a TaskManager instance.
        :raises: HardwareInspectionFailure if essential properties
                 could not be retrieved successfully.
        :raises: IloOperationError if system fails to get power state.
        :returns: The resulting state of inspection.

        """
        power_turned_on = False
        ilo_object = ilo_common.get_ilo_object(task.node)
        try:
            state = task.driver.power.get_power_state(task)
        except exception.IloOperationError as ilo_exception:
            operation = (_("Inspecting hardware (get_power_state) on %s")
                         % task.node.uuid)
            raise exception.IloOperationError(operation=operation,
                                              error=ilo_exception)
        if state != states.POWER_ON:
            LOG.info("The node %s is not powered on. Powering on the "
                     "node for inspection.", task.node.uuid)
            conductor_utils.node_power_action(task, states.POWER_ON)
            power_turned_on = True

        # get the essential properties and update the node properties
        # with it.

        inspected_properties = {}
        result = _get_essential_properties(task.node, ilo_object)

        # A temporary hook for OOB inspection to not to update 'local_gb'
        # for hardware if the storage is a "Direct Attached Storage" or
        # "Dynamic Smart Array Controllers" and the operator has manually
        # updated the local_gb in node properties prior to node inspection.
        # This will be removed once we have inband inspection support for
        # ilo drivers.
        current_local_gb = task.node.properties.get('local_gb')
        properties = result['properties']
        if current_local_gb:
            if properties['local_gb'] == 0 and current_local_gb > 0:
                properties['local_gb'] = current_local_gb
                LOG.warning('Could not discover size of disk on the node '
                            '%s. Value of `properties/local_gb` of the '
                            'node is not overwritten.', task.node.uuid)

        for known_property in self.ESSENTIAL_PROPERTIES:
            inspected_properties[known_property] = properties[known_property]
        node_properties = task.node.properties
        node_properties.update(inspected_properties)
        task.node.properties = node_properties

        # Inspect the hardware for additional hardware capabilities.
        # Since additional hardware capabilities may not apply to all the
        # hardwares, the method inspect_hardware() doesn't raise an error
        # for these capabilities.
        capabilities = _get_capabilities(task.node, ilo_object)
        model = None
        if capabilities:
            model = capabilities.get('server_model')
            valid_cap = _create_supported_capabilities_dict(capabilities)
            capabilities = utils.get_updated_capabilities(
                task.node.properties.get('capabilities'), valid_cap)
            if capabilities:
                node_properties['capabilities'] = capabilities
                task.node.properties = node_properties

        # Inspect the hardware for security parameters related information.
        # Since it applies only for Gen10 based hardware, the method
        # inspect_hardware() doesn't raise an error.
        if model and 'Gen10' in model:
            security_params = _get_security_parameters(task.node, ilo_object)
            if security_params:
                node_properties['security_parameters'] = (
                    security_params.get('security_parameters'))
                task.node.properties = node_properties

        # RIBCL(Gen8) protocol cannot determine if a NIC
        # is physically connected with cable or not when the server
        # is not provisioned. RIS(Gen9) can detect the same for few NIC
        # adapters but not for all. However it is possible to determine
        # the same using Redfish(Gen10) protocol. Hence proliantutils
        # returns ALL MACs for Gen8 and Gen9 while it returns
        # only active MACs for Gen10. A warning is being added
        # for the user so that he knows that he needs to remove the
        # ironic ports created for inactive ports for Gen8 and Gen9.
        servers = ['Gen8', 'Gen9']
        if model is not None and any(serv in model for serv in servers):
            LOG.warning('iLO cannot determine if the NICs are physically '
                        'connected or not for ProLiant Gen8 and Gen9 servers. '
                        'Hence returns all the MACs present on the server. '
                        'Please remove the ironic ports created for inactive '
                        'NICs manually for the node %(node)s',
                        {"node": task.node.uuid})
        task.node.save()

        # Create ports for the nics detected.
        inspect_utils.create_ports_if_not_exist(
            task, list(result['macs'].values()))

        LOG.debug("Node properties for %(node)s are updated as "
                  "%(properties)s",
                  {'properties': inspected_properties,
                   'node': task.node.uuid})

        LOG.info("Node %s inspected.", task.node.uuid)
        if power_turned_on:
            conductor_utils.node_power_action(task, states.POWER_OFF)
            LOG.info("The node %s was powered on for inspection. "
                     "Powered off the node as inspection completed.",
                     task.node.uuid)
        return states.MANAGEABLE
