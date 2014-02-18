# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from ironic.openstack.common.gettextutils import _
from ironic.openstack.common import log as logging


LOG = logging.getLogger(__name__)

exc_log_opts = [
    cfg.BoolOpt('fatal_exception_format_errors',
                default=False,
                help='make exception message format errors fatal'),
]

CONF = cfg.CONF
CONF.register_opts(exc_log_opts)


def _cleanse_dict(original):
    """Strip all admin_password, new_pass, rescue_pass keys from a dict."""
    return dict((k, v) for k, v in original.iteritems() if not "_pass" in k)


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
                LOG.exception(_('Exception in string format operation'))
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


class MACAlreadyExists(Conflict):
    message = _("A Port with MAC address %(mac)s already exists.")


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


class NotFound(IronicException):
    message = _("Resource could not be found.")
    code = 404


class DriverNotFound(NotFound):
    message = _("Failed to load driver %(driver_name)s.")


class ImageNotFound(NotFound):
    message = _("Image %(image_id)s could not be found.")


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


class CatalogUnauthorized(IronicException):
    message = _("Unauthorised for keystone service catalog.")


class CatalogFailure(IronicException):
    pass


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


class NodeLocked(TemporaryFailure):
    message = _("Node %(node)s is locked by host %(host)s, please retry "
                "after the current operation is completed.")


class NoFreeConductorWorker(TemporaryFailure):
    message = _('Requested action cannot be performed due to lack of free '
                'conductor workers.')
