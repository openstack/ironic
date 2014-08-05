# Copyright 2014 Rackspace, Inc.
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

import stevedore

from oslo.config import cfg

from ironic.common import exception
from ironic.openstack.common import lockutils


dhcp_provider_opts = [
    cfg.StrOpt('dhcp_provider',
               default='neutron',
               help='DHCP provider to use. "neutron" uses Neutron, and '
               '"none" uses a no-op provider.'
               ),
]

CONF = cfg.CONF
CONF.register_opts(dhcp_provider_opts, group='dhcp')

_dhcp_provider = None

EM_SEMAPHORE = 'dhcp_provider'


class DHCPFactory(object):

    # NOTE(lucasagomes): Instantiate a stevedore.driver.DriverManager
    #                    only once, the first time DHCPFactory.__init__
    #                    is called.
    _dhcp_provider = None

    def __init__(self, **kwargs):
        if not DHCPFactory._dhcp_provider:
            DHCPFactory._set_dhcp_provider(**kwargs)

    # NOTE(lucasagomes): Use lockutils to avoid a potential race in eventlet
    #                    that might try to create two dhcp factories.
    @classmethod
    @lockutils.synchronized(EM_SEMAPHORE, 'ironic-')
    def _set_dhcp_provider(cls, **kwargs):
        """Initialize the dhcp provider

        :raises: DHCPNotFound if the dhcp_provider cannot be loaded.
        """

        # NOTE(lucasagomes): In case multiple greenthreads queue up on
        #                    this lock before _dhcp_provider is initialized,
        #                    prevent creation of multiple DriverManager.
        if cls._dhcp_provider:
            return

        dhcp_provider_name = CONF.dhcp.dhcp_provider
        try:
            _extension_manager = stevedore.driver.DriverManager(
                'ironic.dhcp',
                dhcp_provider_name,
                invoke_kwds=kwargs,
                invoke_on_load=True)
        except RuntimeError:
            raise exception.DHCPNotFound(dhcp_provider_name=dhcp_provider_name)

        cls._dhcp_provider = _extension_manager.driver

    def update_dhcp(self, task, dhcp_opts):
        """Send or update the DHCP BOOT options for this node.

        :param task: A TaskManager instance.
        :param dhcp_opts: this will be a list of dicts, e.g.
                        [{'opt_name': 'bootfile-name',
                          'opt_value': 'pxelinux.0'},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '123.123.123.456'},
                         {'opt_name': 'tftp-server',
                          'opt_value': '123.123.123.123'}]
        """
        self.provider.update_dhcp_opts(task, dhcp_opts)

    @property
    def provider(self):
        return self._dhcp_provider
