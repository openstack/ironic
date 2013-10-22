# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright 2013 International Business Machines Corporation
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
Ironic Native IPMI power manager.
"""

from oslo.config import cfg

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.openstack.common import log as logging
from pyghmi import exceptions as pyghmi_exception
from pyghmi.ipmi import command as ipmi_command

opts = [
    cfg.IntOpt('native_ipmi_waiting_time',
               default=10,
               help='Maximum time to retry Native IPMI operations'),
    ]

CONF = cfg.CONF
CONF.register_opts(opts)

LOG = logging.getLogger(__name__)


def _parse_driver_info(node):
    """Gets the bmc access info for the given node.
    :raises: InvalidParameterValue when required ipmi credentials
              are missing.
    """

    info = node.get('driver_info', {})
    bmc_info = {}
    bmc_info['address'] = info.get('ipmi_address')
    bmc_info['username'] = info.get('ipmi_username')
    bmc_info['password'] = info.get('ipmi_password')

    # address, username and password must be present
    missing_info = [key for key in bmc_info if not bmc_info[key]]
    if missing_info:
        raise exception.InvalidParameterValue(_(
            "The following IPMI credentials are not supplied"
            " to IPMI driver: %s."
             ) % missing_info)

    # get additonal info
    bmc_info['uuid'] = node.get('uuid')

    return bmc_info


def _power_on(driver_info):
    """Turn the power on for this node.

    :param driver_info: the bmc access info for a node.
    :returns: power state POWER_ON, one of :class:`ironic.common.states`.
    :raises: IPMIFailure when the native ipmi call fails.
    :raises: PowerStateFailure when invalid power state is returned
             from ipmi.
    """

    msg = _("IPMI power on failed for node %(node_id)s with the "
            "following error: %(error)s")
    try:
        ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                           userid=driver_info['username'],
                           password=driver_info['password'])
        wait = CONF.native_ipmi_waiting_time
        ret = ipmicmd.set_power('on', wait)
    except pyghmi_exception.IpmiException as e:
        LOG.warning(msg % {'node_id': driver_info['uuid'], 'error': str(e)})
        raise exception.IPMIFailure(cmd=str(e))

    state = ret.get('powerstate')
    if state == 'on':
        return states.POWER_ON
    else:
        LOG.warning(msg % {'node_id': driver_info['uuid'], 'error': ret})
        raise exception.PowerStateFailure(pstate=state)


def _power_off(driver_info):
    """Turn the power off for this node.

    :param driver_info: the bmc access info for a node.
    :returns: power state POWER_OFF, one of :class:`ironic.common.states`.
    :raises: IPMIFailure when the native ipmi call fails.
    :raises: PowerStateFailure when invalid power state is returned
             from ipmi.
    """

    msg = _("IPMI power off failed for node %(node_id)s with the "
            "following error: %(error)s")
    try:
        ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                           userid=driver_info['username'],
                           password=driver_info['password'])
        wait = CONF.native_ipmi_waiting_time
        ret = ipmicmd.set_power('off', wait)
    except pyghmi_exception.IpmiException as e:
        LOG.warning(msg % {'node_id': driver_info['uuid'], 'error': str(e)})
        raise exception.IPMIFailure(cmd=str(e))

    state = ret.get('powerstate')
    if state == 'off':
        return states.POWER_OFF
    else:
        LOG.warning(msg % {'node_id': driver_info['uuid'], 'error': ret})
        raise exception.PowerStateFailure(pstate=state)


def _reboot(driver_info):
    """Reboot this node.

    If the power is off, turn it on. If the power is on, reset it.

    :param driver_info: the bmc access info for a node.
    :returns: power state POWER_ON, one of :class:`ironic.common.states`.
    :raises: IPMIFailure when the native ipmi call fails.
    :raises: PowerStateFailure when invalid power state is returned
             from ipmi.
    """

    msg = _("IPMI power reboot failed for node %(node_id)s with the "
            "following error: %(error)s")
    try:
        ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                           userid=driver_info['username'],
                           password=driver_info['password'])
        wait = CONF.native_ipmi_waiting_time
        ret = ipmicmd.set_power('boot', wait)
    except pyghmi_exception.IpmiException as e:
        LOG.warning(msg % {'node_id': driver_info['uuid'], 'error': str(e)})
        raise exception.IPMIFailure(cmd=str(e))

    state = ret.get('powerstate')
    if state == 'on':
        return states.POWER_ON
    else:
        LOG.warning(msg % {'node_id': driver_info['uuid'], 'error': ret})
        raise exception.PowerStateFailure(pstate=state)


def _power_status(driver_info):
    """Get the power status for this node.

    :param driver_info: the bmc access info for a node.
    :returns: power state POWER_ON, POWER_OFF or ERROR defined in
             :class:`ironic.common.states`.
    :raises: IPMIFailure when the native ipmi call fails.
    """

    try:
        ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                           userid=driver_info['username'],
                           password=driver_info['password'])
        ret = ipmicmd.get_power()
    except pyghmi_exception.IpmiException as e:
        LOG.warning(_("IPMI get power state failed for node %(node_id)s "
                      "with the following error: %(error)s")
                    % {'node_id': driver_info['uuid'], 'error': str(e)})
        raise exception.IPMIFailure(cmd=str(e))

    state = ret.get('powerstate')
    if state == 'on':
        return states.POWER_ON
    elif state == 'off':
        return states.POWER_OFF
    else:
        # NOTE(linggao): Do not throw an exception here because it might
        # return other valid values. It is up to the caller to decide
        # what to do.
        LOG.warning(_("IPMI get power state for node %(node_id)s returns the  "
                      "following details: %(detail)s")
                    % {'node_id': driver_info['uuid'], 'detail': ret})
        return states.ERROR


class NativeIPMIPower(base.PowerInterface):
    """The power driver using native python-ipmi library."""

    def validate(self, node):
        """Check that node['driver_info'] contains IPMI credentials.

        :param node: a single node to validate.
        :raises: InvalidParameterValue when required ipmi credentials
                 are missing.
        """
        _parse_driver_info(node)

    def get_power_state(self, task, node):
        """Get the current power state.

        :param task: a TaskManager instance.
        :param node: the node info.
        :returns:  power state POWER_ON, POWER_OFF or ERROR defined in
                 :class:`ironic.common.states`.
        :raises: InvalidParameterValue when required ipmi credentials
                 are missing.
        :raises: IPMIFailure when the native ipmi call fails.
        """
        driver_info = _parse_driver_info(node)
        return _power_status(driver_info)

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, node, pstate):
        """Turn the power on or off.

        :param task: a TaskManager instance.
        :param node: the node info.
        :param pstate: a power state that will be set on the given node.
        :raises: IPMIFailure when the native ipmi call fails.
        :raises: InvalidParameterValue when an invalid power state
                 is specified or required ipmi credentials are missing.
        :raises: PowerStateFailure when invalid power state is returned
                 from ipmi.
        """

        driver_info = _parse_driver_info(node)

        if pstate == states.POWER_ON:
            _power_on(driver_info)
        elif pstate == states.POWER_OFF:
            _power_off(driver_info)
        else:
            raise exception.InvalidParameterValue(_(
                "set_power_state called with an invalid power state: %s."
                ) % pstate)

    @task_manager.require_exclusive_lock
    def reboot(self, task, node):
        """Cycles the power to a node.

        :param task: a TaskManager instance.
        :param node: the node info.
        :raises: IPMIFailure when the native ipmi call fails.
        :raises: InvalidParameterValue when required ipmi credentials
                 are missing.
        :raises: PowerStateFailure when invalid power state is returned
                 from ipmi.
        """

        driver_info = _parse_driver_info(node)
        _reboot(driver_info)

    @task_manager.require_exclusive_lock
    def _set_boot_device(self, task, node, device, persistent=False):
        """Set the boot device for a node.

        :param task: a TaskManager instance.
        :param node: The Node.
        :param device: Boot device. One of [net, network, pxe, hd, cd,
            cdrom, dvd, floppy, default, setup, f1]
        :param persistent: Whether to set next-boot, or make the change
            permanent. Default: False.
        :raises: InvalidParameterValue if an invalid boot device is specified
                 or required ipmi credentials are missing.
        :raises: IPMIFailure when the native ipmi call fails.
        """

        if device not in ipmi_command.boot_devices:
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)
        driver_info = _parse_driver_info(node)
        try:
            ipmicmd = ipmi_command.Command(bmc=driver_info['address'],
                               userid=driver_info['username'],
                               password=driver_info['password'])
            ipmicmd.set_bootdev(device)
        except pyghmi_exception.IpmiException as e:
            LOG.warning(_("IPMI set boot device failed for node %(node_id)s "
                          "with the following error: %(error)s")
                          % {'node_id': driver_info['uuid'], 'error': str(e)})
            raise exception.IPMIFailure(cmd=str(e))
