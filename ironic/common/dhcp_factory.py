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

from oslo_concurrency import lockutils
import stevedore

from ironic.common import exception
from ironic.conf import CONF

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
    @lockutils.synchronized(EM_SEMAPHORE)
    def _set_dhcp_provider(cls, **kwargs):
        """Initialize the dhcp provider

        :raises: DHCPLoadError if the dhcp_provider cannot be loaded.
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
        except Exception as e:
            raise exception.DHCPLoadError(
                dhcp_provider_name=dhcp_provider_name, reason=e
            )

        cls._dhcp_provider = _extension_manager.driver

    def update_dhcp(self, task, dhcp_opts, ports=None):
        """Send or update the DHCP BOOT options for this node.

        :param task: A TaskManager instance.
        :param dhcp_opts: this will be a list of dicts, e.g.

                          ::

                           [{'opt_name': '67',
                             'opt_value': 'pxelinux.0'},
                            {'opt_name': '66',
                             'opt_value': '123.123.123.456'}]

        :param ports: A dict with keys 'ports' and 'portgroups' and
            dicts as values. Each dict has key/value pairs of the form
            <ironic UUID>:<neutron port UUID>. e.g.

                          ::

                           {'ports': {'port.uuid': vif.id},
                            'portgroups': {'portgroup.uuid': vif.id}}

            If the value is None, will get the list of ports/portgroups
            from the Ironic port/portgroup objects.
        """
        self.provider.update_dhcp_opts(task, dhcp_opts, ports)

    def clean_dhcp(self, task):
        """Clean up the DHCP BOOT options for this node.

        :param task: A TaskManager instance.
        """
        self.provider.clean_dhcp_opts(task)

    @property
    def provider(self):
        return self._dhcp_provider
