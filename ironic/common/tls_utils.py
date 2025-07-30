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

from cryptography.hazmat import backends
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography import x509
from oslo_log import log


LOG = log.getLogger(__name__)


def _create_private_key(output):
    """Create a new private key and write it to a file.

    Using elliptic curve keys since they are 2x smaller than RSA ones of
    the same security (the NIST P-256 curve we use roughly corresponds
    to RSA with 3072 bits).

    :param output: Output file name.
    :return: a private key object.
    """
    private_key = ec.generate_private_key(ec.SECP256R1(),
                                          backends.default_backend())
    pkey_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    with open(output, 'wb') as fp:
        fp.write(pkey_bytes)

    return private_key


def generate_tls_certificate(output, private_key_output,
                             common_name, ip_address,
                             valid_for_days=30):
    """Generate a self-signed TLS certificate.

    :param output: Output file name for the certificate.
    :param private_key_output: Output file name for the private key.
    :param common_name: Content for the common name field (e.g. host name).
    :param ip_address: IP address the certificate will be valid for.
    :param valid_for_days: Number of days the certificate will be valid for.
    :return: the generated certificate as a string.
    """
    if isinstance(ip_address, str):
        ip_address = ipaddress.ip_address(ip_address)

    private_key = _create_private_key(private_key_output)

    subject = x509.Name([
        x509.NameAttribute(x509.NameOID.COMMON_NAME, common_name),
    ])
    alt_name = x509.SubjectAlternativeName([x509.IPAddress(ip_address)])
    not_valid_before = datetime.datetime.now(tz=datetime.timezone.utc)
    not_valid_after = (datetime.datetime.now(tz=datetime.timezone.utc)
                       + datetime.timedelta(days=valid_for_days))
    cert = (x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(not_valid_before)
            .not_valid_after(not_valid_after)
            .add_extension(alt_name, critical=True)
            .sign(private_key, hashes.SHA256(), backends.default_backend()))
    pub_bytes = cert.public_bytes(serialization.Encoding.PEM)
    with open(output, "wb") as f:
        f.write(pub_bytes)
    LOG.info('Generated TLS certificate for IP address %s valid from %s '
             'to %s', ip_address, not_valid_before, not_valid_after)
    return pub_bytes.decode('utf-8')
