# Copyright 2020 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# NOTE(dtantsur): partial copy from IPA commit
# d86923e7ff40c3ec1d43fe9d4068f0bd3b17de67

import datetime
import ipaddress
import os
import tempfile

from cryptography.hazmat import backends
from cryptography import x509

from ironic.common import tls_utils
from ironic.tests import base


class GenerateTestCase(base.TestCase):

    def setUp(self):
        super().setUp()
        tempdir = tempfile.mkdtemp()
        self.crt_file = os.path.join(tempdir, 'localhost.crt')
        self.key_file = os.path.join(tempdir, 'localhost.key')

    def test__generate(self):
        result = tls_utils.generate_tls_certificate(self.crt_file,
                                                    self.key_file,
                                                    'localhost', '127.0.0.1')
        now = datetime.datetime.now(
            tz=datetime.timezone.utc).replace(tzinfo=None)
        self.assertTrue(result.startswith("-----BEGIN CERTIFICATE-----\n"),
                        result)
        self.assertTrue(result.endswith("\n-----END CERTIFICATE-----\n"),
                        result)
        self.assertTrue(os.path.exists(self.key_file))
        with open(self.crt_file, 'rt') as fp:
            self.assertEqual(result, fp.read())

        cert = x509.load_pem_x509_certificate(result.encode(),
                                              backends.default_backend())
        self.assertEqual([(x509.NameOID.COMMON_NAME, 'localhost')],
                         [(item.oid, item.value) for item in cert.subject])
        # Sanity check for validity range
        # FIXME(dtantsur): use timezone-aware properties and drop the replace()
        # call above when we're ready to bump to cryptography 42.0.
        self.assertLessEqual(cert.not_valid_before, now)
        self.assertGreater(cert.not_valid_after,
                           now + datetime.timedelta(seconds=1800))
        subject_alt_name = cert.extensions.get_extension_for_oid(
            x509.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        self.assertTrue(subject_alt_name.critical)
        self.assertEqual(
            [ipaddress.IPv4Address('127.0.0.1')],
            subject_alt_name.value.get_values_for_type(x509.IPAddress))
        self.assertEqual(
            [], subject_alt_name.value.get_values_for_type(x509.DNSName))
