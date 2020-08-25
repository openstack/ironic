# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Ironic base exception handling.

SHOULD include dedicated exception logging.

"""

import collections

from oslo_log import log as logging
from oslo_serialization import jsonutils
import six
from six.moves import http_client

from ironic.common.i18n import _
from ironic.conf import CONF

LOG = logging.getLogger(__name__)


def _ensure_exception_kwargs_serializable(exc_class_name, kwargs):
    """Ensure that kwargs are serializable

    Ensure that all kwargs passed to exception constructor can be passed over
    RPC, by trying to convert them to JSON, or, as a last resort, to string.
    If it is not possible, unserializable kwargs will be removed, letting the
    receiver to handle the exception string as it is configured to.

    :param exc_class_name: an IronicException class name.
    :param kwargs: a dictionary of keyword arguments passed to the exception
        constructor.
    :returns: a dictionary of serializable keyword arguments.
    """
    serializers = [(jsonutils.dumps, _('when converting to JSON')),
                   (six.text_type, _('when converting to string'))]
    exceptions = collections.defaultdict(list)
    serializable_kwargs = {}
    for k, v in kwargs.items():
        for serializer, msg in serializers:
            try:
                serializable_kwargs[k] = serializer(v)
                exceptions.pop(k, None)
                break
            except Exception as e:
                exceptions[k].append(
                    '(%(serializer_type)s) %(e_type)s: %(e_contents)s' %
                    {'serializer_type': msg, 'e_contents': e,
                     'e_type': e.__class__.__name__})
    if exceptions:
        LOG.error("One or more arguments passed to the %(exc_class)s "
                  "constructor as kwargs can not be serialized. The "
                  "serialized arguments: %(serialized)s. These "
                  "unserialized kwargs were dropped because of the "
                  "exceptions encountered during their "
                  "serialization:\n%(errors)s",
                  dict(errors=';\n'.join("%s: %s" % (k, '; '.join(v))
                                         for k, v in exceptions.items()),
                       exc_class=exc_class_name,
                       serialized=serializable_kwargs))
        # We might be able to actually put the following keys' values into
        # format string, but there is no guarantee, drop it just in case.
        for k in exceptions:
            del kwargs[k]
    return serializable_kwargs


class IronicException(Exception):
    """Base Ironic Exception

    To correctly use this class, inherit from it and define
    a '_msg_fmt' property. That message will get printf'd
    with the keyword arguments provided to the constructor.

    If you need to access the message from an exception you should use
    six.text_type(exc)

    """
    _msg_fmt = _("An unknown exception occurred.")
    code = http_client.INTERNAL_SERVER_ERROR
    headers = {}
    safe = False

    def __init__(self, message=None, **kwargs):

        self.kwargs = _ensure_exception_kwargs_serializable(
            self.__class__.__name__, kwargs)

        if 'code' not in self.kwargs:
            try:
                self.kwargs['code'] = self.code
            except AttributeError:
                pass

        if not message:
            try:
                message = self._msg_fmt % kwargs

            except Exception as e:
                # kwargs doesn't match a variable in self._msg_fmt
                # log the issue and the kwargs
                prs = ', '.join('%s: %s' % pair for pair in kwargs.items())
                LOG.exception('Exception in string format operation '
                              '(arguments %s)', prs)
                if CONF.fatal_exception_format_errors:
                    raise e
                else:
                    # at least get the core self._msg_fmt out if something
                    # happened
                    message = self._msg_fmt

        super(IronicException, self).__init__(message)

    def __str__(self):
        """Encode to utf-8 then wsme api can consume it as well."""
        value = self.__unicode__()
        if six.PY3:
            # On Python 3 unicode is the same as str
            return value
        else:
            return value.encode('utf-8')

    def __unicode__(self):
        """Return a unicode representation of the exception message."""
        return six.text_type(self.args[0])


class NotAuthorized(IronicException):
    _msg_fmt = _("Not authorized.")
    code = http_client.FORBIDDEN


class OperationNotPermitted(NotAuthorized):
    _msg_fmt = _("Operation not permitted.")


class Invalid(IronicException):
    _msg_fmt = _("Unacceptable parameters.")
    code = http_client.BAD_REQUEST


class Conflict(IronicException):
    _msg_fmt = _('Conflict.')
    code = http_client.CONFLICT


class TemporaryFailure(IronicException):
    _msg_fmt = _("Resource temporarily unavailable, please retry.")
    code = http_client.SERVICE_UNAVAILABLE


class NotAcceptable(IronicException):
    # TODO(deva): We need to set response headers in the API for this exception
    _msg_fmt = _("Request not acceptable.")
    code = http_client.NOT_ACCEPTABLE


class InvalidState(Conflict):
    _msg_fmt = _("Invalid resource state.")


class NodeAlreadyExists(Conflict):
    _msg_fmt = _("A node with UUID %(uuid)s already exists.")


class MACAlreadyExists(Conflict):
    _msg_fmt = _("A port with MAC address %(mac)s already exists.")


class ChassisAlreadyExists(Conflict):
    _msg_fmt = _("A chassis with UUID %(uuid)s already exists.")


class PortAlreadyExists(Conflict):
    _msg_fmt = _("A port with UUID %(uuid)s already exists.")


class PortgroupAlreadyExists(Conflict):
    _msg_fmt = _("A portgroup with UUID %(uuid)s already exists.")


class PortgroupDuplicateName(Conflict):
    _msg_fmt = _("A portgroup with name %(name)s already exists.")


class PortgroupMACAlreadyExists(Conflict):
    _msg_fmt = _("A portgroup with MAC address %(mac)s already exists.")


class InstanceAssociated(Conflict):
    _msg_fmt = _("Instance %(instance_uuid)s is already associated with a "
                 "node, it cannot be associated with this other node %(node)s")


class DuplicateName(Conflict):
    _msg_fmt = _("A node with name %(name)s already exists.")


class VolumeConnectorAlreadyExists(Conflict):
    _msg_fmt = _("A volume connector with UUID %(uuid)s already exists.")


class VolumeConnectorTypeAndIdAlreadyExists(Conflict):
    _msg_fmt = _("A volume connector with type %(type)s and connector ID "
                 "%(connector_id)s already exists.")


class VolumeTargetAlreadyExists(Conflict):
    _msg_fmt = _("A volume target with UUID %(uuid)s already exists.")


class VolumeTargetBootIndexAlreadyExists(Conflict):
    _msg_fmt = _("A volume target with boot index '%(boot_index)s' "
                 "for the same node already exists.")


class VifAlreadyAttached(Conflict):
    _msg_fmt = _("Unable to attach VIF because VIF %(vif)s is already "
                 "attached to Ironic %(object_type)s %(object_uuid)s")


class NoFreePhysicalPorts(Invalid):
    _msg_fmt = _("Unable to attach VIF %(vif)s, not "
                 "enough free physical ports.")


class VifNotAttached(Invalid):
    _msg_fmt = _("Unable to detach VIF %(vif)s from node %(node)s "
                 "because it is not attached to it.")


class InvalidUUID(Invalid):
    _msg_fmt = _("Expected a UUID but received %(uuid)s.")


class InvalidUuidOrName(Invalid):
    _msg_fmt = _("Expected a logical name or UUID but received %(name)s.")


class InvalidName(Invalid):
    _msg_fmt = _("Expected a logical name but received %(name)s.")


class InvalidIdentity(Invalid):
    _msg_fmt = _("Expected a UUID or int but received %(identity)s.")


class InvalidMAC(Invalid):
    _msg_fmt = _("Expected a MAC address but received %(mac)s.")


class InvalidSwitchID(Invalid):
    _msg_fmt = _("Expected a MAC address or OpenFlow datapath ID but "
                 "received %(switch_id)s.")


class InvalidDatapathID(Invalid):
    _msg_fmt = _("Expected an OpenFlow datapath ID but received "
                 "%(datapath_id)s.")


class InvalidStateRequested(Invalid):
    _msg_fmt = _('The requested action "%(action)s" can not be performed '
                 'on node "%(node)s" while it is in state "%(state)s".')


class PatchError(Invalid):
    _msg_fmt = _("Couldn't apply patch '%(patch)s'. Reason: %(reason)s")


class InstanceDeployFailure(IronicException):
    _msg_fmt = _("Failed to deploy instance: %(reason)s")


class ImageUnacceptable(IronicException):
    _msg_fmt = _("Image %(image_id)s is unacceptable: %(reason)s")


class ImageConvertFailed(IronicException):
    _msg_fmt = _("Image %(image_id)s is unacceptable: %(reason)s")


# Cannot be templated as the error syntax varies.
# msg needs to be constructed when raised.
class InvalidParameterValue(Invalid):
    _msg_fmt = "%(err)s"


class MissingParameterValue(InvalidParameterValue):
    _msg_fmt = "%(err)s"


class Duplicate(IronicException):
    _msg_fmt = _("Resource already exists.")


class NotFound(IronicException):
    _msg_fmt = _("Resource could not be found.")
    code = http_client.NOT_FOUND


class DHCPLoadError(IronicException):
    _msg_fmt = _("Failed to load DHCP provider %(dhcp_provider_name)s, "
                 "reason: %(reason)s")


# TODO(dtantsur): word "driver" is overused in class names here, and generally
# means stevedore driver, not ironic driver. Rename them in the future.


class DriverNotFound(NotFound):
    _msg_fmt = _("Could not find the following driver(s) or hardware type(s): "
                 "%(driver_name)s.")


class DriverNotFoundInEntrypoint(DriverNotFound):
    _msg_fmt = _("Could not find the following items in the "
                 "'%(entrypoint)s' entrypoint: %(names)s.")


class InterfaceNotFoundInEntrypoint(InvalidParameterValue):
    _msg_fmt = _("Could not find the following interface in the "
                 "'%(entrypoint)s' entrypoint: %(iface)s. Valid interfaces "
                 "are %(valid)s.")


class IncompatibleInterface(InvalidParameterValue):
    _msg_fmt = _("%(interface_type)s interface implementation "
                 "'%(interface_impl)s' is not supported by hardware type "
                 "%(hardware_type)s.")


class NoValidDefaultForInterface(InvalidParameterValue):
    # NOTE(rloo): in the line below, there is no blank space after 'For'
    #             because node_info could be an empty string. If node_info
    #             is not empty, it should start with a space.
    _msg_fmt = _("For%(node_info)s %(driver_type)s '%(driver)s', no default "
                 "value found for %(interface_type)s interface.")


class MustBeNone(InvalidParameterValue):
    _msg_fmt = _("For node %(node)s with driver %(driver)s, these node "
                 "fields must be set to None: %(node_fields)s.")


class ImageNotFound(NotFound):
    _msg_fmt = _("Image %(image_id)s could not be found.")


class NoValidHost(NotFound):
    _msg_fmt = _("No valid host was found. Reason: %(reason)s")


class InstanceNotFound(NotFound):
    _msg_fmt = _("Instance %(instance)s could not be found.")


class InputFileError(IronicException):
    _msg_fmt = _("Error with file %(file_name)s. Reason: %(reason)s")


class NodeNotFound(NotFound):
    _msg_fmt = _("Node %(node)s could not be found.")


class PortgroupNotFound(NotFound):
    _msg_fmt = _("Portgroup %(portgroup)s could not be found.")


class PortgroupNotEmpty(Invalid):
    _msg_fmt = _("Cannot complete the requested action because portgroup "
                 "%(portgroup)s contains ports.")


class NodeAssociated(InvalidState):
    _msg_fmt = _("Node %(node)s is associated with instance %(instance)s.")


class PortNotFound(NotFound):
    _msg_fmt = _("Port %(port)s could not be found.")


class FailedToUpdateDHCPOptOnPort(IronicException):
    _msg_fmt = _("Update DHCP options on port: %(port_id)s failed.")


class FailedToCleanDHCPOpts(IronicException):
    _msg_fmt = _("Clean up DHCP options on node: %(node)s failed.")


class FailedToGetIPAddressOnPort(IronicException):
    _msg_fmt = _("Retrieve IP address on port: %(port_id)s failed.")


class InvalidIPv4Address(IronicException):
    _msg_fmt = _("Invalid IPv4 address %(ip_address)s.")


class FailedToUpdateMacOnPort(IronicException):
    _msg_fmt = _("Update MAC address on port: %(port_id)s failed.")


class ChassisNotFound(NotFound):
    _msg_fmt = _("Chassis %(chassis)s could not be found.")


class VolumeConnectorNotFound(NotFound):
    _msg_fmt = _("Volume connector %(connector)s could not be found.")


class VolumeTargetNotFound(NotFound):
    _msg_fmt = _("Volume target %(target)s could not be found.")


class DriverNameConflict(IronicException):
    _msg_fmt = _("Classic and dynamic drivers cannot have the "
                 "same names '%(names)s'.")


class NoDriversLoaded(IronicException):
    _msg_fmt = _("Conductor %(conductor)s cannot be started "
                 "because no drivers were loaded.")


class ConductorNotFound(NotFound):
    _msg_fmt = _("Conductor %(conductor)s could not be found.")


class ConductorAlreadyRegistered(IronicException):
    _msg_fmt = _("Conductor %(conductor)s already registered.")


class ConductorHardwareInterfacesAlreadyRegistered(IronicException):
    _msg_fmt = _("At least one of these (hardware type %(hardware_type)s, "
                 "interface type %(interface_type)s, interfaces "
                 "%(interfaces)s) combinations are already registered for "
                 "this conductor.")


class PowerStateFailure(InvalidState):
    _msg_fmt = _("Failed to set node power state to %(pstate)s.")


class ExclusiveLockRequired(NotAuthorized):
    _msg_fmt = _("An exclusive lock is required, "
                 "but the current context has a shared lock.")


class NodeMaintenanceFailure(Invalid):
    _msg_fmt = _("Failed to toggle maintenance-mode flag "
                 "for node %(node)s: %(reason)s")


class NodeConsoleNotEnabled(Invalid):
    _msg_fmt = _("Console access is not enabled on node %(node)s")


class NodeInMaintenance(Invalid):
    _msg_fmt = _("The %(op)s operation can't be performed on node "
                 "%(node)s because it's in maintenance mode.")


class ChassisNotEmpty(Invalid):
    _msg_fmt = _("Cannot complete the requested action because chassis "
                 "%(chassis)s contains nodes.")


class IPMIFailure(IronicException):
    _msg_fmt = _("IPMI call failed: %(cmd)s.")


class UnsupportedDriverExtension(Invalid):
    _msg_fmt = _('Driver %(driver)s does not support %(extension)s '
                 '(disabled or not implemented).')


class GlanceConnectionFailed(IronicException):
    _msg_fmt = _("Connection to glance endpoint %(endpoint)s failed: "
                 "%(reason)s")


class ImageNotAuthorized(NotAuthorized):
    _msg_fmt = _("Not authorized for image %(image_id)s.")


class InvalidImageRef(Invalid):
    _msg_fmt = _("Invalid image href %(image_href)s.")


class ImageRefValidationFailed(IronicException):
    _msg_fmt = _("Validation of image href %(image_href)s failed, "
                 "reason: %(reason)s")


class ImageDownloadFailed(IronicException):
    _msg_fmt = _("Failed to download image %(image_href)s, reason: %(reason)s")


class KeystoneUnauthorized(IronicException):
    _msg_fmt = _("Not authorized in Keystone.")


class KeystoneFailure(IronicException):
    pass


class CatalogNotFound(IronicException):
    _msg_fmt = _("Service type %(service_type)s with endpoint type "
                 "%(endpoint_type)s not found in keystone service catalog.")


class ServiceUnavailable(IronicException):
    _msg_fmt = _("Connection failed")


class Forbidden(IronicException):
    _msg_fmt = _("Requested OpenStack Images API is forbidden")


class BadRequest(IronicException):
    pass


class InvalidEndpoint(IronicException):
    _msg_fmt = _("The provided endpoint is invalid")


class CommunicationError(IronicException):
    _msg_fmt = _("Unable to communicate with the server.")


class HTTPForbidden(NotAuthorized):
    _msg_fmt = _("Access was denied to the following resource: %(resource)s")


class Unauthorized(IronicException):
    pass


class HTTPNotFound(NotFound):
    pass


class ConfigNotFound(IronicException):
    _msg_fmt = _("Could not find config at %(path)s")


class NodeLocked(Conflict):
    _msg_fmt = _("Node %(node)s is locked by host %(host)s, please retry "
                 "after the current operation is completed.")


class NodeNotLocked(Invalid):
    _msg_fmt = _("Node %(node)s found not to be locked on release")


class NoFreeConductorWorker(TemporaryFailure):
    _msg_fmt = _('Requested action cannot be performed due to lack of free '
                 'conductor workers.')
    code = http_client.SERVICE_UNAVAILABLE


class VendorPassthruException(IronicException):
    pass


class ConfigInvalid(IronicException):
    _msg_fmt = _("Invalid configuration file. %(error_msg)s")


class DriverLoadError(IronicException):
    _msg_fmt = _("Driver, hardware type or interface %(driver)s could not be "
                 "loaded. Reason: %(reason)s.")


class ConsoleError(IronicException):
    pass


class NoConsolePid(ConsoleError):
    _msg_fmt = _("Could not find pid in pid file %(pid_path)s")


class ConsoleSubprocessFailed(ConsoleError):
    _msg_fmt = _("Console subprocess failed to start. %(error)s")


class PasswordFileFailedToCreate(IronicException):
    _msg_fmt = _("Failed to create the password file. %(error)s")


class IloOperationError(IronicException):
    _msg_fmt = _("%(operation)s failed, error: %(error)s")


class IloOperationNotSupported(IronicException):
    _msg_fmt = _("%(operation)s not supported. error: %(error)s")


class DracOperationError(IronicException):
    _msg_fmt = _('DRAC operation failed. Reason: %(error)s')


class FailedToGetSensorData(IronicException):
    _msg_fmt = _("Failed to get sensor data for node %(node)s. "
                 "Error: %(error)s")


class FailedToParseSensorData(IronicException):
    _msg_fmt = _("Failed to parse sensor data for node %(node)s. "
                 "Error: %(error)s")


class InsufficientDiskSpace(IronicException):
    _msg_fmt = _("Disk volume where '%(path)s' is located doesn't have "
                 "enough disk space. Required %(required)d MiB, "
                 "only %(actual)d MiB available space present.")


class ImageCreationFailed(IronicException):
    _msg_fmt = _('Creating %(image_type)s image failed: %(error)s')


class SwiftOperationError(IronicException):
    _msg_fmt = _("Swift operation '%(operation)s' failed: %(error)s")


class SwiftObjectNotFoundError(SwiftOperationError):
    _msg_fmt = _("Swift object %(obj)s from container %(container)s "
                 "not found. Operation '%(operation)s' failed.")


class SNMPFailure(IronicException):
    _msg_fmt = _("SNMP operation '%(operation)s' failed: %(error)s")


class FileSystemNotSupported(IronicException):
    _msg_fmt = _("Failed to create a file system. "
                 "File system %(fs)s is not supported.")


class IRMCOperationError(IronicException):
    _msg_fmt = _('iRMC %(operation)s failed. Reason: %(error)s')


class IRMCSharedFileSystemNotMounted(IronicException):
    _msg_fmt = _("iRMC shared file system '%(share)s' is not mounted.")


class HardwareInspectionFailure(IronicException):
    _msg_fmt = _("Failed to inspect hardware. Reason: %(error)s")


class NodeCleaningFailure(IronicException):
    _msg_fmt = _("Failed to clean node %(node)s: %(reason)s")


class PathNotFound(IronicException):
    _msg_fmt = _("Path %(dir)s does not exist.")


class DirectoryNotWritable(IronicException):
    _msg_fmt = _("Directory %(dir)s is not writable.")


class UcsOperationError(IronicException):
    _msg_fmt = _("Cisco UCS client: operation %(operation)s failed for node"
                 " %(node)s. Reason: %(error)s")


class UcsConnectionError(IronicException):
    _msg_fmt = _("Cisco UCS client: connection failed for node "
                 "%(node)s. Reason: %(error)s")


class ImageUploadFailed(IronicException):
    _msg_fmt = _("Failed to upload %(image_name)s image to web server "
                 "%(web_server)s, reason: %(reason)s")


class CIMCException(IronicException):
    _msg_fmt = _("Cisco IMC exception occurred for node %(node)s: %(error)s")


class OneViewError(IronicException):
    _msg_fmt = _("OneView exception occurred. Error: %(error)s")


class OneViewInvalidNodeParameter(OneViewError):
    _msg_fmt = _("Error while obtaining OneView info from node %(node_uuid)s. "
                 "Error: %(error)s")


class NodeTagNotFound(IronicException):
    _msg_fmt = _("Node %(node_id)s doesn't have a tag '%(tag)s'")


class NetworkError(IronicException):
    _msg_fmt = _("Network operation failure.")


class IncompleteLookup(Invalid):
    _msg_fmt = _("At least one of 'addresses' and 'node_uuid' parameters "
                 "is required")


class NotificationSchemaObjectError(IronicException):
    _msg_fmt = _("Expected object %(obj)s when populating notification payload"
                 " but got object %(source)s")


class NotificationSchemaKeyError(IronicException):
    _msg_fmt = _("Object %(obj)s doesn't have the field \"%(field)s\" "
                 "required for populating notification schema key "
                 "\"%(key)s\"")


class NotificationPayloadError(IronicException):
    _msg_fmt = _("Payload not populated when trying to send notification "
                 "\"%(class_name)s\"")


class StorageError(IronicException):
    _msg_fmt = _("Storage operation failure.")


class RedfishError(IronicException):
    _msg_fmt = _("Redfish exception occurred. Error: %(error)s")


class RedfishConnectionError(RedfishError):
    _msg_fmt = _("Redfish connection failed for node %(node)s: %(error)s")


class PortgroupPhysnetInconsistent(IronicException):
    _msg_fmt = _("Port group %(portgroup)s has member ports with inconsistent "
                 "physical networks (%(physical_networks)s). All ports in a "
                 "port group must have the same physical network.")


class VifInvalidForAttach(Conflict):
    _msg_fmt = _("Unable to attach VIF %(vif)s to node %(node)s. Reason: "
                 "%(reason)s")


class AgentAPIError(IronicException):
    _msg_fmt = _('Agent API for node %(node)s returned HTTP status code '
                 '%(status)s with error: %(error)s')


class NodeTraitNotFound(NotFound):
    _msg_fmt = _("Node %(node_id)s doesn't have a trait '%(trait)s'")


class InstanceRescueFailure(IronicException):
    _msg_fmt = _('Failed to rescue instance %(instance)s for node '
                 '%(node)s: %(reason)s')


class InstanceUnrescueFailure(IronicException):
    _msg_fmt = _('Failed to unrescue instance %(instance)s for node '
                 '%(node)s: %(reason)s')


class AgentConnectionFailed(IronicException):
    _msg_fmt = _("Connection to agent failed: %(reason)s")
