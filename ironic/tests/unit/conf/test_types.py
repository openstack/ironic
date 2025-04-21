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

from ironic.conf import types
from ironic.tests.base import TestCase


class ExplicitAbsolutePath(TestCase):
    def test_explicit_absolute_path(self):
        """Verifies the Opt subclass used to validate absolute paths."""
        good_paths = [
            '/etc/passwd',  # Valid
            '/usr/bin/python',  # Valid
            '/home/user/file.txt',  # Valid - dot in filename allowed
            '/var/lib/ironic/.secretdir',  # Valid - hidden directory allowed
            '/var/lib/ironic/oslo.config',  # Valid - dots in filename allowed
            '/tmp/',  # Valid
            '/',  # Valid (root directory)
            '/.hidden_root_file',  # Valid
            '/path/including/a/numb3r',  # Valid
            '/a/path/with/a/trailing/slash/'  # Valid
        ]
        bad_paths = [
            'relative/path',  # Invalid - no leading slash
            './file.txt',  # Invalid - relative path
            '../file.txt',  # Invalid - relative path
            'file.txt',  # Invalid - no leading slash
            '',  # Invalid - empty string
            '/var/lib/ironic/../../../etc/passwd',  # Invalid - path traversal
            '/etc/../etc/passwd',  # Invalid - path traversal
            '/home/user/./config',  # Invalid - contains current dir reference
            '/home/user/../user/config',  # Invalid - path traversal
            '/../etc/passwd',  # Invalid - path traversal at beginning
            '/.',  # Invalid - just current directory
            '/..'  # Invalid - just parent directory
        ]

        eap = types.ExplicitAbsolutePath()

        def _trypath(tpath):
            try:
                eap(tpath)
            except ValueError:
                return False
            else:
                return True

        for path in good_paths:
            self.assertTrue(_trypath(path),
                            msg=f"Improperly disallowed path: {path}")

        for path in bad_paths:
            self.assertFalse(_trypath(path),
                             msg=f"Improperly allowed path: {path}")
