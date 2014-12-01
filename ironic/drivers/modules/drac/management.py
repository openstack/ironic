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

from oslo.utils import excutils
from oslo.utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import resource_uris
from ironic.openstack.common import log as logging

pywsman = importutils.try_import('pywsman')

LOG = logging.getLogger(__name__)

_BOOT_DEVICES_MAP = {
    boot_devices.DISK: 'HardDisk',
    boot_devices.PXE: 'NIC',
    boot_devices.CDROM: 'Optical',
}

# IsNext constants

PERSISTENT = '1'
""" Is the next boot config the system will use. """

NOT_NEXT = '2'
""" Is not the next boot config the system will use. """

ONE_TIME_BOOT = '3'
""" Is the next boot config the system will use, one time boot only. """


def _get_next_boot_mode(node):
    """Get the next boot mode.

    To see a list of supported boot modes see: http://goo.gl/aEsvUH
    (Section 7.2)

    :param node: an ironic node object.
    :raises: DracClientError on an error from pywsman library.
    :returns: a dictionary containing:

        :instance_id: the instance id of the boot device.
        :is_next: whether it's the next device to boot or not. One of
                  PERSISTENT, NOT_NEXT, ONE_TIME_BOOT constants.

    """
    client = drac_common.get_wsman_client(node)
    options = pywsman.ClientOptions()
    filter_query = ('select * from DCIM_BootConfigSetting where IsNext=%s '
                    'or IsNext=%s' % (PERSISTENT, ONE_TIME_BOOT))
    try:
        doc = client.wsman_enumerate(resource_uris.DCIM_BootConfigSetting,
                                      options, filter_query=filter_query)
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
    boot_mode = None
    for i in items:
        instance_id = drac_common.find_xml(i, 'InstanceID',
                                     resource_uris.DCIM_BootConfigSetting).text
        is_next = drac_common.find_xml(i, 'IsNext',
                                     resource_uris.DCIM_BootConfigSetting).text

        boot_mode = {'instance_id': instance_id, 'is_next': is_next}
        # If OneTime is set we should return it, because that's
        # where the next boot device is
        if is_next == ONE_TIME_BOOT:
            break

    return boot_mode


def _create_config_job(node):
    """Create a configuration job.

    This method is used to apply the pending values created by
    set_boot_device().

    :param node: an ironic node object.
    :raises: DracClientError on an error from pywsman library.
    :raises: DracConfigJobCreationError on an error when creating the job.

    """
    client = drac_common.get_wsman_client(node)
    options = pywsman.ClientOptions()
    options.add_selector('CreationClassName', 'DCIM_BIOSService')
    options.add_selector('Name', 'DCIM:BIOSService')
    options.add_selector('SystemCreationClassName', 'DCIM_ComputerSystem')
    options.add_selector('SystemName', 'DCIM:ComputerSystem')
    options.add_property('Target', 'BIOS.Setup.1-1')
    options.add_property('ScheduledStartTime', 'TIME_NOW')
    doc = client.wsman_invoke(resource_uris.DCIM_BIOSService,
                              options, 'CreateTargetedConfigJob')
    return_value = drac_common.find_xml(doc, 'ReturnValue',
                                        resource_uris.DCIM_BIOSService).text
    # NOTE(lucasagomes): Possible return values are: RET_ERROR for error
    #                    or RET_CREATED job created (but changes will be
    #                    applied after the reboot)
    # Boot Management Documentation: http://goo.gl/aEsvUH (Section 8.4)
    if return_value == drac_common.RET_ERROR:
        error_message = drac_common.find_xml(doc, 'Message',
                                           resource_uris.DCIM_BIOSService).text
        raise exception.DracConfigJobCreationError(error=error_message)


def _check_for_config_job(node):
    """Check if a configuration job is already created.

    :param node: an ironic node object.
    :raises: DracClientError on an error from pywsman library.
    :raises: DracConfigJobCreationError if the job is already created.

    """
    client = drac_common.get_wsman_client(node)
    options = pywsman.ClientOptions()
    try:
        doc = client.wsman_enumerate(resource_uris.DCIM_LifecycleJob, options)
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
        if 'BIOS.Setup.1-1' not in name.text:
            continue

        job_status = drac_common.find_xml(i, 'JobStatus',
                                      resource_uris.DCIM_LifecycleJob).text
        # If job is already completed or failed we can
        # create another one.
        # Job Control Documentation: http://goo.gl/o1dDD3 (Section 7.2.3.2)
        if job_status.lower() not in ('completed', 'failed'):
            job_id = drac_common.find_xml(i, 'InstanceID',
                                      resource_uris.DCIM_LifecycleJob).text
            reason = (_('Another job with ID "%s" is already created '
                        'to configure the BIOS. Wait until existing job '
                        'is completed or is cancelled') % job_id)
            raise exception.DracConfigJobCreationError(error=reason)


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

    def get_supported_boot_devices(self):
        """Get a list of the supported boot devices.

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
        :raises: DracClientError on an error from pywsman library.
        :raises: InvalidParameterValue if an invalid boot device is
                 specified.
        :raises: DracConfigJobCreationError on an error when creating the job.

        """
        # Check for an existing configuration job
        _check_for_config_job(task.node)

        client = drac_common.get_wsman_client(task.node)
        options = pywsman.ClientOptions()
        filter_query = ("select * from DCIM_BootSourceSetting where "
                        "InstanceID like '%%#%s%%'" %
                        _BOOT_DEVICES_MAP[device])
        try:
            doc = client.wsman_enumerate(resource_uris.DCIM_BootSourceSetting,
                                          options, filter_query=filter_query)
        except exception.DracClientError as exc:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('DRAC driver failed to set the boot device '
                              'for node %(node_uuid)s. Can\'t find the ID '
                              'for the %(device)s type. Reason: %(error)s.'),
                          {'node_uuid': task.node.uuid, 'error': exc,
                           'device': device})

        instance_id = drac_common.find_xml(doc, 'InstanceID',
                                     resource_uris.DCIM_BootSourceSetting).text

        source = 'OneTime'
        if persistent:
            source = drac_common.find_xml(doc, 'BootSourceType',
                                     resource_uris.DCIM_BootSourceSetting).text

        # NOTE(lucasagomes): Don't ask me why 'BootSourceType' is set
        # for 'InstanceID' and 'InstanceID' is set for 'source'! You
        # know enterprisey...
        options = pywsman.ClientOptions()
        options.add_selector('InstanceID', source)
        options.add_property('source', instance_id)
        doc = client.wsman_invoke(resource_uris.DCIM_BootConfigSetting,
                                     options, 'ChangeBootOrderByInstanceID')
        return_value = drac_common.find_xml(doc, 'ReturnValue',
                                     resource_uris.DCIM_BootConfigSetting).text
        # NOTE(lucasagomes): Possible return values are: RET_ERROR for error,
        #                    RET_SUCCESS for success or RET_CREATED job
        #                    created (but changes will be applied after
        #                    the reboot)
        # Boot Management Documentation: http://goo.gl/aEsvUH (Section 8.7)
        if return_value == drac_common.RET_ERROR:
            error_message = drac_common.find_xml(doc, 'Message',
                                     resource_uris.DCIM_BootConfigSetting).text
            raise exception.DracOperationError(operation='set_boot_device',
                                               error=error_message)
        # Create a configuration job
        _create_config_job(task.node)

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
        client = drac_common.get_wsman_client(task.node)
        boot_mode = _get_next_boot_mode(task.node)

        persistent = boot_mode['is_next'] == PERSISTENT
        instance_id = boot_mode['instance_id']

        options = pywsman.ClientOptions()
        filter_query = ('select * from DCIM_BootSourceSetting where '
                        'PendingAssignedSequence=0 and '
                        'BootSourceType="%s"' % instance_id)
        try:
            doc = client.wsman_enumerate(resource_uris.DCIM_BootSourceSetting,
                                         options, filter_query=filter_query)
        except exception.DracClientError as exc:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('DRAC driver failed to get the current boot '
                              'device for node %(node_uuid)s. '
                              'Reason: %(error)s.'),
                          {'node_uuid': task.node.uuid, 'error': exc})

        instance_id = drac_common.find_xml(doc, 'InstanceID',
                                     resource_uris.DCIM_BootSourceSetting).text
        boot_device = next((key for (key, value) in _BOOT_DEVICES_MAP.items()
                            if value in instance_id), None)
        return {'boot_device': boot_device, 'persistent': persistent}

    def get_sensors_data(self, task):
        """Get sensors data.

        :param task: a TaskManager instance.
        :raises: FailedToGetSensorData when getting the sensor data fails.
        :raises: FailedToParseSensorData when parsing sensor data fails.
        :returns: returns a consistent format dict of sensor data grouped by
                  sensor type, which can be processed by Ceilometer.

        """
        raise NotImplementedError()
