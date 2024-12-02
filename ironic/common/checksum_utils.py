# Copyright (c) 2024 Red Hat, Inc.
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

import hashlib
import os
import re
import time
from urllib import parse as urlparse

from oslo_log import log as logging
from oslo_utils import fileutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import image_service
from ironic.conf import CONF

LOG = logging.getLogger(__name__)


# REGEX matches for Checksum file payloads
# If this list requires changes, it should be changed in
# ironic-python-agent (extensions/standby.py) as well.

MD5_MATCH = r"^([a-fA-F\d]{32})\s"  # MD5 at beginning of line
MD5_MATCH_END = r"\s([a-fA-F\d]{32})$"  # MD5 at end of line
MD5_MATCH_ONLY = r"^([a-fA-F\d]{32})$"  # MD5 only
SHA256_MATCH = r"^([a-fA-F\d]{64})\s"  # SHA256 at beginning of line
SHA256_MATCH_END = r"\s([a-fA-F\d]{64})$"  # SHA256 at end of line
SHA256_MATCH_ONLY = r"^([a-fA-F\d]{64})$"  # SHA256 only
SHA512_MATCH = r"^([a-fA-F\d]{128})\s"  # SHA512 at beginning of line
SHA512_MATCH_END = r"\s([a-fA-F\d]{128})$"  # SHA512 at end of line
SHA512_MATCH_ONLY = r"^([a-fA-F\d]{128})$"  # SHA512 only
FILENAME_MATCH_END = r"\s[*]?{filename}$"  # Filename binary/text end of line
FILENAME_MATCH_PARENTHESES = r"\s\({filename}\)\s"  # CentOS images

CHECKSUM_MATCHERS = (MD5_MATCH, MD5_MATCH_END, SHA256_MATCH, SHA256_MATCH_END,
                     SHA512_MATCH, SHA512_MATCH_END)
CHECKSUM_ONLY_MATCHERS = (MD5_MATCH_ONLY, SHA256_MATCH_ONLY, SHA512_MATCH_ONLY)
FILENAME_MATCHERS = (FILENAME_MATCH_END, FILENAME_MATCH_PARENTHESES)


def validate_checksum(path, checksum, checksum_algo=None):
    """Validate image checksum.

    :param path: File path in the form of a string to calculate a checksum
                 which is compared to the checksum field.
    :param checksum: The supplied checksum value, a string, which will be
                     compared to the file.
    :param checksum_algo: The checksum type of the algorithm.
    :raises: ImageChecksumError if the supplied data cannot be parsed or
             if the supplied value does not match the supplied checksum
             value.
    """
    # TODO(TheJilia): At some point, we likely need to compare
    # the incoming checksum algorithm upfront, ut if one is invoked which
    # is not supported, hashlib will raise ValueError.
    use_checksum_algo = None
    if ":" in checksum:
        # A form of communicating the checksum algorithm is to delimit the
        # type from the value. See ansible deploy interface where this
        # is most evident.
        split_checksum = checksum.split(":")
        use_checksum = split_checksum[1]
        use_checksum_algo = split_checksum[0]
    else:
        use_checksum = checksum
    if not use_checksum_algo:
        use_checksum_algo = checksum_algo
    # If we have a zero length value, but we split it, we have
    # invalid input. Also, checksum is what we expect, algorithm is
    # optional. This guards against the split of a value which is
    # image_checksum = "sha256:" which is a potential side effect of
    # splitting the string.
    if use_checksum == '':
        raise exception.ImageChecksumError()

    # Make everything lower case since we don't expect mixed case,
    # but we may have human originated input on the supplied algorithm.
    try:
        if not use_checksum_algo:
            # This is backwards compatible support for a bare checksum.
            calculated = compute_image_checksum(path)
        else:
            calculated = compute_image_checksum(path,
                                                use_checksum_algo.lower())
    except ValueError:
        # ValueError is raised when an invalid/unsupported/unknown
        # checksum algorithm is invoked.
        LOG.error("Failed to generate checksum for file %(path)s, possible "
                  "invalid checksum algorithm: %(algo)s",
                  {"path": path,
                   "algo": use_checksum_algo})
        raise exception.ImageChecksumAlgorithmFailure()
    except OSError:
        LOG.error("Failed to read file %(path)s to compute checksum.",
                  {"path": path})
        raise exception.ImageChecksumFileReadFailure()
    if (use_checksum is not None
        and calculated.lower() != use_checksum.lower()):
        LOG.error("We were supplied a checksum value of %(supplied)s, but "
                  "calculated a value of %(value)s. This is a fatal error.",
                  {"supplied": use_checksum,
                   "value": calculated})
        raise exception.ImageChecksumError()


def compute_image_checksum(image_path, algorithm='md5'):
    """Compute checksum by given image path and algorithm.

    :param image_path: The path to the file to undergo checksum calculation.
    :param algorithm: The checksum algorithm to utilize. Defaults
        to 'md5' due to historical support reasons in Ironic.
    :returns: The calculated checksum value.
    :raises: ValueError when the checksum algorithm is not supported
       by the system.
    """

    time_start = time.time()
    LOG.debug('Start computing %(algo)s checksum for image %(image)s.',
              {'algo': algorithm, 'image': image_path})

    checksum = fileutils.compute_file_checksum(image_path,
                                               algorithm=algorithm)
    time_elapsed = time.time() - time_start
    LOG.debug('Computed %(algo)s checksum for image %(image)s in '
              '%(delta).2f seconds, checksum value: %(checksum)s.',
              {'algo': algorithm, 'image': image_path, 'delta': time_elapsed,
               'checksum': checksum})
    return checksum


def get_checksum_and_algo(instance_info):
    """Get and return the image checksum and algo.

    :param instance_info: The node instance info, or newly updated/generated
                          instance_info value.
    :returns: A tuple containing two values, a checksum and algorithm,
              if available.
    """
    checksum_algo = None
    if 'image_os_hash_value' in instance_info.keys():
        # A value set by image_os_hash_value supersedes other
        # possible uses as it is specific.
        checksum = instance_info.get('image_os_hash_value')
        checksum_algo = instance_info.get('image_os_hash_algo')
    else:
        checksum = instance_info.get('image_checksum')
        image_source = instance_info.get('image_source')

        # NOTE(stevebaker): file:// images have no requirement to supply
        # checksums but they are now mandatory for validation as part
        # of the fix for CVE-2024-47211.
        # The only practical option is to calculate it here.
        if checksum is None and image_source.startswith('file:'):
            checksum_algo = "sha256"
            image_path = urlparse.urlparse(image_source).path
            checksum = fileutils.compute_file_checksum(
                image_path, algorithm=checksum_algo)

        elif is_checksum_url(checksum):
            checksum = get_checksum_from_url(checksum, image_source)

        # NOTE(TheJulia): This is all based on SHA-2 lengths.
        # SHA-3 would require a hint and it would not be a fixed length.
        # That said, SHA-2 is still valid and has not been withdrawn.
        checksum_len = len(checksum)
        if checksum_len == 128:
            # SHA2-512 is 512 bits, 128 characters.
            checksum_algo = "sha512"
        elif checksum_len == 64:
            checksum_algo = "sha256"

        if checksum_len == 32 and not CONF.agent.allow_md5_checksum:
            # MD5 not permitted and the checksum is the length of MD5
            # and not otherwise defined.
            LOG.error('Cannot compute the checksum as it uses MD5 '
                      'and is disabled by configuration. If the checksum '
                      'is *not* MD5, please specify the algorithm.')
            raise exception.ImageChecksumAlgorithmFailure()

    return checksum, checksum_algo


def is_checksum_url(checksum):
    """Identify if checksum is not a url.

    :param checksum: The user supplied checksum value.
    :returns: True if the checksum is a url, otherwise False.
    :raises: ImageChecksumURLNotSupported should the conductor have this
             support disabled.
    """
    if (checksum.startswith('http://') or checksum.startswith('https://')):
        if CONF.conductor.disable_support_for_checksum_files:
            raise exception.ImageChecksumURLNotSupported()
        return True
    else:
        return False


def get_checksum_from_url(checksum, image_source):
    """Gets a checksum value based upon a remote checksum URL file.

    :param checksum: The URL to the checksum URL content.
    :param image_soource: The image source utilized to match with
        the contents of the URL payload file.
    :raises: ImageDownloadFailed when the checksum file cannot be
        accessed or cannot be parsed.
    """

    LOG.debug('Attempting to download checksum from: %(checksum)s.',
              {'checksum': checksum})

    # Directly invoke the image service and get the checksum data.
    resp = image_service.HttpImageService.get(checksum)
    checksum_url = str(checksum)

    # NOTE(TheJulia): The rest of this method is taken from
    # ironic-python-agent. If a change is required here, it may
    # be required in ironic-python-agent (extensions/standby.py).
    lines = [line.strip() for line in resp.split('\n') if line.strip()]
    if not lines:
        raise exception.ImageDownloadFailed(image_href=checksum,
                                            reason=_('Checksum file empty.'))
    elif len(lines) == 1:
        # Special case - checksums file with only the checksum itself
        if ' ' not in lines[0]:
            for matcher in CHECKSUM_ONLY_MATCHERS:
                checksum = re.findall(matcher, lines[0])
                if checksum:
                    return checksum[0]
            raise exception.ImageDownloadFailed(
                image_href=checksum_url,
                reason=(
                    _("Invalid checksum file (No valid checksum found)")))
    # FIXME(dtantsur): can we assume the same name for all images?
    expected_fname = os.path.basename(urlparse.urlparse(
        image_source).path)
    for line in lines:
        # Ignore comment lines
        if line.startswith("#"):
            continue

        # Ignore checksums for other files
        for matcher in FILENAME_MATCHERS:
            if re.findall(matcher.format(filename=expected_fname), line):
                break
        else:
            continue

        for matcher in CHECKSUM_MATCHERS:
            checksum = re.findall(matcher, line)
            if checksum:
                return checksum[0]

    raise exception.ImageDownloadFailed(
        image_href=checksum,
        reason=(_("Checksum file does not contain name %s")
                % expected_fname))


class TransferHelper(object):

    def __init__(self, response, checksum_algo, expected_checksum):
        """Helper class to drive data download with concurrent checksum.

        The TransferHelper can be used to help retrieve data from a
        Python requests request invocation, where the request was set
        with `stream=True`, which also builds the checksum digest as the
        transfer is underway.

        :param response: A populated requests.model.Response object.
        :param checksum_algo: The expected checksum algorithm.
        :param expected_checksum: The expected checksum of the data being
                                  transferred.

        """
        # NOTE(TheJulia): Similar code exists in IPA in regards to
        # downloading and checksumming a raw image while streaming.
        # If a change is required here, it might be worthwhile to
        # consider if a similar change is needed in IPA.
        # NOTE(TheJulia): 1 Megabyte is an attempt to always exceed the
        # minimum chunk size which may be needed for proper checksum
        # generation and balance the memory required. We may want to
        # tune this, but 1MB has worked quite well for IPA for some time.
        # This may artificially throttle transfer speeds a little in
        # high performance environments as the data may get held up
        # in the kernel limiting the window from scaling.
        self._chunk_size = 1024 * 1024  # 1MB
        self._last_check_time = time.time()
        self._request = response
        self._bytes_transferred = 0
        self._checksum_algo = checksum_algo
        self._expected_checksum = expected_checksum
        self._expected_size = self._request.headers.get(
            'Content-Length')
        # Determine the hash algorithm and value will be used for calculation
        # and verification, fallback to md5 if algorithm is not set or not
        # supported.
        # NOTE(TheJulia): Regarding MD5, it is likely this will never be
        # hit, but we will guard in case of future use for this method
        # anyhow.
        if checksum_algo == 'md5' and not CONF.agent.allow_md5_checksum:
            # MD5 not permitted
            LOG.error('MD5 checksum utilization is disabled by '
                      'configuration.')
            raise exception.ImageChecksumAlgorithmFailure()

        if checksum_algo in hashlib.algorithms_available:
            self._hash_algo = hashlib.new(checksum_algo)
        else:
            raise ValueError("Unable to process checksum processing "
                             "for image transfer. Algorithm %s "
                             "is not available." % checksum_algo)

    def __iter__(self):
        """Downloads and returns the next chunk of the image.

        :returns: A chunk of the image. Size of 1MB.
        """
        self._last_chunk_time = None
        for chunk in self._request.iter_content(self._chunk_size):
            # Per requests forum posts/discussions, iter_content should
            # periodically yield to the caller for the client to do things
            # like stopwatch and potentially interrupt the download.
            # While this seems weird and doesn't exactly seem to match the
            # patterns in requests and urllib3, it does appear to be the
            # case. Field testing in environments where TCP sockets were
            # discovered in a read hanged state were navigated with
            # this code in IPA.
            if chunk:
                self._last_chunk_time = time.time()
                if isinstance(chunk, str):
                    encoded_data = chunk.encode()
                    self._hash_algo.update(encoded_data)
                    self._bytes_transferred += len(encoded_data)
                else:
                    self._hash_algo.update(chunk)
                    self._bytes_transferred += len(chunk)
                yield chunk
            elif (time.time() - self._last_chunk_time
                  > CONF.image_download_connection_timeout):
                LOG.error('Timeout reached waiting for a chunk of data from '
                          'a remote server.')
                raise exception.ImageDownloadError(
                    self._image_info['id'],
                    'Timed out reading next chunk from webserver')

    @property
    def checksum_matches(self):
        """Verifies the checksum matches and returns True/False."""
        checksum = self._hash_algo.hexdigest()
        if checksum != self._expected_checksum:
            # This is a property, let the caller figure out what it
            # wants to do.
            LOG.error('Verifying transfer checksum %(algo_name)s value '
                      '%(checksum)s against %(xfer_checksum)s.',
                      {'algo_name': self._hash_algo.name,
                       'checksum': self._expected_checksum,
                       'xfer_checksum': checksum})
            return False
        else:
            LOG.debug('Verifying transfer checksum %(algo_name)s value '
                      '%(checksum)s against %(xfer_checksum)s.',
                      {'algo_name': self._hash_algo.name,
                       'checksum': self._expected_checksum,
                       'xfer_checksum': checksum})
            return True

    @property
    def bytes_transferred(self):
        """Property value to return the number of bytes transferred."""
        return self._bytes_transferred

    @property
    def content_length(self):
        """Property value to return the server indicated length."""
        # If none, there is nothing we can do, the server didn't have
        # a response.
        return self._expected_size


def validate_text_checksum(payload, digest):
    """Compares the checksum of a payload versus the digest.

    The purpose of this method is to take the payload string data,
    and compare it to the digest value of the supplied input. The use
    of this is to validate the the data in cases where we have data
    and need to compare it. Useful in API responses, such as those
    from an OCI Container Registry.

    :param payload: The supplied string with an encode method.
    :param digest: The checksum value in digest form of algorithm:checksum.
    :raises: ImageChecksumError when the response payload does not match the
             supplied digest.
    """
    split_digest = digest.split(':')
    checksum_algo = split_digest[0]
    checksum = split_digest[1]
    hasher = hashlib.new(checksum_algo)
    hasher.update(payload.encode())
    if hasher.hexdigest() != checksum:
        # Mismatch, something is wrong.
        raise exception.ImageChecksumError()
