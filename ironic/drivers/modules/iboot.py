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
Ironic iBoot PDU power manager.
"""

import time

from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _, _LW
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers import base

iboot = importutils.try_import('iboot')

LOG = logging.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'iboot_address': _("IP address of the node. Required."),
    'iboot_username': _("username. Required."),
    'iboot_password': _("password. Required."),
}
OPTIONAL_PROPERTIES = {
    'iboot_relay_id': _("iBoot PDU relay id; default is 1. Optional."),
    'iboot_port': _("iBoot PDU port; default is 9100. Optional."),
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)


def _parse_driver_info(node):
    info = node.driver_info or {}
    missing_info = [key for key in REQUIRED_PROPERTIES if not info.get(key)]
    if missing_info:
        raise exception.MissingParameterValue(
            _("Missing the following iBoot credentials in node's"
              " driver_info: %s.") % missing_info)

    address = info.get('iboot_address', None)
    username = info.get('iboot_username', None)
    password = info.get('iboot_password', None)

    relay_id = info.get('iboot_relay_id', 1)
    try:
        relay_id = int(relay_id)
    except ValueError:
        raise exception.InvalidParameterValue(
            _("iBoot PDU relay id must be an integer."))

    port = info.get('iboot_port', 9100)
    port = utils.validate_network_port(port, 'iboot_port')

    return {
        'address': address,
        'username': username,
        'password': password,
        'port': port,
        'relay_id': relay_id,
        'uuid': node.uuid,
    }


def _get_connection(driver_info):
    # NOTE: python-iboot wants username and password as strings (not unicode)
    return iboot.iBootInterface(driver_info['address'],
                                str(driver_info['username']),
                                str(driver_info['password']),
                                port=driver_info['port'],
                                num_relays=driver_info['relay_id'])


def _switch(driver_info, enabled):
    conn = _get_connection(driver_info)
    relay_id = driver_info['relay_id']

    def _wait_for_switch(mutable):
        if mutable['retries'] > CONF.iboot.max_retry:
            LOG.warning(_LW(
                'Reached maximum number of attempts (%(attempts)d) to set '
                'power state for node %(node)s to "%(op)s"'),
                {'attempts': mutable['retries'], 'node': driver_info['uuid'],
                 'op': states.POWER_ON if enabled else states.POWER_OFF})
            raise loopingcall.LoopingCallDone()

        try:
            mutable['retries'] += 1
            mutable['response'] = conn.switch(relay_id, enabled)
            if mutable['response']:
                raise loopingcall.LoopingCallDone()
        except (TypeError, IndexError):
            LOG.warning(_LW("Cannot call set power state for node '%(node)s' "
                            "at relay '%(relay)s'. iBoot switch() failed."),
                        {'node': driver_info['uuid'], 'relay': relay_id})

    mutable = {'response': False, 'retries': 0}
    timer = loopingcall.FixedIntervalLoopingCall(_wait_for_switch,
                                                 mutable)
    timer.start(interval=CONF.iboot.retry_interval).wait()
    return mutable['response']


def _sleep_switch(seconds):
    """Function broken out for testing purpose."""
    time.sleep(seconds)


def _check_power_state(driver_info, pstate):
    """Function to check power state is correct. Up to max retries."""
    # always try once + number of retries
    for num in range(0, 1 + CONF.iboot.max_retry):
        state = _power_status(driver_info)
        if state == pstate:
            return
        if num < CONF.iboot.max_retry:
            time.sleep(CONF.iboot.retry_interval)
    raise exception.PowerStateFailure(pstate=pstate)


def _power_status(driver_info):
    conn = _get_connection(driver_info)
    relay_id = driver_info['relay_id']

    def _wait_for_power_status(mutable):

        if mutable['retries'] > CONF.iboot.max_retry:
            LOG.warning(_LW(
                'Reached maximum number of attempts (%(attempts)d) to get '
                'power state for node %(node)s'),
                {'attempts': mutable['retries'], 'node': driver_info['uuid']})
            raise loopingcall.LoopingCallDone()

        try:
            mutable['retries'] += 1
            response = conn.get_relays()
            status = response[relay_id - 1]
            if status:
                mutable['state'] = states.POWER_ON
            else:
                mutable['state'] = states.POWER_OFF
            raise loopingcall.LoopingCallDone()
        except (TypeError, IndexError):
            LOG.warning(_LW("Cannot get power state for node '%(node)s' at "
                            "relay '%(relay)s'. iBoot get_relays() failed."),
                        {'node': driver_info['uuid'], 'relay': relay_id})

    mutable = {'state': states.ERROR, 'retries': 0}

    timer = loopingcall.FixedIntervalLoopingCall(_wait_for_power_status,
                                                 mutable)
    timer.start(interval=CONF.iboot.retry_interval).wait()
    return mutable['state']


class IBootPower(base.PowerInterface):
    """iBoot PDU Power Driver for Ironic

    This PowerManager class provides a mechanism for controlling power state
    via an iBoot capable device.

    Requires installation of python-iboot:

        https://github.com/darkip/python-iboot

    """

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task):
        """Validate driver_info for iboot driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if iboot parameters are invalid.
        :raises: MissingParameterValue if required iboot parameters are
            missing.

        """
        _parse_driver_info(task.node)

    def get_power_state(self, task):
        """Get the current power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: one of ironic.common.states POWER_OFF, POWER_ON or ERROR.
        :raises: InvalidParameterValue if iboot parameters are invalid.
        :raises: MissingParameterValue if required iboot parameters are
            missing.

        """
        driver_info = _parse_driver_info(task.node)
        return _power_status(driver_info)

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, pstate):
        """Turn the power on or off.

        :param task: a TaskManager instance containing the node to act on.
        :param pstate: The desired power state, one of ironic.common.states
            POWER_ON, POWER_OFF.
        :raises: InvalidParameterValue if iboot parameters are invalid or if
            an invalid power state was specified.
        :raises: MissingParameterValue if required iboot parameters are
            missing.
        :raises: PowerStateFailure if the power couldn't be set to pstate.

        """
        driver_info = _parse_driver_info(task.node)
        if pstate == states.POWER_ON:
            _switch(driver_info, True)
        elif pstate == states.POWER_OFF:
            _switch(driver_info, False)
        else:
            raise exception.InvalidParameterValue(
                _("set_power_state called with invalid "
                  "power state %s.") % pstate)

        _check_power_state(driver_info, pstate)

    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Cycles the power to the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if iboot parameters are invalid.
        :raises: MissingParameterValue if required iboot parameters are
            missing.
        :raises: PowerStateFailure if the final state of the node is not
            POWER_ON.

        """
        driver_info = _parse_driver_info(task.node)
        _switch(driver_info, False)
        _sleep_switch(CONF.iboot.reboot_delay)
        _switch(driver_info, True)
        _check_power_state(driver_info, states.POWER_ON)
