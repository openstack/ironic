#!/usr/bin/python
# -*- coding: utf-8 -*-
#
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

import hashlib
import ssl
import string

import requests
from requests import adapters as req_adapters

# adapted from IPA
DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1MB

_TLS_VERSION_MAP = {
    '1.2': ssl.TLSVersion.TLSv1_2,
    '1.3': ssl.TLSVersion.TLSv1_3,
}


class TLSHTTPAdapter(req_adapters.HTTPAdapter):
    """An HTTPS adapter that allows TLS configuration."""

    def __init__(self, ssl_context=None, **kwargs):
        self._ssl_context = ssl_context
        super(TLSHTTPAdapter, self).__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        if self._ssl_context:
            kwargs['ssl_context'] = self._ssl_context
        super(TLSHTTPAdapter, self).init_poolmanager(
            *args, **kwargs)


class StreamingDownloader(object):

    def __init__(self, url, chunksize, hash_algo=None, verify=True,
                 certs=None, tls_min_version=None,
                 tls_ciphers=None):
        if hash_algo is not None:
            self.hasher = hashlib.new(hash_algo)
        else:
            self.hasher = None
        self.chunksize = chunksize
        session = requests.Session()
        if tls_min_version or tls_ciphers:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            if tls_min_version:
                ctx.minimum_version = (
                    _TLS_VERSION_MAP[tls_min_version])
            if tls_ciphers:
                ctx.set_ciphers(tls_ciphers)
            adapter = TLSHTTPAdapter(ssl_context=ctx)
            session.mount('https://', adapter)
        resp = session.get(url, stream=True, verify=verify,
                           cert=certs, timeout=30)
        if resp.status_code != 200:
            raise Exception(
                'Invalid response code: %s' % resp.status_code)

        self._request = resp

    def __iter__(self):
        for chunk in self._request.iter_content(chunk_size=self.chunksize):
            if self.hasher is not None:
                self.hasher.update(chunk)
            yield chunk

    def checksum(self):
        if self.hasher is not None:
            return self.hasher.hexdigest()


def stream_to_dest(url, dest, chunksize, hash_algo, verify=True,
                   certs=None, tls_min_version=None,
                   tls_ciphers=None):
    downloader = StreamingDownloader(
        url, chunksize, hash_algo, verify=verify,
        certs=certs, tls_min_version=tls_min_version,
        tls_ciphers=tls_ciphers)

    with open(dest, 'wb+') as f:
        for chunk in downloader:
            f.write(chunk)

    return downloader.checksum()


def main():
    module = AnsibleModule(  # noqa This is normal for Ansible modules.
        argument_spec=dict(
            url=dict(required=True, type='str'),
            dest=dict(required=True, type='str'),
            checksum=dict(required=False, type='str', default=''),
            chunksize=dict(required=False, type='int',
                           default=DEFAULT_CHUNK_SIZE),
            validate_certs=dict(required=False, type='bool',
                                default=True),
            client_cert=dict(required=False, type='str',
                             default=''),
            client_key=dict(required=False, type='str',
                            default=''),
            tls_minimum_version=dict(required=False,
                                     type='str', default=''),
            tls_ciphers=dict(required=False, type='str',
                             default='')

        ))

    url = module.params['url']
    dest = module.params['dest']
    checksum = module.params['checksum']
    chunksize = module.params['chunksize']
    validate = module.params['validate_certs']
    client_cert = module.params['client_cert']
    client_key = module.params['client_key']
    tls_min_version = module.params['tls_minimum_version'] or None
    tls_ciphers = module.params['tls_ciphers'] or None
    if client_cert:
        certs = (client_cert, client_key) if client_key else client_cert
    else:
        certs = None

    if checksum == '':
        hash_algo, checksum = None, None
    else:
        try:
            hash_algo, checksum = checksum.rsplit(':', 1)
        except ValueError:
            module.fail_json(msg='The checksum parameter has to be in format '
                             '"<algorithm>:<checksum>"')
        checksum = checksum.lower()
        if not all(c in string.hexdigits for c in checksum):
            module.fail_json(msg='The checksum must be valid HEX number')

        if hash_algo not in hashlib.algorithms_available:
            module.fail_json(msg="%s checksums are not supported" % hash_algo)

    try:
        actual_checksum = stream_to_dest(
            url, dest, chunksize, hash_algo, verify=validate,
            certs=certs, tls_min_version=tls_min_version,
            tls_ciphers=tls_ciphers)
    except Exception as e:
        module.fail_json(msg=str(e))
    else:
        if hash_algo and actual_checksum != checksum:
            module.fail_json(msg='Invalid dest checksum')
        else:
            module.exit_json(changed=True)


# NOTE(pas-ha) Ansible's module_utils.basic is licensed under BSD (2 clause)
from ansible.module_utils.basic import *  # noqa
if __name__ == '__main__':
    main()
