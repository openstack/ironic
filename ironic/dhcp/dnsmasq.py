#
# Copyright 2022 Red Hat, Inc.
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

import os

from oslo_log import log as logging
from oslo_utils import uuidutils

from ironic.conf import CONF
from ironic.dhcp import base

LOG = logging.getLogger(__name__)


class DnsmasqDHCPApi(base.BaseDHCP):
    """API for managing host specific Dnsmasq configuration."""

    def update_port_dhcp_opts(self, port_id, dhcp_options, token=None,
                              context=None):
        pass

    def update_dhcp_opts(self, task, options, vifs=None):
        """Send or update the DHCP BOOT options for this node.

        :param task: A TaskManager instance.
        :param options: this will be a list of dicts, e.g.

                        ::

                         [{'opt_name': '67',
                           'opt_value': 'pxelinux.0',
                           'ip_version': 4},
                          {'opt_name': '66',
                           'opt_value': '123.123.123.456',
                           'ip_version': 4}]
        :param vifs: Ignored argument
        """
        node = task.node
        macs = set(self._pxe_enabled_macs(task.ports))

        opt_file = self._opt_file_path(node)
        tag = node.driver_internal_info.get('dnsmasq_tag')
        if not tag:
            tag = uuidutils.generate_uuid()
            node.set_driver_internal_info('dnsmasq_tag', tag)
            node.save()

        LOG.debug('Writing to %s:', opt_file)
        with open(opt_file, 'w') as f:
            # Apply each option by tag
            for option in options:
                entry = 'tag:{tag},{opt_name},{opt_value}\n'.format(
                    tag=tag,
                    opt_name=option.get('opt_name'),
                    opt_value=option.get('opt_value'),
                )
                LOG.debug(entry)
                f.write(entry)

        for mac in macs:
            host_file = self._host_file_path(mac)
            LOG.debug('Writing to %s:', host_file)
            with open(host_file, 'w') as f:
                # Tag each address with the unique uuid scoped to
                # this node and DHCP transaction
                entry = '{mac},set:{tag},set:ironic\n'.format(
                    mac=mac, tag=tag)
                LOG.debug(entry)
                f.write(entry)

    def _opt_file_path(self, node):
        return os.path.join(CONF.dnsmasq.dhcp_optsdir,
                            'ironic-{}.conf'.format(node.uuid))

    def _host_file_path(self, mac):
        return os.path.join(CONF.dnsmasq.dhcp_hostsdir,
                            'ironic-{}.conf'.format(mac))

    def _pxe_enabled_macs(self, ports):
        for port in ports:
            if port.pxe_enabled:
                yield port.address

    def get_ip_addresses(self, task):
        """Get IP addresses for all ports/portgroups in `task`.

        :param task: a TaskManager instance.
        :returns: List of IP addresses associated with
                  task's ports/portgroups.
        """
        lease_path = CONF.dnsmasq.dhcp_leasefile
        macs = set(self._pxe_enabled_macs(task.ports))
        addresses = []
        with open(lease_path, 'r') as f:
            for line in f.readlines():
                lease = line.split()
                if lease[1] in macs:
                    addresses.append(lease[2])
        LOG.debug('Found addresses for %s: %s',
                  task.node.uuid, ', '.join(addresses))
        return addresses

    def clean_dhcp_opts(self, task):
        """Clean up the DHCP BOOT options for the host in `task`.

        :param task: A TaskManager instance.

        :raises: FailedToCleanDHCPOpts
        """

        node = task.node
        # Discard this unique tag
        node.del_driver_internal_info('dnsmasq_tag')
        node.save()

        # Changing the host rule to ignore will be picked up by dnsmasq
        # without requiring a SIGHUP. When the mac address is active again
        # this file will be replaced with one that applies a new unique tag.
        macs = set(self._pxe_enabled_macs(task.ports))
        for mac in macs:
            host_file = self._host_file_path(mac)
            with open(host_file, 'w') as f:
                entry = '{mac},ignore\n'.format(mac=mac)
                f.write(entry)

        # Deleting the file containing dhcp-option won't remove the rules from
        # dnsmasq but no requests will be tagged with the dnsmasq_tag uuid so
        # these rules will not apply.
        opt_file = self._opt_file_path(node)
        if os.path.exists(opt_file):
            os.remove(opt_file)

    def supports_ipxe_tag(self):
        """Whether the provider will correctly apply the 'ipxe' tag.

        When iPXE makes a DHCP request, does this provider support adding
        the tag `ipxe` or `ipxe6` (for IPv6). When the provider returns True,
        options can be added which filter on these tags.

        The `dnsmasq` provider sets this to True on the assumption that the
        following is included in the dnsmasq.conf:

        dhcp-match=set:ipxe,175

        :returns: True
        """
        return True
