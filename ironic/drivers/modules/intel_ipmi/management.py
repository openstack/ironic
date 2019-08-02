# coding=utf-8
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
Intel IPMI Hardware.

Supports Intel Speed Select Performance Profile.
"""

from oslo_log import log as logging

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers.modules import ipmitool


LOG = logging.getLogger(__name__)
INTEL_SST_PP_CONFIG_HEXA_CODES = ['0x00', '0x01', '0x02']


class IntelIPMIManagement(ipmitool.IPMIManagement):

    def _validate_input(self, config, sockets):
        if config not in INTEL_SST_PP_CONFIG_HEXA_CODES:
            raise exception.InvalidParameterValue(_(
                "Invalid Intel SST-PP configuration value %(config)s "
                "specified. Valid values are %(config_list)s.")
                % {"config": config,
                   "config_list": INTEL_SST_PP_CONFIG_HEXA_CODES})
        try:
            socket_count = int(sockets)
            if socket_count <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise exception.InvalidParameterValue(_(
                "Invalid number of socket %(socket)s value specified. "
                "Expected a positive integer.") % {"socket": sockets})

    @base.deploy_step(priority=200, argsinfo={
        'intel_speedselect_config': {
            'description': (
                "Hexadecimal code of Intel SST-PP configuration provided. "
                "Input value should be string. Accepted values are %s."
                % ', '.join(INTEL_SST_PP_CONFIG_HEXA_CODES)
            ),
            'required': True
        },
        'socket_count': {
            'description': (
                "Number of sockets. Input value should be a positive integer."
            )
        }
    })
    def configure_intel_speedselect(self, task, **kwargs):
        config = kwargs.get('intel_speedselect_config')
        socket_count = kwargs.get('socket_count', 1)
        self._validate_input(config, socket_count)
        LOG.debug("Going to set Intel SST-PP configuration level %(config)s "
                  "for node %(node)s with socket count %(socket)s",
                  {"config": config, "node": task.node.uuid,
                   "socket": socket_count})
        iss_conf = "0x2c 0x41 0x04 0x00 0x0%s %s"
        for socket in range(socket_count):
            hexa_code = iss_conf % (socket, config)
            try:
                ipmitool.send_raw(task, hexa_code)
            except exception.IPMIFailure as e:
                msg = (_("Failed to set Intel SST-PP configuration level "
                         "%(cfg)s on socket number %(skt)s due to "
                         "reason %(exc)s.") % {"cfg": config,
                                               "skt": socket, "exc": e})
                LOG.error(msg)
                raise exception.IPMIFailure(message=msg)
