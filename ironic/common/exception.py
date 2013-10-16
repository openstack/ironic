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

import functools

from oslo.config import cfg

from ironic.common import safe_utils
from ironic.openstack.common import excutils
from ironic.openstack.common import log as logging


LOG = logging.getLogger(__name__)

exc_log_opts = [
    cfg.BoolOpt('fatal_exception_format_errors',
                default=False,
                help='make exception message format errors fatal'),
]

CONF = cfg.CONF
CONF.register_opts(exc_log_opts)


class ProcessExecutionError(IOError):
    def __init__(self, stdout=None, stderr=None, exit_code=None, cmd=None,
                 description=None):
        self.exit_code = exit_code
        self.stderr = stderr
        self.stdout = stdout
        self.cmd = cmd
        self.description = description

        if description is None:
            description = _('Unexpected error while running command.')
        if exit_code is None:
            exit_code = '-'
        message = (_('%(description)s\nCommand: %(cmd)s\n'
                     'Exit code: %(exit_code)s\nStdout: %(stdout)r\n'
                     'Stderr: %(stderr)r') %
                   {'description': description, 'cmd': cmd,
                    'exit_code': exit_code, 'stdout': stdout,
                    'stderr': stderr})
        IOError.__init__(self, message)


def _cleanse_dict(original):
    """Strip all admin_password, new_pass, rescue_pass keys from a dict."""
    return dict((k, v) for k, v in original.iteritems() if not "_pass" in k)


def wrap_exception(notifier=None, publisher_id=None, event_type=None,
                   level=None):
    """This decorator wraps a method to catch any exceptions that may
    get thrown. It logs the exception as well as optionally sending
    it to the notification system.
    """
    def inner(f):
        def wrapped(self, context, *args, **kw):
            # Don't store self or context in the payload, it now seems to
            # contain confidential information.
            try:
                return f(self, context, *args, **kw)
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    if notifier:
                        payload = dict(exception=e)
                        call_dict = safe_utils.getcallargs(f, *args, **kw)
                        cleansed = _cleanse_dict(call_dict)
                        payload.update({'args': cleansed})

                        # Use a temp vars so we don't shadow
                        # our outer definitions.
                        temp_level = level
                        if not temp_level:
                            temp_level = notifier.ERROR

                        temp_type = event_type
                        if not temp_type:
                            # If f has multiple decorators, they must use
                            # functools.wraps to ensure the name is
                            # propagated.
                            temp_type = f.__name__

                        notifier.notify(context, publisher_id, temp_type,
                                        temp_level, payload)

        return functools.wraps(f)(wrapped)
    return inner


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
            return unicode(self)


class NotAuthorized(IronicException):
    message = _("Not authorized.")
    code = 403


class AdminRequired(NotAuthorized):
    message = _("User does not have admin privileges")


class PolicyNotAuthorized(NotAuthorized):
    message = _("Policy doesn't allow %(action)s to be performed.")


class OperationNotPermitted(NotAuthorized):
    message = _("Operation not permitted.")


class Invalid(IronicException):
    message = _("Unacceptable parameters.")
    code = 400


class InvalidState(IronicException):
    message = _("Invalid resource state.")
    code = 409


class InvalidCPUInfo(Invalid):
    message = _("Unacceptable CPU info: %(reason)s")


class InvalidIpAddressError(Invalid):
    message = _("%(address)s is not a valid IP v4/6 address.")


class InvalidDiskFormat(Invalid):
    message = _("Disk format %(disk_format)s is not acceptable")


class InvalidUUID(Invalid):
    message = _("Expected a uuid but received %(uuid)s.")


class InvalidIdentity(Invalid):
    message = _("Expected an uuid or int but received %(identity)s.")


class InvalidMAC(Invalid):
    message = _("Expected a MAC address but received %(mac)s.")


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


class DiskNotFound(NotFound):
    message = _("No disk at %(location)s")


class DriverNotFound(NotFound):
    message = _("Failed to load driver %(driver_name)s.")


class ImageNotFound(NotFound):
    message = _("Image %(image_id)s could not be found.")


class HostNotFound(NotFound):
    message = _("Host %(host)s could not be found.")


class ConsoleNotFound(NotFound):
    message = _("Console %(console_id)s could not be found.")


class FileNotFound(NotFound):
    message = _("File %(file_path)s could not be found.")


class NoValidHost(NotFound):
    message = _("No valid host was found. %(reason)s")


class InstanceNotFound(NotFound):
    message = _("Instance %(instance)s could not be found.")


class NodeNotFound(NotFound):
    message = _("Node %(node)s could not be found.")


class NodeLocked(InvalidState):
    message = _("Node %(node)s is locked by another process.")


class NodeAssociated(InvalidState):
    message = _("Node %(node)s is associated with instance %(instance)s.")


class PortNotFound(NotFound):
    message = _("Port %(port)s could not be found.")


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


class NodeInUse(InvalidState):
    message = _("Unable to complete the requested action because node "
                "%(node)s is currently in use by another process.")


class NodeInWrongPowerState(InvalidState):
    message = _("Can not change instance association while node "
            "%(node)s is in power state %(pstate)s.")


class NodeNotConfigured(InvalidState):
    message = _("Can not change power state because node %(node)s "
            "is not fully configured.")


class ChassisNotEmpty(Invalid):
    message = _("Cannot complete the requested action because chassis "
                "%(chassis)s contains nodes.")


class IPMIFailure(IronicException):
    message = _("IPMI call failed: %(cmd)s.")


class SSHConnectFailed(IronicException):
    message = _("Failed to establish SSH connection to host %(host)s.")


class UnsupportedObjectError(IronicException):
    message = _('Unsupported object type %(objtype)s')


class OrphanedObjectError(IronicException):
    message = _('Cannot call %(method)s on orphaned %(objtype)s object')


class UnsupportedDriverExtension(Invalid):
    message = _('Driver %(driver)s for node %(node)s does not '
                'support %(extension)s.')


class IncompatibleObjectVersion(IronicException):
    message = _('Version %(objver)s of %(objname)s is not supported')


class GlanceConnectionFailed(IronicException):
    message = "Connection to glance host %(host)s:%(port)s failed: %(reason)s"


class ImageNotAuthorized(NotAuthorized):
    message = "Not authorized for image %(image_id)s."


class InvalidImageRef(Invalid):
    message = "Invalid image href %(image_href)s."


class CatalogUnauthorized(IronicException):
    message = _("Unauthorised for keystone service catalog.")


class CatalogFailure(IronicException):
    pass


class CatalogNotFound(IronicException):
    message = _("Attr %(attr)s with value %(value)s not found in keystone "
                "service catalog.")


class ServiceUnavailable(IronicException):
    message = "Connection failed"


class Forbidden(IronicException):
    message = "Requested OpenStack Images API is forbidden"


class BadRequest(IronicException):
    pass


class HTTPException(IronicException):
    message = "Requested version of OpenStack Images API is not available."


class InvalidEndpoint(IronicException):
    message = "The provided endpoint is invalid"


class CommunicationError(IronicException):
    message = "Unable to communicate with the server."


class HTTPForbidden(Forbidden):
    pass


class Unauthorized(IronicException):
    pass


class HTTPNotFound(NotFound):
    pass
