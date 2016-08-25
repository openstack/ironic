# Copyright 2015 Red Hat, Inc.
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
Ironic Wake-On-Lan power manager.
"""

import contextlib
import socket
import time

from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _, _LI
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.drivers import base

LOG = log.getLogger(__name__)

REQUIRED_PROPERTIES = {}
OPTIONAL_PROPERTIES = {
    'wol_host': _('Broadcast IP address; defaults to '
                  '255.255.255.255. Optional.'),
    'wol_port': _("Destination port; defaults to 9. Optional."),
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)


def _send_magic_packets(task, dest_host, dest_port):
    """Create and send magic packets.

    Creates and sends a magic packet for each MAC address registered in
    the Node.

    :param task: a TaskManager instance containing the node to act on.
    :param dest_host: The broadcast to this IP address.
    :param dest_port: The destination port.
    :raises: WolOperationError if an error occur when connecting to the
        host or sending the magic packets

    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    with contextlib.closing(s) as sock:
        for port in task.ports:
            address = port.address.replace(':', '')

            # TODO(lucasagomes): Implement sending the magic packets with
            # SecureON password feature. If your NIC is capable of, you can
            # set the password of your SecureON using the ethtool utility.
            data = 'FFFFFFFFFFFF' + (address * 16)
            packet = bytearray.fromhex(data)

            try:
                sock.sendto(packet, (dest_host, dest_port))
            except socket.error as e:
                msg = (_("Failed to send Wake-On-Lan magic packets to "
                         "node %(node)s port %(port)s. Error: %(error)s") %
                       {'node': task.node.uuid, 'port': port.address,
                        'error': e})
                LOG.exception(msg)
                raise exception.WolOperationError(msg)

            # let's not flood the network with broadcast packets
            time.sleep(0.5)


def _parse_parameters(task):
    driver_info = task.node.driver_info
    host = driver_info.get('wol_host', '255.255.255.255')
    port = driver_info.get('wol_port', 9)
    port = utils.validate_network_port(port, 'wol_port')

    if len(task.ports) < 1:
        raise exception.MissingParameterValue(_(
            'Wake-On-Lan needs at least one port resource to be '
            'registered in the node'))

    return {'host': host, 'port': port}


class WakeOnLanPower(base.PowerInterface):
    """Wake-On-Lan Driver for Ironic

    This PowerManager class provides a mechanism for controlling power
    state via Wake-On-Lan.

    """

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task):
        """Validate  driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if parameters are invalid.
        :raises: MissingParameterValue if required parameters are missing.

        """
        _parse_parameters(task)

    def get_power_state(self, task):
        """Not supported. Get the current power state of the task's node.

        This operation is not supported by the Wake-On-Lan driver. So
        value returned will be from the database and may not reflect
        the actual state of the system.

        :returns: POWER_OFF if power state is not set otherwise return
            the node's power_state value from the database.

        """
        pstate = task.node.power_state
        return states.POWER_OFF if pstate is states.NOSTATE else pstate

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, pstate):
        """Wakes the task's node on power on. Powering off is not supported.

        Wakes the task's node on. Wake-On-Lan does not support powering
        the task's node off so, just log it.

        :param task: a TaskManager instance containing the node to act on.
        :param pstate: The desired power state, one of ironic.common.states
            POWER_ON, POWER_OFF.
        :raises: InvalidParameterValue if parameters are invalid.
        :raises: MissingParameterValue if required parameters are missing.
        :raises: WolOperationError if an error occur when sending the
            magic packets

        """
        node = task.node
        params = _parse_parameters(task)
        if pstate == states.POWER_ON:
            _send_magic_packets(task, params['host'], params['port'])
        elif pstate == states.POWER_OFF:
            LOG.info(_LI('Power off called for node %s. Wake-On-Lan does not '
                         'support this operation. Manual intervention '
                         'required to perform this action.'), node.uuid)
        else:
            raise exception.InvalidParameterValue(_(
                "set_power_state called for Node %(node)s with invalid "
                "power state %(pstate)s.") % {'node': node.uuid,
                                              'pstate': pstate})

    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Not supported. Cycles the power to the task's node.

        This operation is not fully supported by the Wake-On-Lan
        driver. So this method will just try to power the task's node on.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if parameters are invalid.
        :raises: MissingParameterValue if required parameters are missing.
        :raises: WolOperationError if an error occur when sending the
            magic packets

        """
        LOG.info(_LI('Reboot called for node %s. Wake-On-Lan does '
                     'not fully support this operation. Trying to '
                     'power on the node.'), task.node.uuid)
        self.set_power_state(task, states.POWER_ON)
