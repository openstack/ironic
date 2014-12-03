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

Includes decorator for re-raising Ironic-type exceptions.

SHOULD include dedicated exception logging.

"""

from oslo.config import cfg
import six

from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.openstack.common import log as logging


LOG = logging.getLogger(__name__)

exc_log_opts = [
    cfg.BoolOpt('fatal_exception_format_errors',
                default=False,
                help='Make exception message format errors fatal.'),
]

CONF = cfg.CONF
CONF.register_opts(exc_log_opts)


def _cleanse_dict(original):
    """Strip all admin_password, new_pass, rescue_pass keys from a dict."""
    return dict((k, v) for k, v in original.iteritems() if "_pass" not in k)


class IronicException(Exception):
    """Base Ironic Exception

    To correctly use this class, inherit from it and define
    a 'message' property. That message will get printf'd
    with the keyword arguments provided to the constructor.

    """
    message = _("An unknown exception occurred.")
    code = 500
    headers = {}
    safe = False

    def __init__(self, message=None, **kwargs):
        self.kwargs = kwargs

        if 'code' not in self.kwargs:
            try:
                self.kwargs['code'] = self.code
            except AttributeError:
                pass

        if not message:
            try:
                message = self.message % kwargs

            except Exception as e:
                # kwargs doesn't match a variable in the message
                # log the issue and the kwargs
                LOG.exception(_LE('Exception in string format operation'))
                for name, value in kwargs.iteritems():
                    LOG.error("%s: %s" % (name, value))

                if CONF.fatal_exception_format_errors:
                    raise e
                else:
                    # at least get the core message out if something happened
                    message = self.message

        super(IronicException, self).__init__(message)

    def format_message(self):
        if self.__class__.__name__.endswith('_Remote'):
            return self.args[0]
        else:
            return six.text_type(self)


class NotAuthorized(IronicException):
    message = _("Not authorized.")
    code = 403


class OperationNotPermitted(NotAuthorized):
    message = _("Operation not permitted.")


class Invalid(IronicException):
    message = _("Unacceptable parameters.")
    code = 400


class Conflict(IronicException):
    message = _('Conflict.')
    code = 409


class TemporaryFailure(IronicException):
    message = _("Resource temporarily unavailable, please retry.")
    code = 503


class InvalidState(Conflict):
    message = _("Invalid resource state.")


class NodeAlreadyExists(Conflict):
    message = _("A node with UUID %(uuid)s already exists.")


class MACAlreadyExists(Conflict):
    message = _("A port with MAC address %(mac)s already exists.")


class ChassisAlreadyExists(Conflict):
    message = _("A chassis with UUID %(uuid)s already exists.")


class PortAlreadyExists(Conflict):
    message = _("A port with UUID %(uuid)s already exists.")


class InstanceAssociated(Conflict):
    message = _("Instance %(instance_uuid)s is already associated with a node,"
                " it cannot be associated with this other node %(node)s")


class InvalidUUID(Invalid):
    message = _("Expected a uuid but received %(uuid)s.")


class InvalidIdentity(Invalid):
    message = _("Expected an uuid or int but received %(identity)s.")


class InvalidMAC(Invalid):
    message = _("Expected a MAC address but received %(mac)s.")


class InvalidStateRequested(Invalid):
    message = _("Invalid state '%(state)s' requested for node %(node)s.")


class PatchError(Invalid):
    message = _("Couldn't apply patch '%(patch)s'. Reason: %(reason)s")


class InstanceDeployFailure(IronicException):
    message = _("Failed to deploy instance: %(reason)s")


class ImageUnacceptable(IronicException):
    message = _("Image %(image_id)s is unacceptable: %(reason)s")


class ImageConvertFailed(IronicException):
    message = _("Image %(image_id)s is unacceptable: %(reason)s")


# Cannot be templated as the error syntax varies.
# msg needs to be constructed when raised.
class InvalidParameterValue(Invalid):
    message = _("%(err)s")


class MissingParameterValue(InvalidParameterValue):
    message = _("%(err)s")


class Duplicate(IronicException):
    message = _("Resource already exists.")


class NotFound(IronicException):
    message = _("Resource could not be found.")
    code = 404


class DHCPNotFound(NotFound):
    message = _("Failed to load DHCP provider %(dhcp_provider_name)s.")


class DriverNotFound(NotFound):
    message = _("Failed to load driver %(driver_name)s.")


class ImageNotFound(NotFound):
    message = _("Image %(image_id)s could not be found.")


class NoValidHost(NotFound):
    message = _("No valid host was found. Reason: %(reason)s")


class InstanceNotFound(NotFound):
    message = _("Instance %(instance)s could not be found.")


class NodeNotFound(NotFound):
    message = _("Node %(node)s could not be found.")


class NodeAssociated(InvalidState):
    message = _("Node %(node)s is associated with instance %(instance)s.")


class PortNotFound(NotFound):
    message = _("Port %(port)s could not be found.")


class FailedToUpdateDHCPOptOnPort(IronicException):
    message = _("Update DHCP options on port: %(port_id)s failed.")


class FailedToGetIPAddressOnPort(IronicException):
    message = _("Retrieve IP address on port: %(port_id)s failed.")


class InvalidIPv4Address(IronicException):
    message = _("Invalid IPv4 address %(ip_address)s.")


class FailedToUpdateMacOnPort(IronicException):
    message = _("Update MAC address on port: %(port_id)s failed.")


class ChassisNotFound(NotFound):
    message = _("Chassis %(chassis)s could not be found.")


class ConductorNotFound(NotFound):
    message = _("Conductor %(conductor)s could not be found.")


class ConductorAlreadyRegistered(IronicException):
    message = _("Conductor %(conductor)s already registered.")


class PowerStateFailure(InvalidState):
    message = _("Failed to set node power state to %(pstate)s.")


class ExclusiveLockRequired(NotAuthorized):
    message = _("An exclusive lock is required, "
                "but the current context has a shared lock.")


class NodeMaintenanceFailure(Invalid):
    message = _("Failed to toggle maintenance-mode flag "
                "for node %(node)s: %(reason)s")


class NodeConsoleNotEnabled(Invalid):
    message = _("Console access is not enabled on node %(node)s")


class NodeInMaintenance(Invalid):
    message = _("The %(op)s operation can't be performed on node "
                "%(node)s because it's in maintenance mode.")


class NodeInWrongPowerState(InvalidState):
    message = _("Can not change instance association while node "
                "%(node)s is in power state %(pstate)s.")


class ChassisNotEmpty(Invalid):
    message = _("Cannot complete the requested action because chassis "
                "%(chassis)s contains nodes.")


class IPMIFailure(IronicException):
    message = _("IPMI call failed: %(cmd)s.")


class SSHConnectFailed(IronicException):
    message = _("Failed to establish SSH connection to host %(host)s.")


class SSHCommandFailed(IronicException):
    message = _("Failed to execute command via SSH: %(cmd)s.")


class UnsupportedObjectError(IronicException):
    message = _('Unsupported object type %(objtype)s')


class OrphanedObjectError(IronicException):
    message = _('Cannot call %(method)s on orphaned %(objtype)s object')


class UnsupportedDriverExtension(Invalid):
    message = _('Driver %(driver)s does not support %(extension)s.')


class IncompatibleObjectVersion(IronicException):
    message = _('Version %(objver)s of %(objname)s is not supported')


class GlanceConnectionFailed(IronicException):
    message = _("Connection to glance host %(host)s:%(port)s failed: "
                "%(reason)s")


class ImageNotAuthorized(NotAuthorized):
    message = _("Not authorized for image %(image_id)s.")


class InvalidImageRef(Invalid):
    message = _("Invalid image href %(image_href)s.")


class KeystoneUnauthorized(IronicException):
    message = _("Not authorized in Keystone.")


class KeystoneFailure(IronicException):
    pass


# aliases for backward compatibility, should be removed after Kilo cycle
CatalogUnauthorized = KeystoneUnauthorized
CatalogFailure = KeystoneFailure


class CatalogNotFound(IronicException):
    message = _("Service type %(service_type)s with endpoint type "
                "%(endpoint_type)s not found in keystone service catalog.")


class ServiceUnavailable(IronicException):
    message = _("Connection failed")


class Forbidden(IronicException):
    message = _("Requested OpenStack Images API is forbidden")


class BadRequest(IronicException):
    pass


class InvalidEndpoint(IronicException):
    message = _("The provided endpoint is invalid")


class CommunicationError(IronicException):
    message = _("Unable to communicate with the server.")


class HTTPForbidden(Forbidden):
    pass


class Unauthorized(IronicException):
    pass


class HTTPNotFound(NotFound):
    pass


class ConfigNotFound(IronicException):
    message = _("Could not find config at %(path)s")


class NodeLocked(Conflict):
    message = _("Node %(node)s is locked by host %(host)s, please retry "
                "after the current operation is completed.")


class NodeNotLocked(Invalid):
    message = _("Node %(node)s found not to be locked on release")


class NoFreeConductorWorker(TemporaryFailure):
    message = _('Requested action cannot be performed due to lack of free '
                'conductor workers.')
    code = 503  # Service Unavailable (temporary).


class VendorPassthruException(IronicException):
    pass


class ConfigInvalid(IronicException):
    message = _("Invalid configuration file. %(error_msg)s")


class DriverLoadError(IronicException):
    message = _("Driver %(driver)s could not be loaded. Reason: %(reason)s.")


class ConsoleError(IronicException):
    pass


class NoConsolePid(ConsoleError):
    message = _("Could not find pid in pid file %(pid_path)s")


class ConsoleSubprocessFailed(ConsoleError):
    message = _("Console subprocess failed to start. %(error)s")


class PasswordFileFailedToCreate(IronicException):
    message = _("Failed to create the password file. %(error)s")


class IBootOperationError(IronicException):
    pass


class IloOperationError(IronicException):
    message = _("%(operation)s failed, error: %(error)s")


class DracClientError(IronicException):
    message = _('DRAC client failed. '
                'Last error (cURL error code): %(last_error)s, '
                'fault string: "%(fault_string)s" '
                'response_code: %(response_code)s')


class DracOperationError(IronicException):
    message = _('DRAC %(operation)s failed. Reason: %(error)s')


class DracConfigJobCreationError(DracOperationError):
    message = _('DRAC failed to create a configuration job. '
                'Reason: %(error)s')


class DracInvalidFilterDialect(DracOperationError):
    message = _('Invalid filter dialect \'%(invalid_filter)s\'. '
                'Supported options are %(supported)s')


class FailedToGetSensorData(IronicException):
    message = _("Failed to get sensor data for node %(node)s. "
                "Error: %(error)s")


class FailedToParseSensorData(IronicException):
    message = _("Failed to parse sensor data for node %(node)s. "
                "Error: %(error)s")


class InsufficientDiskSpace(IronicException):
    message = _("Disk volume where '%(path)s' is located doesn't have "
                "enough disk space. Required %(required)d MiB, "
                "only %(actual)d MiB available space present.")


class ImageCreationFailed(IronicException):
    message = _('Creating %(image_type)s image failed: %(error)s')


class SwiftOperationError(IronicException):
    message = _("Swift operation '%(operation)s' failed: %(error)s")


class SNMPFailure(IronicException):
    message = _("SNMP operation '%(operation)s' failed: %(error)s")


class FileSystemNotSupported(IronicException):
    message = _("Failed to create a file system. "
                "File system %(fs)s is not supported.")
