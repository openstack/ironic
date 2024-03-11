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

import builtins
import errno
import os
from unittest import mock

import fixtures

from ironic.conf import CONF
from ironic.pxe_filter import dnsmasq
from ironic.tests import base as test_base


class TestExclusiveWriteOrPass(test_base.TestCase):
    def setUp(self):
        super().setUp()
        self.mock_open = self.useFixture(fixtures.MockPatchObject(
            builtins, 'open', new=mock.mock_open())).mock
        self.mock_fd = self.mock_open.return_value
        self.mock_fcntl = self.useFixture(fixtures.MockPatchObject(
            dnsmasq.fcntl, 'flock', autospec=True)).mock
        self.path = '/foo/bar/baz'
        self.buf = 'spam'
        self.fcntl_lock_call = mock.call(
            self.mock_fd, dnsmasq.fcntl.LOCK_EX | dnsmasq.fcntl.LOCK_NB)
        self.fcntl_unlock_call = mock.call(self.mock_fd, dnsmasq.fcntl.LOCK_UN)
        self.mock_log = self.useFixture(fixtures.MockPatchObject(
            dnsmasq.LOG, 'debug')).mock
        self.mock_sleep = self.useFixture(fixtures.MockPatchObject(
            dnsmasq.time, 'sleep')).mock

    def test_write(self):
        wrote = dnsmasq._exclusive_write_or_pass(self.path, self.buf)
        self.assertTrue(wrote)
        self.mock_open.assert_called_once_with(self.path, 'w', 1)
        self.mock_fcntl.assert_has_calls(
            [self.fcntl_lock_call, self.fcntl_unlock_call])
        self.mock_fd.write.assert_called_once_with(self.buf)
        self.mock_log.assert_not_called()

    def test_write_would_block(self):
        # lock/unlock paired calls
        self.mock_fcntl.side_effect = [
            # first try
            BlockingIOError, None,
            # second try
            None, None]
        wrote = dnsmasq._exclusive_write_or_pass(self.path, self.buf)

        self.assertTrue(wrote)
        self.mock_open.assert_called_once_with(self.path, 'w', 1)
        self.mock_fcntl.assert_has_calls(
            [self.fcntl_lock_call, self.fcntl_unlock_call],
            [self.fcntl_lock_call, self.fcntl_unlock_call])
        self.mock_fd.write.assert_called_once_with(self.buf)
        self.mock_log.assert_called_once_with(
            '%s locked; will try again (later)', self.path)
        self.mock_sleep.assert_called_once_with(
            dnsmasq._EXCLUSIVE_WRITE_ATTEMPTS_DELAY)

    @mock.patch.object(dnsmasq, '_EXCLUSIVE_WRITE_ATTEMPTS', 1)
    def test_write_would_block_too_many_times(self):
        self.mock_fcntl.side_effect = [BlockingIOError, None]

        wrote = dnsmasq._exclusive_write_or_pass(self.path, self.buf)
        self.assertFalse(wrote)
        self.mock_open.assert_called_once_with(self.path, 'w', 1)
        self.mock_fcntl.assert_has_calls(
            [self.fcntl_lock_call, self.fcntl_unlock_call])
        self.mock_fd.write.assert_not_called()
        retry_log_call = mock.call('%s locked; will try again (later)',
                                   self.path)
        failed_log_call = mock.call(
            'Failed to write the exclusively-locked path: %(path)s for '
            '%(attempts)s times', {
                'attempts': dnsmasq._EXCLUSIVE_WRITE_ATTEMPTS,
                'path': self.path
            })
        self.mock_log.assert_has_calls([retry_log_call, failed_log_call])
        self.mock_sleep.assert_called_once_with(
            dnsmasq._EXCLUSIVE_WRITE_ATTEMPTS_DELAY)

    def test_write_custom_ioerror(self):

        err = IOError('Oops!')
        err.errno = errno.EBADF
        self.mock_fcntl.side_effect = [err, None]

        self.assertRaisesRegex(
            IOError, 'Oops!', dnsmasq._exclusive_write_or_pass, self.path,
            self.buf)

        self.mock_open.assert_called_once_with(self.path, 'w', 1)
        self.mock_fcntl.assert_has_calls(
            [self.fcntl_lock_call, self.fcntl_unlock_call])
        self.mock_fd.write.assert_not_called()
        self.mock_log.assert_not_called()


class TestHelpers(test_base.TestCase):
    def setUp(self):
        super().setUp()
        self.mac = 'ff:ff:ff:ff:ff:ff'
        self.dhcp_hostsdir = '/far'
        self.path = os.path.join(self.dhcp_hostsdir, self.mac)
        self.unknown_path = os.path.join(self.dhcp_hostsdir,
                                         dnsmasq._UNKNOWN_HOSTS_FILE)
        CONF.set_override('dhcp_hostsdir', self.dhcp_hostsdir,
                          'pxe_filter')
        self.mock__exclusive_write_or_pass = self.useFixture(
            fixtures.MockPatchObject(dnsmasq, '_exclusive_write_or_pass')).mock
        self.mock_stat = self.useFixture(
            fixtures.MockPatchObject(os, 'stat')).mock
        self.mock_listdir = self.useFixture(
            fixtures.MockPatchObject(os, 'listdir')).mock
        self.mock_log = self.useFixture(
            fixtures.MockPatchObject(dnsmasq, 'LOG')).mock

    def test__allowlist_unknown_hosts(self):
        dnsmasq._configure_unknown_hosts(True)

        self.mock__exclusive_write_or_pass.assert_called_once_with(
            self.unknown_path, '%s' % dnsmasq._ALLOW_UNKNOWN_HOSTS)
        self.mock_log.debug.assert_called_once_with(
            'A %s record for all unknown hosts using wildcard mac '
            'created', 'allow')

    def test__denylist_unknown_hosts(self):
        dnsmasq._configure_unknown_hosts(False)

        self.mock__exclusive_write_or_pass.assert_called_once_with(
            self.unknown_path, '%s' % dnsmasq._DENY_UNKNOWN_HOSTS)
        self.mock_log.debug.assert_called_once_with(
            'A %s record for all unknown hosts using wildcard mac '
            'created', 'deny')

    def test__configure_removedlist_allowlist(self):
        self.mock_stat.return_value.st_size = dnsmasq._MAC_DENY_LEN

        dnsmasq._configure_removedlist({self.mac}, True)

        self.mock__exclusive_write_or_pass.assert_called_once_with(
            self.path, '%s\n' % self.mac)

    def test__configure_removedlist_denylist(self):
        self.mock_stat.return_value.st_size = dnsmasq._MAC_ALLOW_LEN

        dnsmasq._configure_removedlist({self.mac}, False)

        self.mock__exclusive_write_or_pass.assert_called_once_with(
            self.path, '%s,ignore\n' % self.mac)

    def test__allowlist_mac(self):
        dnsmasq._add_mac_to_allowlist(self.mac)

        self.mock__exclusive_write_or_pass.assert_called_once_with(
            self.path, '%s\n' % self.mac)

    def test__denylist_mac(self):
        dnsmasq._add_mac_to_denylist(self.mac)

        self.mock__exclusive_write_or_pass.assert_called_once_with(
            self.path, '%s,ignore\n' % self.mac)

    def test__get_denylist(self):
        self.mock_listdir.return_value = [self.mac]
        self.mock_stat.return_value.st_size = len('%s,ignore\n' % self.mac)
        denylist, allowlist = dnsmasq._get_deny_allow_lists()

        self.assertEqual({self.mac}, denylist)
        self.mock_listdir.assert_called_once_with(self.dhcp_hostsdir)
        self.mock_stat.assert_called_with(self.path)

    def test__get_allowlist(self):
        self.mock_listdir.return_value = [self.mac]
        self.mock_stat.return_value.st_size = len('%s\n' % self.mac)
        denylist, allowlist = dnsmasq._get_deny_allow_lists()

        self.assertEqual({self.mac}, allowlist)
        self.mock_listdir.assert_called_once_with(self.dhcp_hostsdir)
        self.mock_stat.assert_called_with(self.path)

    def test__get_no_denylist(self):
        self.mock_listdir.return_value = [self.mac]
        self.mock_stat.return_value.st_size = len('%s\n' % self.mac)
        denylist, allowlist = dnsmasq._get_deny_allow_lists()

        self.assertEqual(set(), denylist)
        self.mock_listdir.assert_called_once_with(self.dhcp_hostsdir)
        self.mock_stat.assert_called_with(self.path)

    def test__get_no_allowlist(self):
        self.mock_listdir.return_value = [self.mac]
        self.mock_stat.return_value.st_size = len('%s,ignore\n' % self.mac)
        denylist, allowlist = dnsmasq._get_deny_allow_lists()

        self.assertEqual(set(), allowlist)
        self.mock_listdir.assert_called_once_with(self.dhcp_hostsdir)
        self.mock_stat.assert_called_with(self.path)


@mock.patch.object(dnsmasq, '_configure_unknown_hosts', autospec=True)
@mock.patch.object(dnsmasq, '_add_mac_to_denylist', autospec=True)
@mock.patch.object(dnsmasq, '_add_mac_to_allowlist', autospec=True)
class TestUpdate(test_base.TestCase):

    def test_no_update(self, mock_allow, mock_deny, mock_configure_unknown):
        dnsmasq.update([], [])
        mock_allow.assert_not_called()
        mock_deny.assert_not_called()
        mock_configure_unknown.assert_not_called()

    def test_only_allow(self, mock_allow, mock_deny, mock_configure_unknown):
        dnsmasq.update(['mac1', 'mac2'], [], allow_unknown=True)
        mock_allow.assert_has_calls([mock.call(f'mac{i}') for i in (1, 2)])
        mock_deny.assert_not_called()
        mock_configure_unknown.assert_called_once_with(True)

    def test_only_deny(self, mock_allow, mock_deny, mock_configure_unknown):
        dnsmasq.update([], ['mac1', 'mac2'])
        mock_allow.assert_not_called()
        mock_deny.assert_has_calls([mock.call(f'mac{i}') for i in (1, 2)])
        mock_configure_unknown.assert_not_called()


@mock.patch.object(dnsmasq, '_configure_removedlist', autospec=True)
@mock.patch.object(dnsmasq, '_configure_unknown_hosts', autospec=True)
@mock.patch.object(dnsmasq, '_add_mac_to_denylist', autospec=True)
@mock.patch.object(dnsmasq, '_add_mac_to_allowlist', autospec=True)
@mock.patch.object(dnsmasq, '_get_deny_allow_lists', autospec=True)
class TestSync(test_base.TestCase):

    def test_no_macs(self, mock_get_lists, mock_allow, mock_deny,
                     mock_configure_unknown, mock_configure_removedlist):
        mock_get_lists.return_value = set(), set()
        dnsmasq.sync([], [], False)
        mock_allow.assert_not_called()
        mock_deny.assert_not_called()
        mock_configure_unknown.assert_called_once_with(False)
        mock_configure_removedlist.assert_called_once_with(set(), False)

    def test_only_new_macs(self, mock_get_lists, mock_allow, mock_deny,
                           mock_configure_unknown, mock_configure_removedlist):
        mock_get_lists.return_value = set(), set()
        dnsmasq.sync(['allow1', 'allow2'], [], True)
        mock_allow.assert_has_calls(
            [mock.call(f'allow{i}') for i in (1, 2)],
            any_order=True)
        mock_deny.assert_not_called()
        mock_configure_unknown.assert_called_once_with(True)
        mock_configure_removedlist.assert_called_once_with(set(), True)

    def test_deny_macs(self, mock_get_lists, mock_allow, mock_deny,
                       mock_configure_unknown, mock_configure_removedlist):
        mock_get_lists.return_value = set(), {'deny1', 'allow1'}
        dnsmasq.sync(['allow1'], ['deny1', 'deny2'], False)
        mock_allow.assert_not_called()
        mock_deny.assert_has_calls(
            [mock.call(f'deny{i}') for i in (1, 2)],
            any_order=True)
        mock_configure_unknown.assert_called_once_with(False)
        mock_configure_removedlist.assert_called_once_with(set(), False)

    def test_removed_nodes(self, mock_get_lists, mock_allow, mock_deny,
                           mock_configure_unknown, mock_configure_removedlist):
        mock_get_lists.return_value = {'mac1'}, {'mac2', 'mac3'}
        dnsmasq.sync(['mac2'], [], True)
        mock_allow.assert_not_called()
        mock_deny.assert_not_called()
        mock_configure_unknown.assert_called_once_with(True)
        mock_configure_removedlist.assert_called_once_with(
            {'mac1', 'mac3'}, True)

    def test_change_state(self, mock_get_lists, mock_allow, mock_deny,
                          mock_configure_unknown, mock_configure_removedlist):
        # MAC1 from denied to allowed, MAC2 from allowed to denied, drop MAC3
        mock_get_lists.return_value = {'mac1'}, {'mac2', 'mac3'}
        dnsmasq.sync(['mac1'], ['mac2'], False)
        mock_allow.assert_called_once_with('mac1')
        mock_deny.assert_called_once_with('mac2')
        mock_configure_unknown.assert_called_once_with(False)
        mock_configure_removedlist.assert_called_once_with({'mac3'}, False)
