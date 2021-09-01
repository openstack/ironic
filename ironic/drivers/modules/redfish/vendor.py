# Copyright 2015 Hewlett-Packard Development Company, L.P.
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
Vendor Interface for Redfish drivers and its supporting methods.
"""

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_utils import importutils
import rfc3986

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers.modules.redfish import boot as redfish_boot
from ironic.drivers.modules.redfish import utils as redfish_utils

sushy = importutils.try_import('sushy')

LOG = log.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)
SUBSCRIPTION_COMMON_FIELDS = {
    'Id', 'Context', 'Protocol', 'Destination', 'EventTypes'
}


class RedfishVendorPassthru(base.VendorInterface):
    """Vendor-specific interfaces for Redfish drivers."""

    def get_properties(self):
        return {}

    @METRICS.timer('RedfishVendorPassthru.validate')
    def validate(self, task, method, **kwargs):
        """Validate vendor-specific actions.

        Checks if a valid vendor passthru method was passed and validates
        the parameters for the vendor passthru method.

        :param task: a TaskManager instance containing the node to act on.
        :param method: method to be validated.
        :param kwargs: kwargs containing the vendor passthru method's
            parameters.
        :raises: InvalidParameterValue, if any of the parameters have invalid
            value.
        """
        if method == 'eject_vmedia':
            self._validate_eject_vmedia(task, kwargs)
            return
        if method == 'create_subscription':
            self._validate_create_subscription(task, kwargs)
            return
        if method == 'delete_subscription':
            self._validate_delete_subscription(task, kwargs)
            return
        super(RedfishVendorPassthru, self).validate(task, method, **kwargs)

    def _validate_eject_vmedia(self, task, kwargs):
        """Verify that the boot_device input is valid."""

        # If a boot device is provided check that it's valid.
        # It is OK to eject if already ejected
        boot_device = kwargs.get('boot_device')

        if not boot_device:
            return

        system = redfish_utils.get_system(task.node)

        for manager in system.managers:
            for v_media in manager.virtual_media.get_members():
                if boot_device not in v_media.media_types:
                    raise exception.InvalidParameterValue(_(
                        "Boot device %s is not a valid value ") % boot_device)

    @METRICS.timer('RedfishVendorPassthru.eject_vmedia')
    @base.passthru(['POST'],
                   description=_("Eject a virtual media device. If no device "
                                 "is provided then all attached devices will "
                                 "be ejected. "
                                 "Optional arguments: "
                                 "'boot_device' - the boot device to eject, "
                                 "either 'cd', 'dvd', 'usb', or 'floppy'"))
    # @task_manager.require_exclusive_lock
    def eject_vmedia(self, task, **kwargs):
        """Eject a virtual media device.

        :param task: A TaskManager object.
        :param kwargs: The arguments sent with vendor passthru. The optional
            kwargs are::
            'boot_device': the boot device to eject
        """

        # If boot_device not provided all vmedia devices will be ejected
        boot_device = kwargs.get('boot_device')
        redfish_boot.eject_vmedia(task, boot_device)

    def _validate_create_subscription(self, task, kwargs):
        """Verify that the args input are valid."""
        destination = kwargs.get('Destination')
        event_types = kwargs.get('EventTypes')
        # NOTE(iurygregory): Use defaults values from Redfish in case they
        # are not present in the args.
        context = kwargs.get('Context', "")
        protocol = kwargs.get('Protocol', "Redfish")
        http_headers = kwargs.get('HttpHeaders')

        if event_types is not None:
            event_service = redfish_utils.get_event_service(task.node)
            allowed_values = set(
                event_service.get_event_types_for_subscription())
            if not (isinstance(event_types, list)
                    and set(event_types).issubset(allowed_values)):
                raise exception.InvalidParameterValue(
                    _("EventTypes %s is not a valid value, allowed values %s")
                    % (str(event_types), str(allowed_values)))

        # NOTE(iurygregory): check only if they are strings.
        # BMCs will fail to create a subscription if the context, protocol or
        # destination are invalid.
        if not isinstance(context, str):
            raise exception.InvalidParameterValue(
                _("Context %s is not a valid string") % context)
        if not isinstance(protocol, str):
            raise exception.InvalidParameterValue(
                _("Protocol %s is not a string") % protocol)

        # NOTE(iurygregory): if http_headers are None there is no problem,
        # the validation will fail if the value is not None and not a list.
        if http_headers is not None and not isinstance(http_headers, list):
            raise exception.InvalidParameterValue(
                _("HttpHeaders %s is not a list of headers") % http_headers)

        try:
            parsed = rfc3986.uri_reference(destination)
            validator = rfc3986.validators.Validator().require_presence_of(
                'scheme', 'host',
            ).check_validity_of(
                'scheme', 'userinfo', 'host', 'path', 'query', 'fragment',
            )
            try:
                validator.validate(parsed)
            except rfc3986.exceptions.RFC3986Exception:
                # NOTE(iurygregory): raise error because the parsed
                # destination does not contain scheme or authority.
                raise TypeError
        except TypeError:
            raise exception.InvalidParameterValue(
                _("Destination %s is not a valid URI") % destination)

    def _filter_subscription_fields(self, subscription_json):
        filter_subscription = {k: v for k, v in subscription_json.items()
                               if k in SUBSCRIPTION_COMMON_FIELDS}
        return filter_subscription

    @METRICS.timer('RedfishVendorPassthru.create_subscription')
    @base.passthru(['POST'], async_call=False,
                   description=_("Creates a subscription on a node. "
                                 "Required argument: a dictionary of "
                                 "{'Destination': 'destination_url'}"))
    def create_subscription(self, task, **kwargs):
        """Creates a subscription.

        :param task: A TaskManager object.
        :param kwargs: The arguments sent with vendor passthru.
        :raises: RedfishError, if any problem occurs when trying to create
            a subscription.
        """
        payload = {
            'Destination': kwargs.get('Destination'),
            'Protocol': kwargs.get('Protocol', "Redfish"),
            'Context': kwargs.get('Context', ""),
            'EventTypes': kwargs.get('EventTypes', ["Alert"])
        }

        http_headers = kwargs.get('HttpHeaders', [])
        if http_headers:
            payload['HttpHeaders'] = http_headers

        try:
            event_service = redfish_utils.get_event_service(task.node)
            subscription = event_service.subscriptions.create(payload)
            return self._filter_subscription_fields(subscription.json)
        except sushy.exceptions.SushyError as e:
            error_msg = (_('Failed to create subscription on node %(node)s. '
                           'Subscription payload: %(payload)s. '
                           'Error: %(error)s') % {'node': task.node.uuid,
                                                  'payload': str(payload),
                                                  'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

    def _validate_delete_subscription(self, task, kwargs):
        """Verify that the args input are valid."""
        # We can only check if the kwargs contain the id field.

        if not kwargs.get('id'):
            raise exception.InvalidParameterValue(_("id can't be None"))

    @METRICS.timer('RedfishVendorPassthru.delete_subscription')
    @base.passthru(['DELETE'], async_call=False,
                   description=_("Delete a subscription on a node. "
                                 "Required argument: a dictionary of "
                                 "{'id': 'subscription_bmc_id'}"))
    def delete_subscription(self, task, **kwargs):
        """Delete a subscription.

        :param task: A TaskManager object.
        :param kwargs: The arguments sent with vendor passthru.
        :raises: RedfishError, if any problem occurs when trying to delete
            the subscription.
        """
        try:
            event_service = redfish_utils.get_event_service(task.node)
            redfish_subscriptions = event_service.subscriptions
            bmc_id = kwargs.get('id')
            # NOTE(iurygregory): some BMCs doesn't report the last /
            # in the path for the resource, since we will add the ID
            # we need to make sure the separator is present.
            separator = "" if redfish_subscriptions.path[-1] == "/" else "/"

            resource = redfish_subscriptions.path + separator + bmc_id
            subscription = redfish_subscriptions.get_member(resource)
            msg = (_('Sucessfuly deleted subscription %(id)s on node '
                     '%(node)s') % {'id': bmc_id, 'node': task.node.uuid})
            subscription.delete()
            LOG.debug(msg)
        except sushy.exceptions.SushyError as e:
            error_msg = (_('Redfish delete_subscription failed for '
                           'subscription %(id)s on node %(node)s. '
                           'Error: %(error)s') % {'id': bmc_id,
                                                  'node': task.node.uuid,
                                                  'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg, code=404)

    @METRICS.timer('RedfishVendorPassthru.get_subscriptions')
    @base.passthru(['GET'], async_call=False,
                   description=_("Returns all subscriptions on the node."))
    def get_all_subscriptions(self, task, **kwargs):
        """Get all Subscriptions on the node

        :param task: A TaskManager object.
        :param kwargs: Not used.
        :raises: RedfishError, if any problem occurs when retrieving all
            subscriptions.
        """
        try:
            event_service = redfish_utils.get_event_service(task.node)
            subscriptions = event_service.subscriptions.json
            return subscriptions
        except sushy.exceptions.SushyError as e:
            error_msg = (_('Redfish get_subscriptions failed for '
                           'node %(node)s. '
                           'Error: %(error)s') % {'node': task.node.uuid,
                                                  'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)

    @METRICS.timer('RedfishVendorPassthru.get_subscription')
    @base.passthru(['GET'], async_call=False,
                   description=_("Get a subscription on the node. "
                                 "Required argument: a dictionary of "
                                 "{'id': 'subscription_bmc_id'}"))
    def get_subscription(self, task, **kwargs):
        """Get a specific subscription on the node

        :param task: A TaskManager object.
        :param kwargs: The arguments sent with vendor passthru.
        :raises: RedfishError, if any problem occurs when retrieving the
            subscription.
        """
        try:
            event_service = redfish_utils.get_event_service(task.node)
            redfish_subscriptions = event_service.subscriptions
            bmc_id = kwargs.get('id')
            # NOTE(iurygregory): some BMCs doesn't report the last /
            # in the path for the resource, since we will add the ID
            # we need to make sure the separator is present.
            separator = "" if redfish_subscriptions.path[-1] == "/" else "/"
            resource = redfish_subscriptions.path + separator + bmc_id
            subscription = event_service.subscriptions.get_member(resource)
            return self._filter_subscription_fields(subscription.json)
        except sushy.exceptions.SushyError as e:
            error_msg = (_('Redfish get_subscription failed for '
                           'subscription %(id)s on node %(node)s. '
                           'Error: %(error)s') % {'id': bmc_id,
                                                  'node': task.node.uuid,
                                                  'error': e})
            LOG.error(error_msg)
            raise exception.RedfishError(error=error_msg)
