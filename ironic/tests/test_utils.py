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

import errno
import hashlib
import os
import os.path
import shutil
import tempfile
import uuid

import mock
import netaddr
from oslo.config import cfg
from oslo_concurrency import processutils
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
        with mock.patch.object(os, "unlink") as unlink_mock:
            unlink_mock.return_value = None
            utils.unlink_without_raise("/fake/path")
            unlink_mock.assert_called_once_with("/fake/path")

    def test_unlink_ENOENT(self):
        with mock.patch.object(os, "unlink") as unlink_mock:
            unlink_mock.side_effect = OSError(errno.ENOENT)
            utils.unlink_without_raise("/fake/path")
            unlink_mock.assert_called_once_with("/fake/path")

    def test_create_link(self):
        with mock.patch.object(os, "symlink") as symlink_mock:
            symlink_mock.return_value = None
            utils.create_link_without_raise("/fake/source", "/fake/link")
            symlink_mock.assert_called_once_with("/fake/source", "/fake/link")

    def test_create_link_EEXIST(self):
        with mock.patch.object(os, "symlink") as symlink_mock:
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
                                  process_input='foo',
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
                              process_input='foo',
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

    @mock.patch.object(processutils, 'execute')
    @mock.patch.object(os.environ, 'copy', return_value={})
    def test_execute_use_standard_locale_no_env_variables(self, env_mock,
                                                          execute_mock):
        utils.execute('foo', use_standard_locale=True)
        execute_mock.assert_called_once_with('foo',
                                             env_variables={'LC_ALL': 'C'})

    @mock.patch.object(processutils, 'execute')
    def test_execute_use_standard_locale_with_env_variables(self,
                                                            execute_mock):
        utils.execute('foo', use_standard_locale=True,
                      env_variables={'foo': 'bar'})
        execute_mock.assert_called_once_with('foo',
                                             env_variables={'LC_ALL': 'C',
                                                            'foo': 'bar'})

    @mock.patch.object(processutils, 'execute')
    def test_execute_not_use_standard_locale(self, execute_mock):
        utils.execute('foo', use_standard_locale=False,
                      env_variables={'foo': 'bar'})
        execute_mock.assert_called_once_with('foo',
                                             env_variables={'foo': 'bar'})

    def test_execute_get_root_helper(self):
        with mock.patch.object(processutils, 'execute') as execute_mock:
            helper = utils._get_root_helper()
            utils.execute('foo', run_as_root=True)
            execute_mock.assert_called_once_with('foo', run_as_root=True,
                                                 root_helper=helper)

    def test_execute_without_root_helper(self):
        with mock.patch.object(processutils, 'execute') as execute_mock:
            utils.execute('foo', run_as_root=False)
            execute_mock.assert_called_once_with('foo', run_as_root=False)


class GenericUtilsTestCase(base.TestCase):
    def test_hostname_unicode_sanitization(self):
        hostname = u"\u7684.test.example.com"
        self.assertEqual("test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_periods(self):
        hostname = "....test.example.com..."
        self.assertEqual("test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_dashes(self):
        hostname = "----test.example.com---"
        self.assertEqual("test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_characters(self):
        hostname = "(#@&$!(@*--#&91)(__=+--test-host.example!!.com-0+"
        self.assertEqual("91----test-host.example.com-0",
                         utils.sanitize_hostname(hostname))

    def test_hostname_translate(self):
        hostname = "<}\x1fh\x10e\x08l\x02l\x05o\x12!{>"
        self.assertEqual("hello", utils.sanitize_hostname(hostname))

    def test_read_cached_file(self):
        with mock.patch.object(os.path, "getmtime") as getmtime_mock:
            getmtime_mock.return_value = 1

            cache_data = {"data": 1123, "mtime": 1}
            data = utils.read_cached_file("/this/is/a/fake", cache_data)
            self.assertEqual(cache_data["data"], data)
            getmtime_mock.assert_called_once_with(mock.ANY)

    def test_read_modified_cached_file(self):
        with mock.patch.object(os.path, "getmtime") as getmtime_mock:
            with mock.patch.object(__builtin__, 'open') as open_mock:
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
        data = 'Mary had a little lamb, its fleece as white as snow'
        flo = six.StringIO(data)
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

    def test_is_valid_ipv4(self):
        self.assertTrue(utils.is_valid_ipv4('127.0.0.1'))
        self.assertFalse(utils.is_valid_ipv4('::1'))
        self.assertFalse(utils.is_valid_ipv4('bacon'))
        self.assertFalse(utils.is_valid_ipv4(""))
        self.assertFalse(utils.is_valid_ipv4(10))

    def test_is_valid_ipv6(self):
        self.assertTrue(utils.is_valid_ipv6("::1"))
        self.assertTrue(utils.is_valid_ipv6(
                            "abcd:ef01:2345:6789:abcd:ef01:192.168.254.254"))
        self.assertTrue(utils.is_valid_ipv6(
                                    "0000:0000:0000:0000:0000:0000:0000:0001"))
        self.assertFalse(utils.is_valid_ipv6("foo"))
        self.assertFalse(utils.is_valid_ipv6("127.0.0.1"))
        self.assertFalse(utils.is_valid_ipv6(""))
        self.assertFalse(utils.is_valid_ipv6(10))

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

    def test_validate_and_normalize_mac(self):
        mac = 'AA:BB:CC:DD:EE:FF'
        with mock.patch.object(utils, 'is_valid_mac') as m_mock:
            m_mock.return_value = True
            self.assertEqual(mac.lower(),
                             utils.validate_and_normalize_mac(mac))

    def test_validate_and_normalize_mac_invalid_format(self):
        with mock.patch.object(utils, 'is_valid_mac') as m_mock:
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


class MkfsTestCase(base.TestCase):

    @mock.patch.object(utils, 'execute')
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

    @mock.patch.object(utils, 'execute')
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

    @mock.patch.object(utils, 'execute',
                       side_effect=processutils.ProcessExecutionError(
                           stderr=os.strerror(errno.ENOENT)))
    def test_mkfs_with_unsupported_fs(self, execute_mock):
        self.assertRaises(exception.FileSystemNotSupported,
                          utils.mkfs, 'foo', '/my/block/dev')

    @mock.patch.object(utils, 'execute',
                       side_effect=processutils.ProcessExecutionError(
                           stderr='fake'))
    def test_mkfs_with_unexpected_error(self, execute_mock):
        self.assertRaises(processutils.ProcessExecutionError, utils.mkfs,
                          'ext4', '/my/block/dev', 'ext4-vol')


class IntLikeTestCase(base.TestCase):

    def test_is_int_like(self):
        self.assertTrue(utils.is_int_like(1))
        self.assertTrue(utils.is_int_like("1"))
        self.assertTrue(utils.is_int_like("514"))
        self.assertTrue(utils.is_int_like("0"))

        self.assertFalse(utils.is_int_like(1.1))
        self.assertFalse(utils.is_int_like("1.1"))
        self.assertFalse(utils.is_int_like("1.1.1"))
        self.assertFalse(utils.is_int_like(None))
        self.assertFalse(utils.is_int_like("0."))
        self.assertFalse(utils.is_int_like("aaaaaa"))
        self.assertFalse(utils.is_int_like("...."))
        self.assertFalse(utils.is_int_like("1g"))
        self.assertFalse(
            utils.is_int_like("0cc3346e-9fef-4445-abe6-5d2b2690ec64"))
        self.assertFalse(utils.is_int_like("a1"))


class UUIDTestCase(base.TestCase):

    def test_generate_uuid(self):
        uuid_string = utils.generate_uuid()
        self.assertIsInstance(uuid_string, str)
        self.assertEqual(36, len(uuid_string))
        # make sure there are 4 dashes
        self.assertEqual(32, len(uuid_string.replace('-', '')))

    def test_is_uuid_like(self):
        self.assertTrue(utils.is_uuid_like(str(uuid.uuid4())))

    def test_id_is_uuid_like(self):
        self.assertFalse(utils.is_uuid_like(1234567))

    def test_name_is_uuid_like(self):
        self.assertFalse(utils.is_uuid_like('zhongyueluo'))


class TempFilesTestCase(base.TestCase):

    def test_tempdir(self):

        dirname = None
        with utils.tempdir() as tempdir:
            self.assertTrue(os.path.isdir(tempdir))
            dirname = tempdir
        self.assertFalse(os.path.exists(dirname))

    @mock.patch.object(shutil, 'rmtree')
    @mock.patch.object(tempfile, 'mkdtemp')
    def test_tempdir_mocked(self, mkdtemp_mock, rmtree_mock):

        self.config(tempdir='abc')
        mkdtemp_mock.return_value = 'temp-dir'
        kwargs = {'a': 'b'}

        with utils.tempdir(**kwargs) as tempdir:
            self.assertEqual('temp-dir', tempdir)
            tempdir_created = tempdir

        mkdtemp_mock.assert_called_once_with(**kwargs)
        rmtree_mock.assert_called_once_with(tempdir_created)

    @mock.patch.object(utils, 'LOG')
    @mock.patch.object(shutil, 'rmtree')
    @mock.patch.object(tempfile, 'mkdtemp')
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
