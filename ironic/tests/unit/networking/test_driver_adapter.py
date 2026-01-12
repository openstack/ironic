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

"""Unit tests for ironic.networking.switch_drivers.driver_adapter"""

import os
from unittest import mock

import fixtures
from oslo_config import cfg

from ironic.common import exception
from ironic.drivers.modules.switch.base import BaseTranslator
from ironic.drivers.modules.switch.base import NoOpSwitchDriver
from ironic.networking.switch_drivers import driver_adapter
from ironic.tests import base


CONF = cfg.CONF


class NetworkingDriverAdapterTestCase(base.TestCase):
    """Test cases for NetworkingDriverAdapter class."""
    switch_config_path = None
    output_config_path = None
    adapter = None

    def setUp(self):
        super(NetworkingDriverAdapterTestCase, self).setUp()
        temp_dir = self.useFixture(fixtures.TempDir()).path
        self.switch_config_path = os.path.join(temp_dir, 'switch.conf')
        with open(self.switch_config_path, 'w', encoding='utf-8') as config_fp:
            config_fp.write('[DEFAULT]\n')
        self.output_config_path = os.path.join(temp_dir, 'driver.conf')
        self.config(group='ironic_networking',
                    switch_config_file=self.switch_config_path)
        self.config(group='ironic_networking', driver_config_dir=temp_dir)
        fake_drivers = {'noop': NoOpSwitchDriver()}
        self.adapter = driver_adapter.NetworkingDriverAdapter(fake_drivers)

    def test___init__(self):
        """Test NetworkingDriverAdapter initialization."""
        test_drivers = {'noop': NoOpSwitchDriver()}
        adapter = driver_adapter.NetworkingDriverAdapter(test_drivers)
        # Translators are registered during initialization
        self.assertIn('noop', adapter.driver_translators)
        self.assertIsInstance(
            adapter.driver_translators['noop'],
            BaseTranslator
        )

    @mock.patch.object(driver_adapter.NetworkingDriverAdapter,
                       'register_translator', autospec=True)
    def test__register_translators(self, mock_register):
        """Test _register_translators method."""
        # __init__ calls _register_translators, which calls register_translator
        test_drivers = {'noop': NoOpSwitchDriver()}
        adapter = driver_adapter.NetworkingDriverAdapter(test_drivers)

        # Should be called once during __init__
        mock_register.assert_called_once_with(
            adapter, 'noop', mock.ANY)
        # Verify the translator instance is correct type
        call_args = mock_register.call_args[0]
        self.assertIsInstance(call_args[2], BaseTranslator)

    def test_register_translator(self):
        """Test register_translator method."""
        mock_translator = mock.Mock()

        self.adapter.register_translator('test_driver', mock_translator)

        self.assertEqual(mock_translator,
                         self.adapter.driver_translators['test_driver'])

    @mock.patch.object(driver_adapter.NetworkingDriverAdapter,
                       '_write_config_file', autospec=True)
    @mock.patch.object(driver_adapter.NetworkingDriverAdapter,
                       '_extract_switch_sections', autospec=True)
    @mock.patch.object(CONF, 'reload_config_files', autospec=True)
    def test_preprocess_config_success(self, mock_reload, mock_extract,
                                       mock_write):
        """Test preprocess_config method with successful translation."""
        # Setup mock data
        mock_extract.return_value = {
            'switch1': {
                'driver_type': 'generic-switch',
                'device_type': 'netmiko_cisco_ios',
                'address': '192.168.1.1',
                'username': 'admin',
                'password': 'secret',
                'mac_address': '00:11:22:33:44:55'
            }
        }

        mock_translator = mock.Mock()
        mock_translator.translate_config.return_value = {
            'genericswitch:switch1': {
                'ip': '192.168.1.1',
                'username': 'admin'
            }
        }
        self.adapter.driver_translators['generic-switch'] = mock_translator

        result = self.adapter.preprocess_config(self.output_config_path)

        self.assertEqual(1, result)
        mock_extract.assert_called_once()
        mock_translator.translate_config.assert_called_once_with(
            'switch1', {
                'driver_type': 'generic-switch',
                'device_type': 'netmiko_cisco_ios',
                'address': '192.168.1.1',
                'username': 'admin',
                'password': 'secret',
                'mac_address': '00:11:22:33:44:55'
            })
        mock_write.assert_called_once_with(
            self.adapter,
            self.output_config_path,
            {'genericswitch:switch1': {
                'ip': '192.168.1.1',
                'username': 'admin'
            }}
        )
        mock_reload.assert_called_once()

    @mock.patch(
        'ironic.networking.switch_drivers.driver_adapter.os.path.exists',
        autospec=True)
    def test_preprocess_config_missing_config_file(self, mock_exists):
        """Raise NetworkError when switch config file is absent."""
        mock_exists.return_value = False

        self.assertRaises(
            exception.NetworkError,
            self.adapter.preprocess_config,
            self.output_config_path,
        )
        mock_exists.assert_called_once_with(self.switch_config_path)

    @mock.patch.object(driver_adapter.NetworkingDriverAdapter,
                       '_extract_switch_sections', autospec=True)
    def test_preprocess_config_no_switches(self, mock_extract):
        """Test preprocess_config method with no switch sections."""
        mock_extract.return_value = {}

        result = self.adapter.preprocess_config(self.output_config_path)

        self.assertEqual(0, result)

    @mock.patch.object(driver_adapter.NetworkingDriverAdapter,
                       '_extract_switch_sections', autospec=True)
    def test_preprocess_config_translator_error(self, mock_extract):
        """Translator failure should bubble up as NetworkError."""
        mock_extract.return_value = {
            'switch1': {
                'driver_type': 'generic-switch',
                'device_type': 'netmiko_cisco_ios',
                'address': '10.0.0.1',
                'username': 'admin',
                'password': 'secret',
                'mac_address': '00:11:22:33:44:55'
            }
        }
        broken = mock.Mock()
        broken.translate_config.side_effect = RuntimeError('boom')
        self.adapter.driver_translators['generic-switch'] = broken

        with mock.patch.object(CONF, 'reload_config_files', autospec=True):
            self.assertRaises(
                exception.NetworkError,
                self.adapter.preprocess_config,
                self.output_config_path,
            )
        mock_extract.assert_called_once()

    def test__validate_switch_config_valid_with_password(self):
        """Test _validate_switch_config with valid config using password."""
        config = {
            'driver_type': 'generic-switch',
            'device_type': 'netmiko_cisco_ios',
            'address': '192.168.1.1',
            'username': 'admin',
            'password': 'secret',
            'mac_address': '00:11:22:33:44:55'
        }
        # Should not raise
        self.adapter._validate_switch_config('switch1', config)

    def test__validate_switch_config_valid_with_key_file(self):
        """Test _validate_switch_config with valid config using key_file."""
        config = {
            'driver_type': 'generic-switch',
            'device_type': 'netmiko_cisco_ios',
            'address': '192.168.1.1',
            'username': 'admin',
            'key_file': '/path/to/key',
            'mac_address': '00:11:22:33:44:55'
        }
        # Should not raise
        self.adapter._validate_switch_config('switch1', config)

    def test__validate_switch_config_missing_driver_type(self):
        """Test _validate_switch_config with missing driver_type."""
        config = {
            'device_type': 'netmiko_cisco_ios',
            'address': '192.168.1.1',
            'username': 'admin',
            'password': 'secret',
            'mac_address': '00:11:22:33:44:55'
        }
        exc = self.assertRaises(
            exception.NetworkError,
            self.adapter._validate_switch_config,
            'switch1',
            config
        )
        self.assertIn('driver_type', str(exc))
        self.assertIn('switch1', str(exc))

    def test__validate_switch_config_missing_device_type(self):
        """Test _validate_switch_config with missing device_type."""
        config = {
            'driver_type': 'generic-switch',
            'address': '192.168.1.1',
            'username': 'admin',
            'password': 'secret',
            'mac_address': '00:11:22:33:44:55'
        }
        exc = self.assertRaises(
            exception.NetworkError,
            self.adapter._validate_switch_config,
            'switch1',
            config
        )
        self.assertIn('device_type', str(exc))

    def test__validate_switch_config_missing_address(self):
        """Test _validate_switch_config with missing address."""
        config = {
            'driver_type': 'generic-switch',
            'device_type': 'netmiko_cisco_ios',
            'username': 'admin',
            'password': 'secret',
            'mac_address': '00:11:22:33:44:55'
        }
        exc = self.assertRaises(
            exception.NetworkError,
            self.adapter._validate_switch_config,
            'switch1',
            config
        )
        self.assertIn('address', str(exc))

    def test__validate_switch_config_missing_username(self):
        """Test _validate_switch_config with missing username."""
        config = {
            'driver_type': 'generic-switch',
            'device_type': 'netmiko_cisco_ios',
            'address': '192.168.1.1',
            'password': 'secret',
            'mac_address': '00:11:22:33:44:55'
        }
        exc = self.assertRaises(
            exception.NetworkError,
            self.adapter._validate_switch_config,
            'switch1',
            config
        )
        self.assertIn('username', str(exc))

    def test__validate_switch_config_missing_mac_address(self):
        """Test _validate_switch_config with missing mac_address."""
        config = {
            'driver_type': 'generic-switch',
            'device_type': 'netmiko_cisco_ios',
            'address': '192.168.1.1',
            'username': 'admin',
            'password': 'secret'
        }
        exc = self.assertRaises(
            exception.NetworkError,
            self.adapter._validate_switch_config,
            'switch1',
            config
        )
        self.assertIn('mac_address', str(exc))

    def test__validate_switch_config_missing_authentication(self):
        """Test _validate_switch_config with no password or key_file."""
        config = {
            'driver_type': 'generic-switch',
            'device_type': 'netmiko_cisco_ios',
            'address': '192.168.1.1',
            'username': 'admin',
            'mac_address': '00:11:22:33:44:55'
        }
        exc = self.assertRaises(
            exception.NetworkError,
            self.adapter._validate_switch_config,
            'switch1',
            config
        )
        self.assertIn('password', str(exc))
        self.assertIn('key_file', str(exc))

    def test__validate_switch_config_multiple_missing_fields(self):
        """Test _validate_switch_config with multiple missing fields."""
        config = {
            'driver_type': 'generic-switch',
        }
        exc = self.assertRaises(
            exception.NetworkError,
            self.adapter._validate_switch_config,
            'switch1',
            config
        )
        error_msg = str(exc)
        self.assertIn('device_type', error_msg)
        self.assertIn('address', error_msg)
        self.assertIn('username', error_msg)
        self.assertIn('mac_address', error_msg)
        self.assertIn('password', error_msg)
        self.assertIn('key_file', error_msg)

    @mock.patch.object(driver_adapter.NetworkingDriverAdapter,
                       '_extract_switch_sections', autospec=True)
    def test_preprocess_config_empty_translation(self, mock_extract):
        """Test preprocess_config with empty translation result."""
        mock_extract.return_value = {
            'switch1': {
                'driver_type': 'generic-switch',
                'device_type': 'netmiko_cisco_ios',
                'address': '192.168.1.1',
                'username': 'admin',
                'password': 'secret',
                'mac_address': '00:11:22:33:44:55'
            }
        }

        mock_translator = mock.Mock()
        mock_translator.translate_config.return_value = {}
        self.adapter.driver_translators['generic-switch'] = mock_translator

        result = self.adapter.preprocess_config(self.output_config_path)

        self.assertEqual(0, result)

    @mock.patch.object(driver_adapter.NetworkingDriverAdapter,
                       '_extract_switch_sections', autospec=True)
    def test_preprocess_config_exception(self, mock_extract):
        """Test preprocess_config method with exception."""
        mock_extract.side_effect = Exception("Test error")

        self.assertRaises(exception.NetworkError,
                          self.adapter.preprocess_config,
                          self.output_config_path)

    @mock.patch.object(driver_adapter.NetworkingDriverAdapter,
                       '_extract_switch_sections', autospec=True)
    def test_preprocess_config_unknown_driver_type(self, mock_extract):
        """Test preprocess_config with unknown driver type."""
        mock_extract.return_value = {
            'switch1': {
                'driver_type': 'unknown_driver',
                'device_type': 'netmiko_cisco_ios',
                'address': '192.168.1.1',
                'username': 'admin',
                'password': 'secret',
                'mac_address': '00:11:22:33:44:55'
            }
        }

        # No translator registered for 'unknown_driver'
        # Should fail validation before reaching translator
        self.assertRaises(exception.NetworkError,
                          self.adapter.preprocess_config,
                          self.output_config_path)

    @mock.patch.object(driver_adapter.NetworkingDriverAdapter,
                       '_extract_switch_sections', autospec=True)
    def test_preprocess_config_validation_fails(self, mock_extract):
        """Test preprocess_config with validation failure."""
        mock_extract.return_value = {
            'switch1': {
                'driver_type': 'generic-switch',
                # Missing required fields
                'address': '192.168.1.1'
            }
        }

        # Should fail validation before reaching translator
        self.assertRaises(exception.NetworkError,
                          self.adapter.preprocess_config,
                          self.output_config_path)

    @mock.patch('glob.glob', autospec=True)
    def test__config_files_with_config_dir(self, mock_glob):
        """Test _config_files method with config directories."""
        # Setup CONF mock
        CONF.config_file = ['/etc/ironic/ironic.conf']
        CONF.config_dir = ['/etc/ironic/conf.d']
        mock_glob.return_value = ['/etc/ironic/conf.d/test.conf']

        result = list(self.adapter._config_files())

        expected = ['/etc/ironic/ironic.conf', '/etc/ironic/conf.d/test.conf']
        self.assertEqual(expected, result)
        mock_glob.assert_called_once_with('/etc/ironic/conf.d/*.conf')

    def test__config_files_only_config_file(self):
        """Test _config_files method with only config files."""
        CONF.config_file = ['/etc/ironic/ironic.conf',
                            '/etc/ironic/other.conf']
        CONF.config_dir = []

        result = list(self.adapter._config_files())

        expected = ['/etc/ironic/ironic.conf', '/etc/ironic/other.conf']
        self.assertEqual(expected, result)

    @mock.patch(
        'ironic.networking.switch_drivers.driver_adapter.cfg.ConfigParser',
        autospec=True)
    def test__extract_switch_sections(self, mock_parser_class):
        """Test _extract_switch_sections method."""
        # Mock the sections dict that will be populated
        sections = {
            'switch:switch1': {
                'address': ['192.168.1.1'],
                'username': ['admin'],
                'password': ['secret']
            },
            'switch:switch2': {
                'address': ['192.168.1.2'],
                'device_type': ['cisco_ios']
            },
            'regular_section': {
                'key': ['value']
            }
        }

        # Create a mock parser that populates the sections dict when called
        def mock_parser_init(config_file, sections_dict):
            # Populate the sections dict that was passed in
            sections_dict.update(sections)
            # Return a mock parser instance
            parser = mock.Mock()
            parser.parse.return_value = None
            return parser

        mock_parser_class.side_effect = mock_parser_init

        result = self.adapter._extract_switch_sections(
            '/etc/ironic/ironic.conf'
        )

        expected = {
            'switch1': {
                'address': '192.168.1.1',
                'username': 'admin',
                'password': 'secret'
            },
            'switch2': {
                'address': '192.168.1.2',
                'device_type': 'cisco_ios'
            }
        }
        self.assertEqual(expected, result)

    @mock.patch(
        'ironic.networking.switch_drivers.driver_adapter.cfg.ConfigParser',
        autospec=True)
    def test__extract_switch_sections_parse_error(self, mock_parser_class):
        """Test _extract_switch_sections with config parse error."""
        # Create a mock parser that raises an exception when parse() is called
        def mock_parser_init(config_file, sections_dict):
            parser = mock.Mock()
            parser.parse.side_effect = Exception("Parse error")
            return parser

        mock_parser_class.side_effect = mock_parser_init

        result = self.adapter._extract_switch_sections(
            '/etc/ironic/ironic.conf'
        )

        self.assertEqual({}, result)

    @mock.patch('os.replace', autospec=True)
    @mock.patch('os.fdopen', autospec=True)
    @mock.patch('tempfile.mkstemp', autospec=True)
    def test__write_config_file_success(self, mock_mkstemp, mock_fdopen,
                                        mock_replace):
        """Test _write_config_file method successful write."""
        switch_configs = {
            'genericswitch:switch1': {
                'ip': '192.168.1.1',
                'username': 'admin',
                'device_type': 'netmiko_cisco_ios'
            },
            'genericswitch:switch2': {
                'ip': '192.168.1.2',
                'device_type': 'netmiko_ovs_linux'
            }
        }

        # Mock tempfile.mkstemp to return a fake fd and path
        mock_mkstemp.return_value = (42, '/tmp/.tmp_driver_config_xyz')

        # Mock fdopen to return a mock file object
        mock_file = mock.mock_open()()
        mock_fdopen.return_value.__enter__.return_value = mock_file

        self.adapter._write_config_file('/tmp/test.conf', switch_configs)

        mock_mkstemp.assert_called_once_with(
            dir='/tmp', prefix='.tmp_driver_config_', text=True)
        mock_fdopen.assert_called_once_with(42, 'w')
        mock_replace.assert_called_once_with(
            '/tmp/.tmp_driver_config_xyz', '/tmp/test.conf')

        # Verify the content written
        write_calls = mock_file.write.call_args_list
        written_content = ''.join(call[0][0] for call in write_calls)

        self.assertIn('# Auto-generated config', written_content)
        self.assertIn('[genericswitch:switch1]', written_content)
        self.assertIn('ip = 192.168.1.1', written_content)
        self.assertIn('username = admin', written_content)
        self.assertIn('device_type = netmiko_cisco_ios', written_content)
        self.assertIn('[genericswitch:switch2]', written_content)
        self.assertIn('ip = 192.168.1.2', written_content)
        self.assertIn('device_type = netmiko_ovs_linux', written_content)

    @mock.patch('os.unlink', autospec=True)
    @mock.patch('os.close', autospec=True)
    @mock.patch('os.fdopen', autospec=True)
    @mock.patch('tempfile.mkstemp', autospec=True)
    def test__write_config_file_error(self, mock_mkstemp, mock_fdopen,
                                      mock_close, mock_unlink):
        """Test _write_config_file method with write error."""
        switch_configs = {'test': {'key': 'value'}}

        # Mock tempfile.mkstemp to return a fake fd and path
        mock_mkstemp.return_value = (42, '/tmp/.tmp_driver_config_xyz')

        # Mock fdopen to raise an error during writing
        mock_fdopen.return_value.__enter__.side_effect = IOError(
            "Permission denied")

        # Should raise the IOError after cleanup
        self.assertRaises(IOError,
                          self.adapter._write_config_file,
                          '/tmp/test.conf', switch_configs)

        # Verify cleanup was attempted
        mock_close.assert_called_once_with(42)
        mock_unlink.assert_called_once_with('/tmp/.tmp_driver_config_xyz')

    @mock.patch('os.unlink', autospec=True)
    @mock.patch('os.replace', autospec=True)
    @mock.patch('os.fdopen', autospec=True)
    @mock.patch('tempfile.mkstemp', autospec=True)
    def test__write_config_file_write_error_with_cleanup(
            self, mock_mkstemp, mock_fdopen, mock_replace, mock_unlink):
        """Test _write_config_file cleans up temp file on write error."""
        switch_configs = {'test': {'key': 'value'}}

        # Mock tempfile.mkstemp to return a fake fd and path
        mock_mkstemp.return_value = (42, '/tmp/.tmp_driver_config_xyz')

        # Mock file write to succeed but replace to fail
        mock_file = mock.mock_open()()
        mock_fdopen.return_value.__enter__.return_value = mock_file
        mock_replace.side_effect = OSError("Rename failed")

        # Should raise the OSError after cleanup
        self.assertRaises(OSError,
                          self.adapter._write_config_file,
                          '/tmp/test.conf', switch_configs)

        # Verify temp file cleanup was attempted
        mock_unlink.assert_called_once_with('/tmp/.tmp_driver_config_xyz')


class NetworkingDriverAdapterReloadTestCase(base.TestCase):
    """Tests for reload_configuration helper."""
    adapter = None

    def setUp(self):
        super(NetworkingDriverAdapterReloadTestCase, self).setUp()
        test_drivers = {'noop': NoOpSwitchDriver()}
        self.adapter = driver_adapter.NetworkingDriverAdapter(test_drivers)

    def test_reload_configuration_success(self):
        output_file = '/tmp/switches.conf'

        with mock.patch.object(
            self.adapter, 'preprocess_config', autospec=True
        ) as mock_preprocess, mock.patch(
            'ironic.networking.switch_drivers.driver_adapter.CONF',
            autospec=True
        ) as mock_conf:
            mock_preprocess.return_value = 3

            result = self.adapter.reload_configuration(output_file)

            mock_conf.reload_config_files.assert_called_once()
            mock_preprocess.assert_called_once_with(output_file)
            self.assertEqual(3, result)

    def test_reload_configuration_preprocess_failure(self):
        output_file = '/tmp/switches.conf'

        with mock.patch.object(
            self.adapter, 'preprocess_config', autospec=True
        ) as mock_preprocess, mock.patch(
            'ironic.networking.switch_drivers.driver_adapter.CONF',
            autospec=True
        ) as mock_conf:
            mock_preprocess.side_effect = Exception('fail')

            self.assertRaises(
                exception.NetworkError,
                self.adapter.reload_configuration,
                output_file,
            )

            mock_conf.reload_config_files.assert_called_once()
            mock_preprocess.assert_called_once_with(output_file)

    def test_reload_configuration_conf_reload_failure(self):
        output_file = '/tmp/switches.conf'

        with mock.patch(
            'ironic.networking.switch_drivers.driver_adapter.CONF',
            autospec=True
        ) as mock_conf:
            mock_conf.reload_config_files.side_effect = Exception('boom')

            self.assertRaises(
                exception.NetworkError,
                self.adapter.reload_configuration,
                output_file,
            )

            mock_conf.reload_config_files.assert_called_once()

    def test_reload_configuration_zero_translations(self):
        output_file = '/tmp/switches.conf'

        with mock.patch.object(
            self.adapter, 'preprocess_config', autospec=True
        ) as mock_preprocess, mock.patch(
            'ironic.networking.switch_drivers.driver_adapter.CONF',
            autospec=True
        ) as mock_conf:
            mock_preprocess.return_value = 0

            result = self.adapter.reload_configuration(output_file)

            mock_conf.reload_config_files.assert_called_once()
            mock_preprocess.assert_called_once_with(output_file)
            self.assertEqual(0, result)
