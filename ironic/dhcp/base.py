# Copyright 2014 Rackspace, Inc.
# All Rights Reserved
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
Abstract base class for dhcp providers.
"""

import abc

import six


@six.add_metaclass(abc.ABCMeta)
class BaseDHCP(object):
    """Base class for DHCP provider APIs."""

    @abc.abstractmethod
    def update_port_dhcp_opts(self, port_id, dhcp_options):
        """Update one or more DHCP options on the specified port.

        :param port_id: designate which port these attributes
                        will be applied to.
        :param dhcp_options: this will be a list of dicts, e.g.
                        [{'opt_name': 'bootfile-name',
                          'opt_value': 'pxelinux.0'},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '123.123.123.456'},
                         {'opt_name': 'tftp-server',
                          'opt_value': '123.123.123.123'}]

        :raises: FailedToUpdateDHCPOptOnPort
        """

    @abc.abstractmethod
    def update_port_address(self, port_id, address):
        """Update a port's MAC address.

        :param port_id: port id.
        :param address: new MAC address.
        :raises: FailedToUpdateMacOnPort
        """

    @abc.abstractmethod
    def update_dhcp_opts(self, task, options):
        """Send or update the DHCP BOOT options for this node.

        :param task: A TaskManager instance.
        :param options: this will be a list of dicts, e.g.
                        [{'opt_name': 'bootfile-name',
                          'opt_value': 'pxelinux.0'},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '123.123.123.456'},
                         {'opt_name': 'tftp-server',
                          'opt_value': '123.123.123.123'}]

        :raises: FailedToUpdateDHCPOptOnPort
        """

    @abc.abstractmethod
    def get_ip_addresses(self, task):
        """Get IP addresses for all ports in `task`.

        :param task: a TaskManager instance.
        :returns: List of IP addresses associated with task.ports
        """
