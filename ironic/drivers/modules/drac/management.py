# -*- coding: utf-8 -*-
#
# Copyright 2014 Red Hat, Inc.
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

"""
DRAC Management Driver
"""

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _LE
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.drac import client as drac_client
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import resource_uris

pywsman = importutils.try_import('pywsman')

LOG = logging.getLogger(__name__)

_BOOT_DEVICES_MAP = {
    boot_devices.DISK: 'HardDisk',
    boot_devices.PXE: 'NIC',
    boot_devices.CDROM: 'Optical',
}

TARGET_DEVICE = 'BIOS.Setup.1-1'

# RebootJobType constants

_GRACEFUL_REBOOT_WITH_FORCED_SHUTDOWN = '3'

# IsNext constants

PERSISTENT = '1'
""" Is the next boot config the system will use. """

ONE_TIME_BOOT = '3'
""" Is the next boot config the system will use, one time boot only. """


def _get_boot_device(node, controller_version=None):
    if controller_version is None:
        controller_version = _get_lifecycle_controller_version(node)

    boot_list = _get_next_boot_list(node)
    persistent = boot_list['is_next'] == PERSISTENT
    boot_list_id = boot_list['instance_id']

    boot_device_id = _get_boot_device_for_boot_list(node, boot_list_id,
                                                    controller_version)
    boot_device = next((key for (key, value) in _BOOT_DEVICES_MAP.items()
                        if value in boot_device_id), None)
    return {'boot_device': boot_device, 'persistent': persistent}


def _get_next_boot_list(node):
    """Get the next boot list.

    The DCIM_BootConfigSetting resource represents each boot list (eg.
    IPL/BIOS, BCV, UEFI, vFlash Partition, One Time Boot).
    The DCIM_BootSourceSetting resource represents each of the boot list boot
    devices or sources that are shown under their corresponding boot list.

    :param node: an ironic node object.
    :raises: DracClientError on an error from pywsman library.
    :returns: a dictionary containing:

        :instance_id: the instance id of the boot list.
        :is_next: whether it's the next device to boot or not. One of
                  PERSISTENT, ONE_TIME_BOOT constants.
    """
    client = drac_client.get_wsman_client(node)
    filter_query = ('select * from DCIM_BootConfigSetting where IsNext=%s '
                    'or IsNext=%s' % (PERSISTENT, ONE_TIME_BOOT))
    try:
        doc = client.wsman_enumerate(resource_uris.DCIM_BootConfigSetting,
                                     filter_query=filter_query)
    except exception.DracClientError as exc:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE('DRAC driver failed to get next boot mode for '
                          'node %(node_uuid)s. Reason: %(error)s.'),
                      {'node_uuid': node.uuid, 'error': exc})

    items = drac_common.find_xml(doc, 'DCIM_BootConfigSetting',
                                 resource_uris.DCIM_BootConfigSetting,
                                 find_all=True)

    # This list will have 2 items maximum, one for the persistent element
    # and another one for the OneTime if set
    boot_list = None
    for i in items:
        boot_list_id = drac_common.find_xml(
            i, 'InstanceID', resource_uris.DCIM_BootConfigSetting).text
        is_next = drac_common.find_xml(
            i, 'IsNext', resource_uris.DCIM_BootConfigSetting).text

        boot_list = {'instance_id': boot_list_id, 'is_next': is_next}
        # If OneTime is set we should return it, because that's
        # where the next boot device is
        if is_next == ONE_TIME_BOOT:
            break

    return boot_list


def _get_boot_device_for_boot_list(node, boot_list_id, controller_version):
    """Get the next boot device for a given boot list.

    The DCIM_BootConfigSetting resource represents each boot list (eg.
    IPL/BIOS, BCV, UEFI, vFlash Partition, One Time Boot).
    The DCIM_BootSourceSetting resource represents each of the boot list boot
    devices or sources that are shown under their corresponding boot list.

    :param node: ironic node object.
    :param boot_list_id: boot list id.
    :param controller_version: version of the Lifecycle controller.
    :raises: DracClientError on an error from pywsman library.
    :returns: boot device id.
    """
    client = drac_client.get_wsman_client(node)

    if controller_version < '2.0.0':
        filter_query = ('select * from DCIM_BootSourceSetting where '
                        'PendingAssignedSequence=0')
    else:
        filter_query = ('select * from DCIM_BootSourceSetting where '
                        'PendingAssignedSequence=0 and '
                        'BootSourceType="%s"' % boot_list_id)
    try:
        doc = client.wsman_enumerate(resource_uris.DCIM_BootSourceSetting,
                                     filter_query=filter_query)
    except exception.DracClientError as exc:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE('DRAC driver failed to get the current boot '
                          'device for node %(node_uuid)s. '
                          'Reason: %(error)s.'),
                      {'node_uuid': node.uuid, 'error': exc})

    if controller_version < '2.0.0':
        boot_devices = drac_common.find_xml(
            doc, 'InstanceID', resource_uris.DCIM_BootSourceSetting,
            find_all=True)
        for device in boot_devices:
            if device.text.startswith(boot_list_id):
                boot_device_id = device.text
                break
    else:
        boot_device_id = drac_common.find_xml(
            doc, 'InstanceID', resource_uris.DCIM_BootSourceSetting).text

    return boot_device_id


def _get_boot_list_for_boot_device(node, device, controller_version):
    """Get the boot list for a given boot device.

    The DCIM_BootConfigSetting resource represents each boot list (eg.
    IPL/BIOS, BCV, UEFI, vFlash Partition, One Time Boot).
    The DCIM_BootSourceSetting resource represents each of the boot list boot
    devices or sources that are shown under their corresponding boot list.

    :param node: ironic node object.
    :param device: boot device.
    :param controller_version: version of the Lifecycle controller.
    :raises: DracClientError on an error from pywsman library.
    :returns: dictionary containing:

        :boot_list: boot list.
        :boot_device_id: boot device id.
    """
    client = drac_client.get_wsman_client(node)

    if controller_version < '2.0.0':
        filter_query = None
    else:
        filter_query = ("select * from DCIM_BootSourceSetting where "
                        "InstanceID like '%%#%s%%'" %
                        _BOOT_DEVICES_MAP[device])

    try:
        doc = client.wsman_enumerate(resource_uris.DCIM_BootSourceSetting,
                                     filter_query=filter_query)
    except exception.DracClientError as exc:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE('DRAC driver failed to set the boot device '
                          'for node %(node_uuid)s. Can\'t find the ID '
                          'for the %(device)s type. Reason: %(error)s.'),
                      {'node_uuid': node.uuid, 'error': exc,
                       'device': device})

    if controller_version < '2.0.0':
        boot_devices = drac_common.find_xml(
            doc, 'InstanceID', resource_uris.DCIM_BootSourceSetting,
            find_all=True)
        for boot_device in boot_devices:
            if _BOOT_DEVICES_MAP[device] in boot_device.text:
                boot_device_id = boot_device.text
                boot_list = boot_device_id.split(':')[0]
                break
    else:
        boot_device_id = drac_common.find_xml(
            doc, 'InstanceID', resource_uris.DCIM_BootSourceSetting).text
        boot_list = drac_common.find_xml(
            doc, 'BootSourceType', resource_uris.DCIM_BootSourceSetting).text

    return {'boot_list': boot_list, 'boot_device_id': boot_device_id}


def create_config_job(node, reboot=False):
    """Create a configuration job.

    This method is used to apply the pending values created by
    set_boot_device().

    :param node: an ironic node object.
    :raises: DracClientError if the client received unexpected response.
    :raises: DracOperationFailed if the client received response with an
             error message.
    :raises: DracUnexpectedReturnValue if the client received a response
             with unexpected return value.
    """
    client = drac_client.get_wsman_client(node)
    selectors = {'CreationClassName': 'DCIM_BIOSService',
                 'Name': 'DCIM:BIOSService',
                 'SystemCreationClassName': 'DCIM_ComputerSystem',
                 'SystemName': 'DCIM:ComputerSystem'}
    properties = {'Target': TARGET_DEVICE,
                  'ScheduledStartTime': 'TIME_NOW'}

    if reboot:
        properties['RebootJobType'] = _GRACEFUL_REBOOT_WITH_FORCED_SHUTDOWN

    try:
        client.wsman_invoke(resource_uris.DCIM_BIOSService,
                            'CreateTargetedConfigJob', selectors, properties,
                            drac_client.RET_CREATED)
    except exception.DracRequestFailed as exc:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE('DRAC driver failed to create config job for node '
                          '%(node_uuid)s. The changes are not applied. '
                          'Reason: %(error)s.'),
                      {'node_uuid': node.uuid, 'error': exc})


def check_for_config_job(node):
    """Check if a configuration job is already created.

    :param node: an ironic node object.
    :raises: DracClientError on an error from pywsman library.
    :raises: DracPendingConfigJobExists if the job is already created.

    """
    client = drac_client.get_wsman_client(node)
    try:
        doc = client.wsman_enumerate(resource_uris.DCIM_LifecycleJob)
    except exception.DracClientError as exc:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE('DRAC driver failed to list the configuration jobs '
                          'for node %(node_uuid)s. Reason: %(error)s.'),
                      {'node_uuid': node.uuid, 'error': exc})

    items = drac_common.find_xml(doc, 'DCIM_LifecycleJob',
                                 resource_uris.DCIM_LifecycleJob,
                                 find_all=True)
    for i in items:
        name = drac_common.find_xml(i, 'Name', resource_uris.DCIM_LifecycleJob)
        if TARGET_DEVICE not in name.text:
            continue

        job_status = drac_common.find_xml(
            i, 'JobStatus', resource_uris.DCIM_LifecycleJob).text
        # If job is already completed or failed we can
        # create another one.
        # The 'Completed with Errors' JobStatus can be returned by
        # configuration jobs that set NIC or BIOS attributes.
        # Job Control Documentation: http://goo.gl/o1dDD3 (Section 7.2.3.2)
        if job_status.lower() not in ('completed', 'completed with errors',
                                      'failed'):
            job_id = drac_common.find_xml(i, 'InstanceID',
                                          resource_uris.DCIM_LifecycleJob).text
            raise exception.DracPendingConfigJobExists(job_id=job_id,
                                                       target=TARGET_DEVICE)


def _get_lifecycle_controller_version(node):
    """Returns the Lifecycle controller version of the DRAC card of the node

    :param node: the node.
    :returns: the Lifecycle controller version.
    :raises: DracClientError if the client received unexpected response.
    :raises: InvalidParameterValue if required DRAC credentials are missing.
    """
    client = drac_client.get_wsman_client(node)
    filter_query = ('select LifecycleControllerVersion from DCIM_SystemView')
    try:
        doc = client.wsman_enumerate(resource_uris.DCIM_SystemView,
                                     filter_query=filter_query)
    except exception.DracClientError as exc:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE('DRAC driver failed to get power state for node '
                          '%(node_uuid)s. Reason: %(error)s.'),
                      {'node_uuid': node.uuid, 'error': exc})

    version = drac_common.find_xml(doc, 'LifecycleControllerVersion',
                                   resource_uris.DCIM_SystemView).text
    return version


class DracManagement(base.ManagementInterface):

    def get_properties(self):
        return drac_common.COMMON_PROPERTIES

    def validate(self, task):
        """Validate the driver-specific info supplied.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        manage the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if required driver_info attribute
                 is missing or invalid on the node.

        """
        return drac_common.parse_driver_info(task.node)

    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.

        """
        return list(_BOOT_DEVICES_MAP.keys())

    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device, one of
                       :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: DracClientError if the client received unexpected response.
        :raises: DracOperationFailed if the client received response with an
                 error message.
        :raises: DracUnexpectedReturnValue if the client received a response
                 with unexpected return value.
        :raises: InvalidParameterValue if an invalid boot device is
                 specified.
        :raises: DracPendingConfigJobExists on an error when creating the job.

        """

        client = drac_client.get_wsman_client(task.node)
        controller_version = _get_lifecycle_controller_version(task.node)
        current_boot_device = _get_boot_device(task.node, controller_version)

        # If we are already booting from the right device, do nothing.
        if current_boot_device == {'boot_device': device,
                                   'persistent': persistent}:
            LOG.debug('DRAC already set to boot from %s', device)
            return

        # Check for an existing configuration job
        check_for_config_job(task.node)

        # Querying the boot device attributes
        boot_device = _get_boot_list_for_boot_device(task.node, device,
                                                     controller_version)
        boot_list = boot_device['boot_list']
        boot_device_id = boot_device['boot_device_id']

        if not persistent:
            boot_list = 'OneTime'

        # Send the request to DRAC
        selectors = {'InstanceID': boot_list}
        properties = {'source': boot_device_id}
        try:
            client.wsman_invoke(resource_uris.DCIM_BootConfigSetting,
                                'ChangeBootOrderByInstanceID', selectors,
                                properties, drac_client.RET_SUCCESS)
        except exception.DracRequestFailed as exc:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('DRAC driver failed to set the boot device for '
                              'node %(node_uuid)s to %(target_boot_device)s. '
                              'Reason: %(error)s.'),
                          {'node_uuid': task.node.uuid,
                           'target_boot_device': device,
                           'error': exc})

        # Create a configuration job
        create_config_job(task.node)

    def get_boot_device(self, task):
        """Get the current boot device for a node.

        Returns the current boot device of the node.

        :param task: a task from TaskManager.
        :raises: DracClientError on an error from pywsman library.
        :returns: a dictionary containing:

            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.

        """
        return _get_boot_device(task.node)

    def get_sensors_data(self, task):
        """Get sensors data.

        :param task: a TaskManager instance.
        :raises: FailedToGetSensorData when getting the sensor data fails.
        :raises: FailedToParseSensorData when parsing sensor data fails.
        :returns: returns a consistent format dict of sensor data grouped by
                  sensor type, which can be processed by Ceilometer.

        """
        raise NotImplementedError()
