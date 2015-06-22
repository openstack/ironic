# Copyright 2011 Justin Santa Barbara
# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

import datetime
import errno
import hashlib
import os
import os.path
import shutil
import tempfile

import mock
import netaddr
from oslo_concurrency import processutils
from oslo_config import cfg
import six
import six.moves.builtins as __builtin__

from ironic.common import exception
from ironic.common import utils
from ironic.tests import base

CONF = cfg.CONF


class BareMetalUtilsTestCase(base.TestCase):

    def test_random_alnum(self):
        s = utils.random_alnum(10)
        self.assertEqual(10, len(s))
        s = utils.random_alnum(100)
        self.assertEqual(100, len(s))

    def test_unlink(self):
        with mock.patch.object(os, "unlink", autospec=True) as unlink_mock:
            unlink_mock.return_value = None
            utils.unlink_without_raise("/fake/path")
            unlink_mock.assert_called_once_with("/fake/path")

    def test_unlink_ENOENT(self):
        with mock.patch.object(os, "unlink", autospec=True) as unlink_mock:
            unlink_mock.side_effect = OSError(errno.ENOENT)
            utils.unlink_without_raise("/fake/path")
            unlink_mock.assert_called_once_with("/fake/path")

    def test_create_link(self):
        with mock.patch.object(os, "symlink", autospec=True) as symlink_mock:
            symlink_mock.return_value = None
            utils.create_link_without_raise("/fake/source", "/fake/link")
            symlink_mock.assert_called_once_with("/fake/source", "/fake/link")

    def test_create_link_EEXIST(self):
        with mock.patch.object(os, "symlink", autospec=True) as symlink_mock:
            symlink_mock.side_effect = OSError(errno.EEXIST)
            utils.create_link_without_raise("/fake/source", "/fake/link")
            symlink_mock.assert_called_once_with("/fake/source", "/fake/link")


class ExecuteTestCase(base.TestCase):

    def test_retry_on_failure(self):
        fd, tmpfilename = tempfile.mkstemp()
        _, tmpfilename2 = tempfile.mkstemp()
        try:
            fp = os.fdopen(fd, 'w+')
            fp.write('''#!/bin/sh
# If stdin fails to get passed during one of the runs, make a note.
if ! grep -q foo
then
    echo 'failure' > "$1"
fi
# If stdin has failed to get passed during this or a previous run, exit early.
if grep failure "$1"
then
    exit 1
fi
runs="$(cat $1)"
if [ -z "$runs" ]
then
    runs=0
fi
runs=$(($runs + 1))
echo $runs > "$1"
exit 1
''')
            fp.close()
            os.chmod(tmpfilename, 0o755)
            try:
                self.assertRaises(processutils.ProcessExecutionError,
                                  utils.execute,
                                  tmpfilename, tmpfilename2, attempts=10,
                                  process_input=b'foo',
                                  delay_on_retry=False)
            except OSError as e:
                if e.errno == errno.EACCES:
                    self.skipTest("Permissions error detected. "
                                  "Are you running with a noexec /tmp?")
                else:
                    raise
            fp = open(tmpfilename2, 'r')
            runs = fp.read()
            fp.close()
            self.assertNotEqual(runs.strip(), 'failure', 'stdin did not '
                                'always get passed '
                                'correctly')
            runs = int(runs.strip())
            self.assertEqual(10, runs,
                             'Ran %d times instead of 10.' % (runs,))
        finally:
            os.unlink(tmpfilename)
            os.unlink(tmpfilename2)

    def test_unknown_kwargs_raises_error(self):
        self.assertRaises(processutils.UnknownArgumentError,
                          utils.execute,
                          '/usr/bin/env', 'true',
                          this_is_not_a_valid_kwarg=True)

    def test_check_exit_code_boolean(self):
        utils.execute('/usr/bin/env', 'false', check_exit_code=False)
        self.assertRaises(processutils.ProcessExecutionError,
                          utils.execute,
                          '/usr/bin/env', 'false', check_exit_code=True)

    def test_no_retry_on_success(self):
        fd, tmpfilename = tempfile.mkstemp()
        _, tmpfilename2 = tempfile.mkstemp()
        try:
            fp = os.fdopen(fd, 'w+')
            fp.write('''#!/bin/sh
# If we've already run, bail out.
grep -q foo "$1" && exit 1
# Mark that we've run before.
echo foo > "$1"
# Check that stdin gets passed correctly.
grep foo
''')
            fp.close()
            os.chmod(tmpfilename, 0o755)
            try:
                utils.execute(tmpfilename,
                              tmpfilename2,
                              process_input=b'foo',
                              attempts=2)
            except OSError as e:
                if e.errno == errno.EACCES:
                    self.skipTest("Permissions error detected. "
                                  "Are you running with a noexec /tmp?")
                else:
                    raise
        finally:
            os.unlink(tmpfilename)
            os.unlink(tmpfilename2)

    @mock.patch.object(processutils, 'execute', autospec=True)
    @mock.patch.object(os.environ, 'copy', return_value={}, autospec=True)
    def test_execute_use_standard_locale_no_env_variables(self, env_mock,
                                                          execute_mock):
        utils.execute('foo', use_standard_locale=True)
        execute_mock.assert_called_once_with('foo',
                                             env_variables={'LC_ALL': 'C'})

    @mock.patch.object(processutils, 'execute', autospec=True)
    def test_execute_use_standard_locale_with_env_variables(self,
                                                            execute_mock):
        utils.execute('foo', use_standard_locale=True,
                      env_variables={'foo': 'bar'})
        execute_mock.assert_called_once_with('foo',
                                             env_variables={'LC_ALL': 'C',
                                                            'foo': 'bar'})

    @mock.patch.object(processutils, 'execute', autospec=True)
    def test_execute_not_use_standard_locale(self, execute_mock):
        utils.execute('foo', use_standard_locale=False,
                      env_variables={'foo': 'bar'})
        execute_mock.assert_called_once_with('foo',
                                             env_variables={'foo': 'bar'})

    def test_execute_get_root_helper(self):
        with mock.patch.object(
                processutils, 'execute', autospec=True) as execute_mock:
            helper = utils._get_root_helper()
            utils.execute('foo', run_as_root=True)
            execute_mock.assert_called_once_with('foo', run_as_root=True,
                                                 root_helper=helper)

    def test_execute_without_root_helper(self):
        with mock.patch.object(
                processutils, 'execute', autospec=True) as execute_mock:
            utils.execute('foo', run_as_root=False)
            execute_mock.assert_called_once_with('foo', run_as_root=False)


class GenericUtilsTestCase(base.TestCase):
    def test_hostname_unicode_sanitization(self):
        hostname = u"\u7684.test.example.com"
        self.assertEqual(b"test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_periods(self):
        hostname = "....test.example.com..."
        self.assertEqual(b"test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_dashes(self):
        hostname = "----test.example.com---"
        self.assertEqual(b"test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_characters(self):
        hostname = "(#@&$!(@*--#&91)(__=+--test-host.example!!.com-0+"
        self.assertEqual(b"91----test-host.example.com-0",
                         utils.sanitize_hostname(hostname))

    def test_hostname_translate(self):
        hostname = "<}\x1fh\x10e\x08l\x02l\x05o\x12!{>"
        self.assertEqual(b"hello", utils.sanitize_hostname(hostname))

    def test_read_cached_file(self):
        with mock.patch.object(
                os.path, "getmtime", autospec=True) as getmtime_mock:
            getmtime_mock.return_value = 1

            cache_data = {"data": 1123, "mtime": 1}
            data = utils.read_cached_file("/this/is/a/fake", cache_data)
            self.assertEqual(cache_data["data"], data)
            getmtime_mock.assert_called_once_with(mock.ANY)

    def test_read_modified_cached_file(self):
        with mock.patch.object(
                os.path, "getmtime", autospec=True) as getmtime_mock:
            with mock.patch.object(
                    __builtin__, 'open', autospec=True) as open_mock:
                getmtime_mock.return_value = 2
                fake_contents = "lorem ipsum"
                fake_file = mock.Mock()
                fake_file.read.return_value = fake_contents
                fake_context_manager = mock.MagicMock()
                fake_context_manager.__enter__.return_value = fake_file
                fake_context_manager.__exit__.return_value = None
                open_mock.return_value = fake_context_manager

                cache_data = {"data": 1123, "mtime": 1}
                self.reload_called = False

                def test_reload(reloaded_data):
                    self.assertEqual(fake_contents, reloaded_data)
                    self.reload_called = True

                data = utils.read_cached_file("/this/is/a/fake",
                                              cache_data,
                                              reload_func=test_reload)

                self.assertEqual(fake_contents, data)
                self.assertTrue(self.reload_called)
                getmtime_mock.assert_called_once_with(mock.ANY)
                open_mock.assert_called_once_with(mock.ANY)
                fake_file.read.assert_called_once_with()
                fake_context_manager.__exit__.assert_called_once_with(mock.ANY,
                                                                      mock.ANY,
                                                                      mock.ANY)
                fake_context_manager.__enter__.assert_called_once_with()

    def test_hash_file(self):
        data = b'Mary had a little lamb, its fleece as white as snow'
        flo = six.BytesIO(data)
        h1 = utils.hash_file(flo)
        h2 = hashlib.sha1(data).hexdigest()
        self.assertEqual(h1, h2)

    def test_is_valid_boolstr(self):
        self.assertTrue(utils.is_valid_boolstr('true'))
        self.assertTrue(utils.is_valid_boolstr('false'))
        self.assertTrue(utils.is_valid_boolstr('yes'))
        self.assertTrue(utils.is_valid_boolstr('no'))
        self.assertTrue(utils.is_valid_boolstr('y'))
        self.assertTrue(utils.is_valid_boolstr('n'))
        self.assertTrue(utils.is_valid_boolstr('1'))
        self.assertTrue(utils.is_valid_boolstr('0'))

        self.assertFalse(utils.is_valid_boolstr('maybe'))
        self.assertFalse(utils.is_valid_boolstr('only on tuesdays'))

    def test_is_valid_ipv6_cidr(self):
        self.assertTrue(utils.is_valid_ipv6_cidr("2600::/64"))
        self.assertTrue(utils.is_valid_ipv6_cidr(
            "abcd:ef01:2345:6789:abcd:ef01:192.168.254.254/48"))
        self.assertTrue(utils.is_valid_ipv6_cidr(
            "0000:0000:0000:0000:0000:0000:0000:0001/32"))
        self.assertTrue(utils.is_valid_ipv6_cidr(
            "0000:0000:0000:0000:0000:0000:0000:0001"))
        self.assertFalse(utils.is_valid_ipv6_cidr("foo"))
        self.assertFalse(utils.is_valid_ipv6_cidr("127.0.0.1"))

    def test_get_shortened_ipv6(self):
        self.assertEqual("abcd:ef01:2345:6789:abcd:ef01:c0a8:fefe",
                         utils.get_shortened_ipv6(
                             "abcd:ef01:2345:6789:abcd:ef01:192.168.254.254"))
        self.assertEqual("::1", utils.get_shortened_ipv6(
            "0000:0000:0000:0000:0000:0000:0000:0001"))
        self.assertEqual("caca::caca:0:babe:201:102",
                         utils.get_shortened_ipv6(
                             "caca:0000:0000:caca:0000:babe:0201:0102"))
        self.assertRaises(netaddr.AddrFormatError, utils.get_shortened_ipv6,
                          "127.0.0.1")
        self.assertRaises(netaddr.AddrFormatError, utils.get_shortened_ipv6,
                          "failure")

    def test_get_shortened_ipv6_cidr(self):
        self.assertEqual("2600::/64", utils.get_shortened_ipv6_cidr(
            "2600:0000:0000:0000:0000:0000:0000:0000/64"))
        self.assertEqual("2600::/64", utils.get_shortened_ipv6_cidr(
            "2600::1/64"))
        self.assertRaises(netaddr.AddrFormatError,
                          utils.get_shortened_ipv6_cidr,
                          "127.0.0.1")
        self.assertRaises(netaddr.AddrFormatError,
                          utils.get_shortened_ipv6_cidr,
                          "failure")

    def test_is_valid_mac(self):
        self.assertTrue(utils.is_valid_mac("52:54:00:cf:2d:31"))
        self.assertTrue(utils.is_valid_mac(u"52:54:00:cf:2d:31"))
        self.assertFalse(utils.is_valid_mac("127.0.0.1"))
        self.assertFalse(utils.is_valid_mac("not:a:mac:address"))
        self.assertFalse(utils.is_valid_mac("52-54-00-cf-2d-31"))
        self.assertFalse(utils.is_valid_mac("aa bb cc dd ee ff"))
        self.assertTrue(utils.is_valid_mac("AA:BB:CC:DD:EE:FF"))
        self.assertFalse(utils.is_valid_mac("AA BB CC DD EE FF"))
        self.assertFalse(utils.is_valid_mac("AA-BB-CC-DD-EE-FF"))

    def test_is_hostname_safe(self):
        self.assertTrue(utils.is_hostname_safe('spam'))
        self.assertFalse(utils.is_hostname_safe('spAm'))
        self.assertFalse(utils.is_hostname_safe('SPAM'))
        self.assertFalse(utils.is_hostname_safe('-spam'))
        self.assertFalse(utils.is_hostname_safe('spam-'))
        self.assertTrue(utils.is_hostname_safe('spam-eggs'))
        self.assertFalse(utils.is_hostname_safe('spam_eggs'))
        self.assertFalse(utils.is_hostname_safe('spam eggs'))
        self.assertTrue(utils.is_hostname_safe('spam.eggs'))
        self.assertTrue(utils.is_hostname_safe('9spam'))
        self.assertTrue(utils.is_hostname_safe('spam7'))
        self.assertTrue(utils.is_hostname_safe('br34kf4st'))
        self.assertFalse(utils.is_hostname_safe('$pam'))
        self.assertFalse(utils.is_hostname_safe('egg$'))
        self.assertFalse(utils.is_hostname_safe('spam#eggs'))
        self.assertFalse(utils.is_hostname_safe(' eggs'))
        self.assertFalse(utils.is_hostname_safe('spam '))
        self.assertTrue(utils.is_hostname_safe('s'))
        self.assertTrue(utils.is_hostname_safe('s' * 63))
        self.assertFalse(utils.is_hostname_safe('s' * 64))
        self.assertFalse(utils.is_hostname_safe(''))
        self.assertFalse(utils.is_hostname_safe(None))
        # Need to ensure a binary response for success or fail
        self.assertIsNotNone(utils.is_hostname_safe('spam'))
        self.assertIsNotNone(utils.is_hostname_safe('-spam'))
        self.assertTrue(utils.is_hostname_safe('www.rackspace.com'))
        self.assertTrue(utils.is_hostname_safe('www.rackspace.com.'))
        self.assertTrue(utils.is_hostname_safe('http._sctp.www.example.com'))
        self.assertTrue(utils.is_hostname_safe('mail.pets_r_us.net'))
        self.assertTrue(utils.is_hostname_safe('mail-server-15.my_host.org'))
        self.assertFalse(utils.is_hostname_safe('www.nothere.com_'))
        self.assertFalse(utils.is_hostname_safe('www.nothere_.com'))
        self.assertFalse(utils.is_hostname_safe('www..nothere.com'))
        long_str = 'a' * 63 + '.' + 'b' * 63 + '.' + 'c' * 63 + '.' + 'd' * 63
        self.assertTrue(utils.is_hostname_safe(long_str))
        self.assertFalse(utils.is_hostname_safe(long_str + '.'))
        self.assertFalse(utils.is_hostname_safe('a' * 255))

    def test_is_valid_logical_name(self):
        valid = (
            'spam', 'spAm', 'SPAM', 'spam-eggs', 'spam.eggs', 'spam_eggs',
            'spam~eggs', '9spam', 'spam7', '~spam', '.spam', '.~-_', '~',
            'br34kf4st', 's', 's' * 63, 's' * 255)
        invalid = (
            ' ', 'spam eggs', '$pam', 'egg$', 'spam#eggs',
            ' eggs', 'spam ', '', None, 'spam%20')

        for hostname in valid:
            result = utils.is_valid_logical_name(hostname)
            # Need to ensure a binary response for success. assertTrue
            # is too generous, and would pass this test if, for
            # instance, a regex Match object were returned.
            self.assertIs(result, True,
                          "%s is unexpectedly invalid" % hostname)

        for hostname in invalid:
            result = utils.is_valid_logical_name(hostname)
            # Need to ensure a binary response for
            # success. assertFalse is too generous and would pass this
            # test if None were returned.
            self.assertIs(result, False,
                          "%s is unexpectedly valid" % hostname)

    def test_validate_and_normalize_mac(self):
        mac = 'AA:BB:CC:DD:EE:FF'
        with mock.patch.object(utils, 'is_valid_mac', autospec=True) as m_mock:
            m_mock.return_value = True
            self.assertEqual(mac.lower(),
                             utils.validate_and_normalize_mac(mac))

    def test_validate_and_normalize_mac_invalid_format(self):
        with mock.patch.object(utils, 'is_valid_mac', autospec=True) as m_mock:
            m_mock.return_value = False
            self.assertRaises(exception.InvalidMAC,
                              utils.validate_and_normalize_mac, 'invalid-mac')

    def test_safe_rstrip(self):
        value = '/test/'
        rstripped_value = '/test'
        not_rstripped = '/'

        self.assertEqual(rstripped_value, utils.safe_rstrip(value, '/'))
        self.assertEqual(not_rstripped, utils.safe_rstrip(not_rstripped, '/'))

    def test_safe_rstrip_not_raises_exceptions(self):
        # Supplying an integer should normally raise an exception because it
        # does not save the rstrip() method.
        value = 10

        # In the case of raising an exception safe_rstrip() should return the
        # original value.
        self.assertEqual(value, utils.safe_rstrip(value))

    @mock.patch.object(os.path, 'getmtime', return_value=1439465889.4964755,
                       autospec=True)
    def test_unix_file_modification_datetime(self, mtime_mock):
        expected = datetime.datetime(2015, 8, 13, 11, 38, 9, 496475)
        self.assertEqual(expected,
                         utils.unix_file_modification_datetime('foo'))
        mtime_mock.assert_called_once_with('foo')


class MkfsTestCase(base.TestCase):

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_mkfs(self, execute_mock):
        utils.mkfs('ext4', '/my/block/dev')
        utils.mkfs('msdos', '/my/msdos/block/dev')
        utils.mkfs('swap', '/my/swap/block/dev')

        expected = [mock.call('mkfs', '-t', 'ext4', '-F', '/my/block/dev',
                              run_as_root=True,
                              use_standard_locale=True),
                    mock.call('mkfs', '-t', 'msdos', '/my/msdos/block/dev',
                              run_as_root=True,
                              use_standard_locale=True),
                    mock.call('mkswap', '/my/swap/block/dev',
                              run_as_root=True,
                              use_standard_locale=True)]
        self.assertEqual(expected, execute_mock.call_args_list)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_mkfs_with_label(self, execute_mock):
        utils.mkfs('ext4', '/my/block/dev', 'ext4-vol')
        utils.mkfs('msdos', '/my/msdos/block/dev', 'msdos-vol')
        utils.mkfs('swap', '/my/swap/block/dev', 'swap-vol')

        expected = [mock.call('mkfs', '-t', 'ext4', '-F', '-L', 'ext4-vol',
                              '/my/block/dev', run_as_root=True,
                              use_standard_locale=True),
                    mock.call('mkfs', '-t', 'msdos', '-n', 'msdos-vol',
                              '/my/msdos/block/dev', run_as_root=True,
                              use_standard_locale=True),
                    mock.call('mkswap', '-L', 'swap-vol',
                              '/my/swap/block/dev', run_as_root=True,
                              use_standard_locale=True)]
        self.assertEqual(expected, execute_mock.call_args_list)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_mkfs_with_unsupported_fs(self, execute_mock):
        execute_mock.side_effect = iter([processutils.ProcessExecutionError(
            stderr=os.strerror(errno.ENOENT))])
        self.assertRaises(exception.FileSystemNotSupported,
                          utils.mkfs, 'foo', '/my/block/dev')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_mkfs_with_unexpected_error(self, execute_mock):
        execute_mock.side_effect = iter([processutils.ProcessExecutionError(
            stderr='fake')])
        self.assertRaises(processutils.ProcessExecutionError, utils.mkfs,
                          'ext4', '/my/block/dev', 'ext4-vol')


class TempFilesTestCase(base.TestCase):

    def test_tempdir(self):

        dirname = None
        with utils.tempdir() as tempdir:
            self.assertTrue(os.path.isdir(tempdir))
            dirname = tempdir
        self.assertFalse(os.path.exists(dirname))

    @mock.patch.object(shutil, 'rmtree', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    def test_tempdir_mocked(self, mkdtemp_mock, rmtree_mock):

        self.config(tempdir='abc')
        mkdtemp_mock.return_value = 'temp-dir'
        kwargs = {'dir': 'b'}

        with utils.tempdir(**kwargs) as tempdir:
            self.assertEqual('temp-dir', tempdir)
            tempdir_created = tempdir

        mkdtemp_mock.assert_called_once_with(**kwargs)
        rmtree_mock.assert_called_once_with(tempdir_created)

    @mock.patch.object(utils, 'LOG', autospec=True)
    @mock.patch.object(shutil, 'rmtree', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    def test_tempdir_mocked_error_on_rmtree(self, mkdtemp_mock, rmtree_mock,
                                            log_mock):

        self.config(tempdir='abc')
        mkdtemp_mock.return_value = 'temp-dir'
        rmtree_mock.side_effect = OSError

        with utils.tempdir() as tempdir:
            self.assertEqual('temp-dir', tempdir)
            tempdir_created = tempdir

        rmtree_mock.assert_called_once_with(tempdir_created)
        self.assertTrue(log_mock.error.called)

    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(utils, '_check_dir_writable', autospec=True)
    @mock.patch.object(utils, '_check_dir_free_space', autospec=True)
    def test_check_dir_with_pass_in(self, mock_free_space, mock_dir_writable,
                                    mock_exists):
        mock_exists.return_value = True
        # test passing in a directory and size
        utils.check_dir(directory_to_check='/fake/path', required_space=5)
        mock_exists.assert_called_once_with('/fake/path')
        mock_dir_writable.assert_called_once_with('/fake/path')
        mock_free_space.assert_called_once_with('/fake/path', 5)

    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(utils, '_check_dir_writable', autospec=True)
    @mock.patch.object(utils, '_check_dir_free_space', autospec=True)
    def test_check_dir_no_dir(self, mock_free_space, mock_dir_writable,
                              mock_exists):
        mock_exists.return_value = False
        self.config(tempdir='/fake/path')
        self.assertRaises(exception.PathNotFound, utils.check_dir)
        mock_exists.assert_called_once_with(CONF.tempdir)
        self.assertFalse(mock_free_space.called)
        self.assertFalse(mock_dir_writable.called)

    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(utils, '_check_dir_writable', autospec=True)
    @mock.patch.object(utils, '_check_dir_free_space', autospec=True)
    def test_check_dir_ok(self, mock_free_space, mock_dir_writable,
                          mock_exists):
        mock_exists.return_value = True
        self.config(tempdir='/fake/path')
        utils.check_dir()
        mock_exists.assert_called_once_with(CONF.tempdir)
        mock_dir_writable.assert_called_once_with(CONF.tempdir)
        mock_free_space.assert_called_once_with(CONF.tempdir, 1)

    @mock.patch.object(os, 'access', autospec=True)
    def test__check_dir_writable_ok(self, mock_access):
        mock_access.return_value = True
        self.assertIsNone(utils._check_dir_writable("/fake/path"))
        mock_access.assert_called_once_with("/fake/path", os.W_OK)

    @mock.patch.object(os, 'access', autospec=True)
    def test__check_dir_writable_not_writable(self, mock_access):
        mock_access.return_value = False

        self.assertRaises(exception.DirectoryNotWritable,
                          utils._check_dir_writable, "/fake/path")
        mock_access.assert_called_once_with("/fake/path", os.W_OK)

    @mock.patch.object(os, 'statvfs', autospec=True)
    def test__check_dir_free_space_ok(self, mock_stat):
        statvfs_mock_return = mock.MagicMock()
        statvfs_mock_return.f_bsize = 5
        statvfs_mock_return.f_frsize = 0
        statvfs_mock_return.f_blocks = 0
        statvfs_mock_return.f_bfree = 0
        statvfs_mock_return.f_bavail = 1024 * 1024
        statvfs_mock_return.f_files = 0
        statvfs_mock_return.f_ffree = 0
        statvfs_mock_return.f_favail = 0
        statvfs_mock_return.f_flag = 0
        statvfs_mock_return.f_namemax = 0
        mock_stat.return_value = statvfs_mock_return
        utils._check_dir_free_space("/fake/path")
        mock_stat.assert_called_once_with("/fake/path")

    @mock.patch.object(os, 'statvfs', autospec=True)
    def test_check_dir_free_space_raises(self, mock_stat):
        statvfs_mock_return = mock.MagicMock()
        statvfs_mock_return.f_bsize = 1
        statvfs_mock_return.f_frsize = 0
        statvfs_mock_return.f_blocks = 0
        statvfs_mock_return.f_bfree = 0
        statvfs_mock_return.f_bavail = 1024
        statvfs_mock_return.f_files = 0
        statvfs_mock_return.f_ffree = 0
        statvfs_mock_return.f_favail = 0
        statvfs_mock_return.f_flag = 0
        statvfs_mock_return.f_namemax = 0
        mock_stat.return_value = statvfs_mock_return

        self.assertRaises(exception.InsufficientDiskSpace,
                          utils._check_dir_free_space, "/fake/path")
        mock_stat.assert_called_once_with("/fake/path")


class IsHttpUrlTestCase(base.TestCase):

    def test_is_http_url(self):
        self.assertTrue(utils.is_http_url('http://127.0.0.1'))
        self.assertTrue(utils.is_http_url('https://127.0.0.1'))
        self.assertTrue(utils.is_http_url('HTTP://127.1.2.3'))
        self.assertTrue(utils.is_http_url('HTTPS://127.3.2.1'))
        self.assertFalse(utils.is_http_url('Zm9vYmFy'))
        self.assertFalse(utils.is_http_url('11111111'))


class GetUpdatedCapabilitiesTestCase(base.TestCase):

    def test_get_updated_capabilities(self):
        capabilities = {'ilo_firmware_version': 'xyz'}
        cap_string = 'ilo_firmware_version:xyz'
        cap_returned = utils.get_updated_capabilities(None, capabilities)
        self.assertEqual(cap_string, cap_returned)
        self.assertIsInstance(cap_returned, str)

    def test_get_updated_capabilities_multiple_keys(self):
        capabilities = {'ilo_firmware_version': 'xyz',
                        'foo': 'bar', 'somekey': 'value'}
        cap_string = 'ilo_firmware_version:xyz,foo:bar,somekey:value'
        cap_returned = utils.get_updated_capabilities(None, capabilities)
        set1 = set(cap_string.split(','))
        set2 = set(cap_returned.split(','))
        self.assertEqual(set1, set2)
        self.assertIsInstance(cap_returned, str)

    def test_get_updated_capabilities_invalid_capabilities(self):
        capabilities = 'ilo_firmware_version'
        self.assertRaises(ValueError,
                          utils.get_updated_capabilities,
                          capabilities, {})

    def test_get_updated_capabilities_capabilities_not_dict(self):
        capabilities = ['ilo_firmware_version:xyz', 'foo:bar']
        self.assertRaises(ValueError,
                          utils.get_updated_capabilities,
                          None, capabilities)

    def test_get_updated_capabilities_add_to_existing_capabilities(self):
        new_capabilities = {'BootMode': 'uefi'}
        expected_capabilities = 'BootMode:uefi,foo:bar'
        cap_returned = utils.get_updated_capabilities('foo:bar',
                                                      new_capabilities)
        set1 = set(expected_capabilities.split(','))
        set2 = set(cap_returned.split(','))
        self.assertEqual(set1, set2)
        self.assertIsInstance(cap_returned, str)

    def test_get_updated_capabilities_replace_to_existing_capabilities(self):
        new_capabilities = {'BootMode': 'bios'}
        expected_capabilities = 'BootMode:bios'
        cap_returned = utils.get_updated_capabilities('BootMode:uefi',
                                                      new_capabilities)
        set1 = set(expected_capabilities.split(','))
        set2 = set(cap_returned.split(','))
        self.assertEqual(set1, set2)
        self.assertIsInstance(cap_returned, str)
