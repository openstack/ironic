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

import os
import tempfile

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import base64
from oslo_utils import strutils
from oslo_utils import timeutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import swift
from ironic.conductor import utils
from ironic.drivers import base
from ironic.drivers.modules import agent_client


LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class MixinVendorInterface(base.VendorInterface):
    """Wrapper around multiple VendorInterfaces."""

    def __init__(self, mapping, driver_passthru_mapping=None):
        """Wrapper around multiple VendorInterfaces.

        :param mapping: dict of {'method': interface} specifying how to combine
                        multiple vendor interfaces into one vendor driver.
        :param driver_passthru_mapping: dict of {'method': interface}
                                        specifying how to map
                                        driver_vendor_passthru calls to
                                        interfaces.

        """
        self.mapping = mapping
        self.driver_level_mapping = driver_passthru_mapping or {}
        self.vendor_routes = self._build_routes(self.mapping)
        self.driver_routes = self._build_routes(self.driver_level_mapping,
                                                driver_passthru=True)

    def _build_routes(self, map_dict, driver_passthru=False):
        """Build the mapping for the vendor calls.

        Build the mapping between the given methods and the corresponding
        method metadata.

        :param map_dict: dict of {'method': interface} specifying how
                         to map multiple vendor calls to interfaces.
        :param driver_passthru: Boolean value. Whether build the mapping
                                to the node vendor passthru or driver
                                vendor passthru.
        """
        d = {}
        for method_name in map_dict:
            iface = map_dict[method_name]
            if driver_passthru:
                driver_methods = iface.driver_routes
            else:
                driver_methods = iface.vendor_routes

            try:
                d.update({method_name: driver_methods[method_name]})
            except KeyError:
                pass
        return d

    def _get_route(self, method):
        """Return the driver interface which contains the given method.

        :param method: The name of the vendor method.
        """
        if not method:
            raise exception.MissingParameterValue(
                _("Method not specified when calling vendor extension."))

        try:
            route = self.mapping[method]
        except KeyError:
            raise exception.InvalidParameterValue(
                _('No handler for method %s') % method)

        return route

    def get_properties(self):
        """Return the properties from all the VendorInterfaces.

        :returns: a dictionary of <property_name>:<property_description>
                  entries.
        """
        properties = {}
        interfaces = set(self.mapping.values())
        for interface in interfaces:
            properties.update(interface.get_properties())
        return properties

    def validate(self, task, method, **kwargs):
        """Call validate on the appropriate interface only.

        :raises: UnsupportedDriverExtension if 'method' can not be mapped to
                 the supported interfaces.
        :raises: InvalidParameterValue if 'method' is invalid.
        :raises: MissingParameterValue if missing 'method' or parameters
                 in kwargs.

        """
        route = self._get_route(method)
        route.validate(task, method=method, **kwargs)


def get_node_mac_addresses(task):
    """Get all MAC addresses for the ports belonging to this task's node.

    :param task: a TaskManager instance containing the node to act on.
    :returns: A list of MAC addresses in the format xx:xx:xx:xx:xx:xx.
    """
    return [p.address for p in task.ports]


def get_node_capability(node, capability):
    """Returns 'capability' value from node's 'capabilities' property.

    :param node: Node object.
    :param capability: Capability key.
    :return: Capability value.
             If capability is not present, then return "None"

    """
    capabilities = node.properties.get('capabilities')

    if not capabilities:
        return

    for node_capability in capabilities.split(','):
        parts = node_capability.split(':')
        if len(parts) == 2 and parts[0] and parts[1]:
            if parts[0].strip() == capability:
                return parts[1].strip()
        else:
            LOG.warning("Ignoring malformed capability '%s'. "
                        "Format should be 'key:val'.", node_capability)


def add_node_capability(task, capability, value):
    """Add 'capability' to node's 'capabilities' property.

    If 'capability' is already present, then a duplicate entry
    will be added.

    :param task: Task object.
    :param capability: Capability key.
    :param value: Capability value.

    """
    node = task.node
    properties = node.properties
    capabilities = properties.get('capabilities')

    new_cap = ':'.join([capability, value])

    if capabilities:
        capabilities = ','.join([capabilities, new_cap])
    else:
        capabilities = new_cap

    properties['capabilities'] = capabilities
    node.properties = properties
    node.save()


def ensure_next_boot_device(task, driver_info):
    """Ensure boot from correct device if persistent is True

    If ipmi_force_boot_device is True and is_next_boot_persistent, set to
    boot from correct device, else unset is_next_boot_persistent field.

    :param task: Node object.
    :param driver_info: Node driver_info.
    """
    ifbd = driver_info.get('force_boot_device', False)
    if strutils.bool_from_string(ifbd):
        driver_internal_info = task.node.driver_internal_info
        if driver_internal_info.get('is_next_boot_persistent') is False:
            driver_internal_info.pop('is_next_boot_persistent', None)
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
        else:
            boot_device = driver_internal_info.get('persistent_boot_device')
            if boot_device:
                utils.node_set_boot_device(task, boot_device)


def force_persistent_boot(task, device, persistent):
    """Set persistent boot device to driver_internal_info

    If persistent is True set 'persistent_boot_device' field to the
    boot device and reset persistent to False, else set
    'is_next_boot_persistent' to False.

    :param task: Task object.
    :param device: Boot device.
    :param persistent: Whether next boot is persistent or not.
    """

    node = task.node
    driver_internal_info = node.driver_internal_info
    if persistent:
        driver_internal_info.pop('is_next_boot_persistent', None)
        driver_internal_info['persistent_boot_device'] = device
    else:
        driver_internal_info['is_next_boot_persistent'] = False

    node.driver_internal_info = driver_internal_info
    node.save()


def capabilities_to_dict(capabilities):
    """Parse the capabilities string into a dictionary

    :param capabilities: the capabilities of the node as a formatted string.
    :raises: InvalidParameterValue if capabilities is not an string or has a
             malformed value
    """
    capabilities_dict = {}
    if capabilities:
        if not isinstance(capabilities, str):
            raise exception.InvalidParameterValue(
                _("Value of 'capabilities' must be string. Got %s")
                % type(capabilities))
        try:
            for capability in capabilities.split(','):
                key, value = capability.split(':')
                capabilities_dict[key] = value
        except ValueError:
            raise exception.InvalidParameterValue(
                _("Malformed capabilities value: %s") % capability
            )

    return capabilities_dict


def normalize_mac(mac):
    """Remove '-' and ':' characters and lowercase the MAC string.

    :param mac: MAC address to normalize.
    :return: Normalized MAC address string.
    """
    return mac.replace('-', '').replace(':', '').lower()


def get_ramdisk_logs_file_name(node, label=None):
    """Construct the log file name.

    :param node: A node object.
    :param label: A string to label the log file such as a clean step name.
    :returns: The log file name.
    """
    timestamp = timeutils.utcnow().strftime('%Y-%m-%d-%H-%M-%S')
    file_name_fields = [node.uuid]
    if node.name:
        file_name_fields.append(node.name)

    if node.instance_uuid:
        file_name_fields.append(node.instance_uuid)

    if label:
        file_name_fields.append(label)

    file_name_fields.append(timestamp)
    return '_'.join(file_name_fields) + '.tar.gz'


def store_ramdisk_logs(node, logs, label=None):
    """Store the ramdisk logs.

    This method stores the ramdisk logs according to the configured
    storage backend.

    :param node: A node object.
    :param logs: A gzipped and base64 encoded string containing the
                 logs archive.
    :param label: A string to label the log file such as a clean step name.
    :raises: OSError if the directory to save the logs cannot be created.
    :raises: IOError when the logs can't be saved to the local file system.
    :raises: SwiftOperationError, if any operation with Swift fails.

    """
    logs_file_name = get_ramdisk_logs_file_name(node, label=label)
    data = base64.decode_as_bytes(logs)

    if CONF.agent.deploy_logs_storage_backend == 'local':
        if not os.path.exists(CONF.agent.deploy_logs_local_path):
            os.makedirs(CONF.agent.deploy_logs_local_path)

        log_path = os.path.join(CONF.agent.deploy_logs_local_path,
                                logs_file_name)
        with open(log_path, 'wb') as f:
            f.write(data)

    elif CONF.agent.deploy_logs_storage_backend == 'swift':
        with tempfile.NamedTemporaryFile(dir=CONF.tempdir) as f:
            f.write(data)
            f.flush()

            # convert days to seconds
            timeout = CONF.agent.deploy_logs_swift_days_to_expire * 86400
            object_headers = {'X-Delete-After': str(timeout)}
            swift_api = swift.SwiftAPI()
            swift_api.create_object(
                CONF.agent.deploy_logs_swift_container, logs_file_name,
                f.name, object_headers=object_headers)


def collect_ramdisk_logs(node, label=None):
    """Collect and store the system logs from the IPA ramdisk.

    Collect and store the system logs from the IPA ramdisk. This method
    makes a call to the IPA ramdisk to collect the logs and store it
    according to the configured storage backend.

    :param node: A node object.
    :param label: A string to label the log file such as a clean step name.
    """
    if CONF.agent.deploy_logs_collect == 'never':
        return

    client = agent_client.AgentClient()
    try:
        result = client.collect_system_logs(node)
    except exception.IronicException as e:
        LOG.error('Failed to invoke collect_system_logs agent command '
                  'for node %(node)s. Error: %(error)s',
                  {'node': node.uuid, 'error': e})
        return

    error = result.get('faultstring')
    if error is not None:
        LOG.error('Failed to collect logs from the node %(node)s '
                  'deployment. Error: %(error)s',
                  {'node': node.uuid, 'error': error})
        return

    try:
        store_ramdisk_logs(node, result['command_result']['system_logs'],
                           label=label)
    except exception.SwiftOperationError as e:
        LOG.error('Failed to store the logs from the node %(node)s '
                  'deployment in Swift. Error: %(error)s',
                  {'node': node.uuid, 'error': e})
    except EnvironmentError as e:
        LOG.exception('Failed to store the logs from the node %(node)s '
                      'deployment due a file-system related error. '
                      'Error: %(error)s', {'node': node.uuid, 'error': e})
    except Exception as e:
        LOG.exception('Unknown error when storing logs from the node '
                      '%(node)s deployment. Error: %(error)s',
                      {'node': node.uuid, 'error': e})


OPTIONAL_PROPERTIES = {
    'force_persistent_boot_device': _("Controls the persistency of boot order "
                                      "changes. 'Always' will make all "
                                      "changes persistent, 'Default' will "
                                      "make all but the final one upon "
                                      "instance deployment non-persistent, "
                                      "and 'Never' will make no persistent "
                                      "changes at all. The old values 'True' "
                                      "and 'False' are still supported but "
                                      "deprecated in favor of the new ones."
                                      "Defaults to 'Default'. Optional."),
}


def get_kernel_append_params(node, default):
    """Get the applicable kernel params.

    The locations are checked in this order:

    1. The node's instance_info.
    2. The node's driver_info.
    3. Configuration.

    :param node: Node object.
    :param default: Default value.
    """
    for location in ('instance_info', 'driver_info'):
        result = getattr(node, location).get('kernel_append_params')
        if result is not None:
            return result

    return default


def _get_field(node, name, deprecated_prefix=None):
    value = node.driver_info.get(name)
    if value or not deprecated_prefix:
        return value

    deprecated_name = f'{deprecated_prefix}_{name}'
    value = node.driver_info.get(deprecated_name)
    if value:
        LOG.warning("The driver_info field %s of node %s is deprecated, "
                    "please use %s instead",
                    deprecated_name, node.uuid, name)
        return value


def get_agent_kernel_ramdisk(node, mode='deploy', deprecated_prefix=None):
    """Get the agent kernel/ramdisk as a dictionary."""
    kernel_name = f'{mode}_kernel'
    ramdisk_name = f'{mode}_ramdisk'
    kernel, ramdisk = (
        _get_field(node, kernel_name, deprecated_prefix),
        _get_field(node, ramdisk_name, deprecated_prefix),
    )
    # NOTE(dtantsur): avoid situation when e.g. deploy_kernel comes
    # from driver_info but deploy_ramdisk comes from configuration,
    # since it's a sign of a potential operator's mistake.
    if not kernel or not ramdisk:
        return {
            kernel_name: getattr(CONF.conductor, kernel_name),
            ramdisk_name: getattr(CONF.conductor, ramdisk_name),
        }
    else:
        return {
            kernel_name: kernel,
            ramdisk_name: ramdisk
        }


def get_agent_iso(node, mode='deploy', deprecated_prefix=None):
    """Get the agent ISO image."""
    return _get_field(node, f'{mode}_iso', deprecated_prefix)
