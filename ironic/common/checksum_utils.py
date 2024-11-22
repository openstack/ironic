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
