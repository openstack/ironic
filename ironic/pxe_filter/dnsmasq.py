# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import fcntl
import os
import time

from oslo_log import log

from ironic.conf import CONF

LOG = log.getLogger(__name__)


def update(allow_macs, deny_macs, allow_unknown=None):
    """Update only the given MACs.

    MACs not in either lists are ignored.

    :param allow_macs: MACs to allow in dnsmasq.
    :param deny_macs: MACs to disallow in dnsmasq.
    :param allow_unknown: If set to True, unknown MACs are also allowed.
        Setting it to False does nothing in this call.
    """
    for mac in allow_macs:
        _add_mac_to_allowlist(mac)
    for mac in deny_macs:
        _add_mac_to_denylist(mac)
    if allow_unknown:
        _configure_unknown_hosts(True)


def sync(allow_macs, deny_macs, allow_unknown):
    """Conduct a complete sync of the state.

    Unlike ``update``, MACs not in either list are handled according
    to ``allow_unknown``.

    :param allow_macs: MACs to allow in dnsmasq.
    :param deny_macs: MACs to disallow in dnsmasq.
    :param allow_unknown: Whether to allow access to dnsmasq to unknown
        MACs.
    """
    allow_macs = set(allow_macs)
    deny_macs = set(deny_macs)

    known_macs = allow_macs.union(deny_macs)
    current_denylist, current_allowlist = _get_deny_allow_lists()
    removed_macs = current_denylist.union(current_allowlist).difference(
        known_macs)

    update(allow_macs=allow_macs.difference(current_allowlist),
           deny_macs=deny_macs.difference(current_denylist))

    # Allow or deny unknown hosts and MACs not kept in ironic
    # NOTE(hjensas): Treat unknown hosts and MACs not kept in ironic the
    # same. Neither should boot the inspection image unless inspection
    # is active. Deleted MACs must be added to the allow list when
    # inspection is active in case the host is re-enrolled.
    _configure_unknown_hosts(allow_unknown)
    _configure_removedlist(removed_macs, allow_unknown)


_EXCLUSIVE_WRITE_ATTEMPTS = 10
_EXCLUSIVE_WRITE_ATTEMPTS_DELAY = 0.01

_MAC_DENY_LEN = len('ff:ff:ff:ff:ff:ff,ignore\n')
_MAC_ALLOW_LEN = len('ff:ff:ff:ff:ff:ff\n')
_UNKNOWN_HOSTS_FILE = 'unknown_hosts_filter'
_DENY_UNKNOWN_HOSTS = '*:*:*:*:*:*,ignore\n'
_ALLOW_UNKNOWN_HOSTS = '*:*:*:*:*:*\n'


def _get_deny_allow_lists():
    """Get addresses currently denied by dnsmasq.

    :raises: FileNotFoundError in case the dhcp_hostsdir is invalid.
    :returns: tuple with 2 elements: a set of MACs currently denied by dnsmasq
        and a set of allowed MACs.
    """
    hostsdir = CONF.pxe_filter.dhcp_hostsdir
    # MACs in the allow list lack the ,ignore directive
    denylist = set()
    allowlist = set()
    for mac in os.listdir(hostsdir):
        if os.stat(os.path.join(hostsdir, mac)).st_size == _MAC_DENY_LEN:
            denylist.add(mac)
        if os.stat(os.path.join(hostsdir, mac)).st_size == _MAC_ALLOW_LEN:
            allowlist.add(mac)

    return denylist, allowlist


def _exclusive_write_or_pass(path, buf):
    """Write exclusively or pass if path locked.

    The intention is to be able to run multiple instances of the filter on the
    same node in multiple inspector processes.

    :param path: where to write to
    :param buf: the content to write
    :raises: FileNotFoundError, IOError
    :returns: True if the write was successful.
    """
    # NOTE(milan) line-buffering enforced to ensure dnsmasq record update
    # through inotify, which reacts on f.close()
    with open(path, 'w', 1) as f:
        for attempt in range(_EXCLUSIVE_WRITE_ATTEMPTS):
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                f.write(buf)
                # Go ahead and flush the data now instead of waiting until
                # after the automatic flush with the file close after the
                # file lock is released.
                f.flush()
                return True
            except BlockingIOError:
                LOG.debug('%s locked; will try again (later)', path)
                time.sleep(_EXCLUSIVE_WRITE_ATTEMPTS_DELAY)
                continue
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    LOG.debug('Failed to write the exclusively-locked path: %(path)s for '
              '%(attempts)s times', {'attempts': _EXCLUSIVE_WRITE_ATTEMPTS,
                                     'path': path})
    return False


def _configure_removedlist(macs, allowed):
    """Manages a dhcp_hostsdir allow/deny record for removed macs

    :raises: FileNotFoundError in case the dhcp_hostsdir is invalid,
    :returns: None.
    """
    hostsdir = CONF.pxe_filter.dhcp_hostsdir

    for mac in macs:
        file_size = os.stat(os.path.join(hostsdir, mac)).st_size
        if allowed:
            if file_size != _MAC_ALLOW_LEN:
                _add_mac_to_allowlist(mac)
        else:
            if file_size != _MAC_DENY_LEN:
                _add_mac_to_denylist(mac)


def _configure_unknown_hosts(enabled):
    """Manages a dhcp_hostsdir allow/deny record for unknown macs.

    :raises: FileNotFoundError in case the dhcp_hostsdir is invalid,
             IOError in case the dhcp host unknown file isn't writable.
    :returns: None.
    """
    path = os.path.join(CONF.pxe_filter.dhcp_hostsdir, _UNKNOWN_HOSTS_FILE)

    if enabled:
        wildcard_filter = _ALLOW_UNKNOWN_HOSTS
        log_wildcard_filter = 'allow'
    else:
        wildcard_filter = _DENY_UNKNOWN_HOSTS
        log_wildcard_filter = 'deny'

    # Don't update if unknown hosts are already in the deny/allow-list
    try:
        if os.stat(path).st_size == len(wildcard_filter):
            return
    except FileNotFoundError:
        pass

    if _exclusive_write_or_pass(path, '%s' % wildcard_filter):
        LOG.debug('A %s record for all unknown hosts using wildcard mac '
                  'created', log_wildcard_filter)
    else:
        LOG.warning('Failed to %s unknown hosts using wildcard mac; '
                    'retrying next periodic sync time', log_wildcard_filter)


def _add_mac_to_denylist(mac):
    """Creates a dhcp_hostsdir deny record for the MAC.

    :raises: FileNotFoundError in case the dhcp_hostsdir is invalid,
             IOError in case the dhcp host MAC file isn't writable.
    :returns: None.
    """
    path = os.path.join(CONF.pxe_filter.dhcp_hostsdir, mac)
    if _exclusive_write_or_pass(path, '%s,ignore\n' % mac):
        LOG.debug('MAC %s added to the deny list', mac)
    else:
        LOG.warning('Failed to add MAC %s to the deny list; retrying next '
                    'periodic sync time', mac)


def _add_mac_to_allowlist(mac):
    """Update the dhcp_hostsdir record for the MAC adding it to allow list

    :raises: FileNotFoundError in case the dhcp_hostsdir is invalid,
             IOError in case the dhcp host MAC file isn't writable.
    :returns: None.
    """
    path = os.path.join(CONF.pxe_filter.dhcp_hostsdir, mac)
    # remove the ,ignore directive
    if _exclusive_write_or_pass(path, '%s\n' % mac):
        LOG.debug('MAC %s removed from the deny list', mac)
    else:
        LOG.warning('Failed to remove MAC %s from the deny list; retrying '
                    'next periodic sync time', mac)
