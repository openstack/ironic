# Copyright (2015-2017) Hewlett Packard Enterprise Development LP
# Copyright (2015-2017) Universidade Federal de Campina Grande
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

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy_utils

client_exception = importutils.try_import('hpOneView.exceptions')

LOG = logging.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)

BOOT_DEVICE_MAP_ONEVIEW = {
    boot_devices.CDROM: 'CD',
    boot_devices.DISK: 'HardDisk',
    boot_devices.PXE: 'PXE'
}

BOOT_DEVICE_MAP_ONEVIEW_REV = {
    v: k for k, v in BOOT_DEVICE_MAP_ONEVIEW.items()}

BOOT_DEVICE_MAP_ILO = {
    boot_devices.CDROM: 'Cd',
    boot_devices.DISK: 'Hdd',
    boot_devices.PXE: 'Pxe'
}

BOOT_DEVICE_MAP_ILO_REV = {
    v: k for k, v in BOOT_DEVICE_MAP_ILO.items()}

ILO_SYSTEM_PATH = "/rest/v1/Systems/1"

ILO_REQUEST_HEADERS = {"Content-Type": "application/json"}


def set_onetime_boot(task):
    """Set onetime boot to server hardware.

    Change the onetime boot option of an OneView server hardware.

    :param task: a task from TaskManager.
    """
    driver_internal_info = task.node.driver_internal_info
    next_boot_device = driver_internal_info.get('next_boot_device')

    if not next_boot_device:
        return

    boot_device = next_boot_device.get('boot_device')
    persistent = next_boot_device.get('persistent')

    if persistent:
        return

    server_hardware = task.node.driver_info.get('server_hardware_uri')
    ilo_client = common.get_ilorest_client(server_hardware)
    boot_device = BOOT_DEVICE_MAP_ILO.get(boot_device)
    body = {
        "Boot": {
            "BootSourceOverrideTarget": boot_device,
            "BootSourceOverrideEnabled": "Once"
        }
    }
    try:
        ilo_client.patch(path=ILO_SYSTEM_PATH, body=body,
                         headers=ILO_REQUEST_HEADERS)
    except Exception as e:
        msg = (_("Error while trying to set onetime boot on Server Hardware: "
                 "%(sh_uri)s. Error: %(error)s") %
               {'sh_uri': server_hardware, 'error': e})
        raise exception.OneViewError(error=msg)


def _is_onetime_boot(task):
    """Check onetime boot from server hardware.

    Check if the onetime boot option of an OneView server hardware
    is set to 'Once' in iLO.

    :param task: a task from TaskManager.
    :returns: Boolean value. True if onetime boot is 'Once'
              False otherwise.
    """
    server_hardware = task.node.driver_info.get('server_hardware_uri')
    ilo_client = common.get_ilorest_client(server_hardware)
    response = ilo_client.get(path=ILO_SYSTEM_PATH,
                              headers=ILO_REQUEST_HEADERS)
    onetime_boot = None
    boot = response.dict.get('Boot', {})
    if boot:
        onetime_boot = boot.get('BootSourceOverrideEnabled')
    return onetime_boot == 'Once'


def set_boot_device(task):
    """Sets the boot device for a node.

    Sets the boot device to use on next reboot of the node.

    :param task: a task from TaskManager.
    :raises: InvalidParameterValue if an invalid boot device is
             specified.
    :raises: OneViewError if the communication with OneView fails
    """
    oneview_client = common.get_hponeview_client()
    common.ensure_server_profile(task)
    driver_internal_info = task.node.driver_internal_info
    next_boot_device = driver_internal_info.get('next_boot_device')

    if next_boot_device:
        boot_device = next_boot_device.get('boot_device')
        persistent = next_boot_device.get('persistent')

        if boot_device not in sorted(BOOT_DEVICE_MAP_ONEVIEW):
            raise exception.InvalidParameterValue(
                _("Invalid boot device %s specified.") % boot_device)

        LOG.debug("Setting boot device to %(boot_device)s and "
                  "persistent to %(persistent)s for node %(node)s",
                  {"boot_device": boot_device, "persistent": persistent,
                   "node": task.node.uuid})

        profile = task.node.driver_info.get('applied_server_profile_uri')
        boot_device = BOOT_DEVICE_MAP_ONEVIEW.get(boot_device)

        try:
            server_profile = oneview_client.server_profiles.get(profile)
            boot = server_profile.get('boot', {})
            order = boot.get('order', [])
            if boot_device in order:
                order.remove(boot_device)
            order.insert(0, boot_device)
            boot['order'] = order
            server_profile['boot'] = boot
            oneview_client.server_profiles.update(server_profile, profile)
            set_onetime_boot(task)
            driver_internal_info.pop('next_boot_device', None)
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
        except client_exception.HPOneViewException as oneview_exc:
            msg = (_(
                "Error setting boot device on OneView. Error: %s")
                % oneview_exc
            )
            raise exception.OneViewError(error=msg)

    else:
        LOG.debug("Not going to set boot device because there is no "
                  "'next_boot_device' on driver_internal_info "
                  "for the %(node)s",
                  {"node": task.node.uuid})


class OneViewManagement(base.ManagementInterface):

    # NOTE(TheJulia): Marking as unsupported as 3rd party CI was taken down
    # shortly before the beginning of the Rocky cycle, and no replies have
    # indicated that 3rd party CI will be re-established nor visible
    # actions observed regarding re-establishing 3rd party CI.
    # TODO(TheJulia): This should be expected to be removed in Stein.
    supported = False

    def get_properties(self):
        return deploy_utils.get_properties()

    @METRICS.timer('OneViewManagement.validate')
    def validate(self, task):
        """Checks required info on 'driver_info' and validates node for OneView

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required info such as server_hardware_uri,
        server_hardware_type, server_profile_template_uri and
        enclosure_group_uri. Also, checks if the server profile of the node is
        applied, if NICs are valid for the server profile of the node, and if
        the server hardware attributes (ram, memory, vcpus count) are
        consistent with OneView.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue if parameters set are inconsistent with
                 resources in OneView
        """

        common.verify_node_info(task.node)

        try:
            common.validate_oneview_resources_compatibility(task)

            if not deploy_utils.is_node_in_use_by_ironic(task.node):
                raise exception.InvalidParameterValue(
                    _("Node %s is not in use by ironic.") % task.node.uuid)
        except exception.OneViewError as oneview_exc:
            raise exception.InvalidParameterValue(oneview_exc)

    @METRICS.timer('OneViewManagement.get_supported_boot_devices')
    def get_supported_boot_devices(self, task):
        """Gets a list of the supported boot devices.

        :param task: a task from TaskManager.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.
        """

        return sorted(BOOT_DEVICE_MAP_ONEVIEW)

    @METRICS.timer('OneViewManagement.set_boot_device')
    @task_manager.require_exclusive_lock
    @common.node_has_server_profile
    def set_boot_device(self, task, device, persistent=False):
        """Set the next boot device to the node.

        Sets the boot device to the node next_boot_device on
        driver_internal_info namespace. The operation will be
        performed before the next node power on.

        :param task: a task from TaskManager.
        :param device: the boot device, one of the supported devices
                       listed in :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue if an invalid boot device is
                 specified.
        """
        if device not in self.get_supported_boot_devices(task):
            raise exception.InvalidParameterValue(
                _("Invalid boot device %s specified.") % device)

        driver_internal_info = task.node.driver_internal_info
        next_boot_device = {'boot_device': device,
                            'persistent': persistent}
        driver_internal_info['next_boot_device'] = next_boot_device
        task.node.driver_internal_info = driver_internal_info
        task.node.save()
        LOG.debug("The 'next_boot_device' flag was updated on "
                  "driver_internal_info with device=%(boot_device)s "
                  "and persistent=%(persistent)s for the node "
                  "%(node)s",
                  {"boot_device": device, "persistent": persistent,
                   "node": task.node.uuid})

    @METRICS.timer('OneViewManagement.get_boot_device')
    @common.node_has_server_profile
    def get_boot_device(self, task):
        """Get the current boot device from the node.

        Gets the boot device from the node 'next_boot_device on
        driver_internal_info namespace if exists. Gets through
        a request to OneView otherwise.

        :param task: a task from TaskManager.
        :returns: a dictionary containing:
            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` [PXE, DISK, CDROM]
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.
        :raises: InvalidParameterValue if the boot device is unknown
        :raises: OneViewError if the communication with OneView fails
        """
        oneview_client = common.get_hponeview_client()
        driver_internal_info = task.node.driver_internal_info
        next_boot_device = driver_internal_info.get('next_boot_device')

        if next_boot_device:
            return next_boot_device

        driver_info = task.node.driver_info
        server_profile = driver_info.get('applied_server_profile_uri')

        try:
            profile = oneview_client.server_profiles.get(server_profile)
            primary_device = None
            boot = profile.get('boot', {})
            boot_order = boot.get('order', [])
            if boot_order:
                primary_device = boot_order[0]
        except client_exception.HPOneViewException as exc:
            msg = _("Error on node: %(node)s while getting Server Profile: "
                    "%(profile)s of the from OneView. Error: %(error)s.") % {
                        'profile': server_profile,
                        'node': task.node.uuid,
                        'error': exc
            }
            raise exception.OneViewError(msg)

        if primary_device not in BOOT_DEVICE_MAP_ONEVIEW_REV:
            raise exception.InvalidParameterValue(
                _("Unsupported boot device %(device)s for node: %(node)s")
                % {"device": primary_device, "node": task.node.uuid}
            )

        boot_device = {
            'boot_device': BOOT_DEVICE_MAP_ONEVIEW_REV.get(primary_device),
            'persistent': not _is_onetime_boot(task)
        }

        return boot_device

    @METRICS.timer('OneViewManagement.get_sensors_data')
    def get_sensors_data(self, task):
        """Get sensors data.

        Not implemented by this driver.
        :param task: a TaskManager instance.
        """
        raise NotImplementedError()
