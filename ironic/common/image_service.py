# Copyright 2010 OpenStack Foundation
# Copyright 2013 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
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


import abc
import datetime
from http import client as http_client
from operator import itemgetter
import os
import shutil
from urllib import parse as urlparse

from oslo_log import log
from oslo_utils import strutils
from oslo_utils import uuidutils
import requests

from ironic.common import exception
from ironic.common.glance_service.image_service import GlanceImageService
from ironic.common.i18n import _
from ironic.common import oci_registry
from ironic.common import utils
from ironic.conf import CONF

IMAGE_CHUNK_SIZE = 1024 * 1024  # 1mb
# NOTE(JayF): This is the check-of-last-resort; we also have an allowlist
# enabled by default. These represent paths that under no circumstances should
# we access for file:// URLs
BLOCKED_FILE_URL_PATHS = {'/dev', '/sys', '/proc', '/boot', '/etc', '/run'}

LOG = log.getLogger(__name__)


class BaseImageService(object, metaclass=abc.ABCMeta):
    """Provides retrieval of disk images."""

    @abc.abstractmethod
    def validate_href(self, image_href):
        """Validate image reference.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed.
        :returns: Information needed to further operate with an image.
        """

    @abc.abstractmethod
    def download(self, image_href, image_file):
        """Downloads image to specified location.

        :param image_href: Image reference.
        :param image_file: File object to write data to.
        :raises: exception.ImageRefValidationFailed.
        :raises: exception.ImageDownloadFailed.
        """

    @abc.abstractmethod
    def show(self, image_href):
        """Get dictionary of image properties.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed.
        :returns: dictionary of image properties. It has three of them: 'size',
            'updated_at' and 'properties'. 'updated_at' attribute is a naive
            UTC datetime object.
        """

    @property
    def is_auth_set_needed(self):
        """Property to notify the caller if it needs to set authentication."""
        return False

    @property
    def transfer_verified_checksum(self):
        """The transferred artifact checksum."""
        return None


class HttpImageService(BaseImageService):
    """Provides retrieval of disk images using HTTP."""

    @staticmethod
    def gen_auth_from_conf_user_pass(image_href):
        """This function is used to pass the credentials to the chosen

           credential verifier and in case the verification is successful
           generate the compatible authentication object that will be used
           with the request(s). This function handles the authentication object
           generation for authentication strategies that are username+password
           based. Credentials are collected from the oslo.config framework.

        :param image_href: href of the image that is being acted upon

        :return: Authentication object used directly by the request library
        :rtype: requests.auth.HTTPBasicAuth
        """

        image_server_user = None
        image_server_password = None

        if CONF.deploy.image_server_auth_strategy == 'http_basic':
            HttpImageService.verify_basic_auth_cred_format(
                CONF.deploy.image_server_user,
                CONF.deploy.image_server_password,
                image_href)
            image_server_user = CONF.deploy.image_server_user
            image_server_password = CONF.deploy.image_server_password
        else:
            return None

        return requests.auth.HTTPBasicAuth(image_server_user,
                                           image_server_password)

    @staticmethod
    def verify_basic_auth_cred_format(image_href, user=None, password=None):
        """Verify basic auth credentials used for image head request.

        :param user: auth username
        :param password: auth password
        :raises: exception.ImageRefValidationFailed if the credentials are not
            present
        """
        expected_creds = {'image_server_user': user,
                          'image_server_password': password}
        missing_creds = []
        for key, value in expected_creds.items():
            if not value:
                missing_creds.append(key)
        if missing_creds:
            raise exception.ImageRefValidationFailed(
                image_href=image_href,
                reason=_("Missing %s fields from HTTP(S) "
                         "basic auth config") % missing_creds
            )

    def validate_href(self, image_href, secret=False):
        """Validate HTTP image reference.

        :param image_href: Image reference.
        :param secret: Specify if image_href being validated should not be
            shown in exception message.
        :raises: exception.ImageRefValidationFailed if HEAD request failed or
            returned response code not equal to 200.
        :raises: exception.ImageRefIsARedirect if the supplied URL is a
            redirect to a different URL. The caller may be able to handle
            this.
        :returns: Response to HEAD request.
        """
        output_url = 'secreturl' if secret else image_href

        try:
            verify = strutils.bool_from_string(CONF.webserver_verify_ca,
                                               strict=True)
        except ValueError:
            verify = CONF.webserver_verify_ca

        try:
            auth = HttpImageService.gen_auth_from_conf_user_pass(image_href)
            # NOTE(TheJulia): Head requests do not work on things that are not
            # files, but they can be responded with redirects or a 200 OK....
            # We don't want to permit endless redirects either, thus not
            # request an override to the requests default to try and resolve
            # redirects as otherwise we might end up with something like
            # HTTPForbidden or a list of files. Both should be okay to at
            # least know things are okay in a limited fashion.
            response = requests.head(image_href, verify=verify,
                                     timeout=CONF.webserver_connection_timeout,
                                     auth=auth)
            if response.status_code == http_client.MOVED_PERMANENTLY:
                # NOTE(TheJulia): In the event we receive a redirect, we need
                # to notify the caller. Before this we would just fail,
                # but a url which is missing a trailing slash results in a
                # redirect to a target path, and the caller *may* actually
                # care about that.
                redirect = requests.Session().get_redirect_target(response)

                # Extra guard because this is pointless if there is no
                # location in the field. Requests also properly formats
                # our string for us, or gives us None.
                if redirect:
                    raise exception.ImageRefIsARedirect(
                        image_ref=image_href,
                        redirect_url=redirect)

            if (response.status_code == http_client.FORBIDDEN
                    and str(image_href).endswith('/')):
                LOG.warning('Attempted to validate a URL %s, however we '
                            'received an HTTP Forbidden response and the '
                            'url ends with trailing slash (/), suggesting '
                            'non-image deploy may be in progress with '
                            'a webserver which is not permitting an index '
                            'to be generated. We will treat this as valid, '
                            'but return the response.', image_href)
                return response

            # NOTE(TheJulia): Any file list reply will proceed past here just
            # fine as they are conveyed as an HTTP 200 OK response with a
            # server rendered HTML document payload.
            if response.status_code != http_client.OK:
                raise exception.ImageRefValidationFailed(
                    image_href=output_url,
                    reason=_("Got HTTP code %s instead of 200 in response "
                             "to HEAD request.") % response.status_code)

        except (OSError, requests.ConnectionError,
                requests.RequestException) as e:
            raise exception.ImageRefValidationFailed(image_href=output_url,
                                                     reason=str(e))
        return response

    def download(self, image_href, image_file):
        """Downloads image to specified location.

        :param image_href: Image reference.
        :param image_file: File object to write data to.
        :raises: exception.ImageRefValidationFailed if GET request returned
            response code not equal to 200.
        :raises: exception.ImageDownloadFailed if:
            * IOError happened during file write;
            * GET request failed.
        """

        try:

            verify = strutils.bool_from_string(CONF.webserver_verify_ca,
                                               strict=True)
        except ValueError:
            verify = CONF.webserver_verify_ca

        try:
            auth = HttpImageService.gen_auth_from_conf_user_pass(image_href)
            response = requests.get(image_href, stream=True, verify=verify,
                                    timeout=CONF.webserver_connection_timeout,
                                    auth=auth)
            if response.status_code != http_client.OK:
                raise exception.ImageRefValidationFailed(
                    image_href=image_href,
                    reason=_("Got HTTP code %s instead of 200 in response "
                             "to GET request.") % response.status_code)

            with response.raw as input_img:
                shutil.copyfileobj(input_img, image_file, IMAGE_CHUNK_SIZE)

        except (OSError, requests.ConnectionError, requests.RequestException,
                IOError) as e:
            raise exception.ImageDownloadFailed(image_href=image_href,
                                                reason=str(e))

    def show(self, image_href):
        """Get dictionary of image properties.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed if:
            * HEAD request failed;
            * HEAD request returned response code not equal to 200;
            * Content-Length header not found in response to HEAD request.
        :returns: dictionary of image properties. It has three of them: 'size',
            'updated_at' and 'properties'. 'updated_at' attribute is a naive
            UTC datetime object.
        """
        response = self.validate_href(image_href)
        image_size = response.headers.get('Content-Length')
        if image_size is None:
            raise exception.ImageRefValidationFailed(
                image_href=image_href,
                reason=_("Cannot determine image size as there is no "
                         "Content-Length header specified in response "
                         "to HEAD request."))

        # Parse last-modified header to return naive datetime object
        str_date = response.headers.get('Last-Modified')
        date = None
        if str_date:
            http_date_format_strings = [
                '%a, %d %b %Y %H:%M:%S GMT',  # RFC 822
                '%A, %d-%b-%y %H:%M:%S GMT',  # RFC 850
                '%a %b %d %H:%M:%S %Y'        # ANSI C
            ]
            for fmt in http_date_format_strings:
                try:
                    date = datetime.datetime.strptime(str_date, fmt)
                    break
                except ValueError:
                    continue

        no_cache = 'no-store' in response.headers.get('Cache-Control', '')

        return {
            'size': int(image_size),
            'updated_at': date,
            'properties': {},
            'no_cache': no_cache,
        }

    @staticmethod
    def get(image_href):
        """Downloads content and returns the response text.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed if GET request returned
            response code not equal to 200.
        :raises: exception.ImageDownloadFailed if:
            * IOError happened during file write;
            * GET request failed.
        """

        try:

            verify = strutils.bool_from_string(CONF.webserver_verify_ca,
                                               strict=True)
        except ValueError:
            verify = CONF.webserver_verify_ca

        try:
            auth = HttpImageService.gen_auth_from_conf_user_pass(image_href)
            response = requests.get(image_href, stream=False, verify=verify,
                                    timeout=CONF.webserver_connection_timeout,
                                    auth=auth)
            if response.status_code != http_client.OK:
                raise exception.ImageRefValidationFailed(
                    image_href=image_href,
                    reason=_("Got HTTP code %s instead of 200 in response "
                             "to GET request.") % response.status_code)

            return response.text

        except (OSError, requests.ConnectionError, requests.RequestException,
                IOError) as e:
            raise exception.ImageDownloadFailed(image_href=image_href,
                                                reason=str(e))


class OciImageService(BaseImageService):
    """Image Service class for accessing an OCI Container Registry."""

    # Holding place on the instantiated class for the image processing
    # request to house authentication data, because we have to support
    # varying authentication to backend services.
    _user_auth_data = None

    # Field to house the verified checksum of the last downloaded content
    # by the running class.
    _verified_checksum = None

    _client = None

    def __init__(self):
        verify = strutils.bool_from_string(CONF.webserver_verify_ca,
                                           strict=True)
        # Creates a client which we can use for actions.
        # Note, this is not yet authenticated!
        self._client = oci_registry.OciClient(verify=verify)

    def _validate_url_is_specific(self, image_href):
        """Identifies if the supplied image_href is a manifest pointer.

        Identifies if the image_href value is specific, and performs basic
        data validation on the digest value to ensure it is as expected.
        As a note, this does *not* consider a URL with a tag value as
        specific enough, because that is a starting point in the data
        structure view which can have multiple artifacts nested within
        that view.

        :param image_href: The user supplied image_href value to evaluate
                           if the URL is specific to to a specific manifest,
                           or is otherwise generalized and needs to be
                           identified.
        :raises: OciImageNotSpecifc if the supplied image_href lacks a
                 required manifest digest value, or if the digest value
                 is not understood.
        :raises: ImageRefValidationFailed if the supplied image_href
                 appears to be malformed and lacking a digest value,
                 or if the supplied data and values are the incorrect
                 length and thus invalid.
        """
        href = urlparse.urlparse(image_href)
        # Identify if we have an @ character denoting manifest
        # reference in the path.
        split_path = str(href.path).split('@')
        if len(split_path) < 2:
            # Lacks a manifest digest pointer being referenced.
            raise exception.OciImageNotSpecific(image_ref=image_href)
        # Extract the digest for evaluation.
        hash_array = split_path[1].split(':')
        if len(hash_array) < 2:
            # We cannot parse something we don't understand. Specifically the
            # supplied data appaears to be invalid.
            raise exception.ImageRefValidationFailed(
                image_href=image_href,
                reason='Lacking required digest value')
        algo = hash_array[0].lower()
        value = hash_array[1].lower()

        # Sanity check the checksum hash lengths to match types we expect.
        # NOTE(TheJulia): Generally everything is sha256 with container
        # registries, however there are open patches to also embrace sha512
        # in the upstream registry code base.
        if 'sha256' == algo:
            if 64 != len(value):
                raise exception.ImageRefValidationFailed(
                    image_href=image_href,
                    reason='Manifest digest length incorrect and does not '
                           'match the expected lenngth of the algorithm.')
        elif 'sha512' == algo:
            # While sha256 seems to be the convention, the go libraries and
            # even the transport reference don't seem to explicitly set an
            # expectation of what type. This is likely some future proofing
            # more than anything else.
            if 128 != len(value):
                raise exception.ImageRefValidationFailed(
                    image_href=image_href,
                    reason='Manifest digest length incorrect and does not '
                           'match the expected lenngth of the algorithm.')
        else:
            LOG.error('Failed to parse %(image_href)s, unknown digest '
                      'algorithm %(algo)s.',
                      {'image_href': image_href,
                       'algo': algo})
            raise exception.OciImageNotSpecific(image_ref=image_href)

    def validate_href(self, image_href, secret=None):
        """Validate OCI image reference.

        This method is an alias of the ``show`` method on this class, which
        exists only for API compatibility reasons. Ultimately, the show
        method performs all of the same validation required.

        :param image_href: Image reference.
        :param secret: Unused setting.
        :raises: exception.ImageRefValidationFailed
        :raises: exception.OciImageNotSpecific
        :returns: Identical output to the ``show`` method on this class
                  as this method is an alias of the ``show``.
        """

        return self.show(image_href)

    def download(self, image_href, image_file):
        """Downloads image to specified location.

        :param image_href: Image reference.
        :param image_file: File object to write data to.
        :raises: exception.ImageRefValidationFailed.
        :raises: exception.ImageDownloadFailed.
        :raises: exception.OciImageNotSpecific.
        """
        # Call not permitted until we have a specific image_source.
        self._validate_url_is_specific(image_href)
        csum = self._client.download_blob_from_manifest(image_href,
                                                        image_file)
        self._verified_checksum = csum

    def show(self, image_href):
        """Get dictionary of image properties.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed.
        :raises: exception.OciImageNotSpecific.
        :returns: dictionary of image properties. It has three of them: 'size',
            'checksum', and 'digest'
        """
        self._validate_url_is_specific(image_href)
        manifest = self._client.get_manifest(image_href)
        layers = manifest.get('layers', [{}])
        size = layers[0].get('size', 0)
        digest = layers[0].get('digest')
        checksum = None
        if digest and ':' in digest:
            # This should always be the case, but just being
            # defensive given array interaction.
            checksum = digest.split(':')[1]
        # Return values to the caller so size handling can be
        # navigated with the image cache, checksum saved to make
        # everyone happy, and the original digest value to help
        # generate a blob url path to enable download.
        return {'size': size,
                'checksum': checksum,
                'digest': digest}

    @property
    def is_auth_set_needed(self):
        """Property to notify the caller if it needs to set authentication."""
        return True

    @property
    def transfer_verified_checksum(self):
        """Property to notify the caller if it needs to set authentication."""
        return self._verified_checksum

    def set_image_auth(self, image_url, auth_data):
        """Sets the supplied auth_data dictionary on the class for use later.

        Provides a mechanism to inform the image service of specific
        credentials without wiring this in as a first class citizen in
        all image service interfaces.

        :param auth_data: The authentication data dictionary holding username,
                          password, or other authentication data which may
                          be used by this client class.
        :returns: None
        :raises: AssertionError should this method be called twice
                 in the same workflow.
        """
        if self._user_auth_data:
            raise AssertionError("BUG: _user_auth_data should only be set"
                                 "once in a overall workflow.")
        if not auth_data and not CONF.oci.authentication_config:
            # We have no data, and no settings, we should just quietly
            # return, there is nothing to do.
            return
        if auth_data:
            # Set a username and password. Bearer auth expects
            # no valid user name in the code path of the oci client.
            # The important as the passwords with bearer auth are
            # full tokens.
            self._user_auth_data = auth_data
            username = auth_data.get('username')
            password = auth_data.get('password')
        else:
            # Set username and password to None so the OCI client loads
            # auth data from configuration.
            username = None
            password = None
        self._client.authenticate(image_url, username, password)

    def identify_specific_image(self, image_href, image_download_source=None,
                                cpu_arch=None):
        """Identify a specific OCI Registry Artifact.

        This method supports the caller, but is located in the image service
        code to provide it access to the Container Registry client code which
        holds the lower level methods.

        The purpose of this method is to take the user requested image_href
        and identify the best matching artifact attached to a container
        registry's entry. This is because the container registry can
        contain many artifacts which can be distributed and allocated
        by different types. To achieve this goal, this method utilizes
        the image_download_source to weight the preference of type of
        file to look for, and the CPU architecture to enable support
        for mutli-arch container registries.

        In order to inform the caller about the url, as well as related
        data, such as the manifest which points to the artifact, artifact
        digest, known original filename of the artifact, this method
        returns a dictionary with several fields which may be useful
        to aid in understanding of what artifact was chosen.

        :param image_href: The image URL as supplied by the Ironic user.
        :param image_download_source: The Ironic image_download_source
            value, defaults to None. When a value of 'local' is provided,
            this method prefers selection of qcow images over raw images.
            Otherwise, raw images are the preference.
        :param cpu_arch: The Bare Metal node's defined CPU architecture,
            if any. Defaults to None. When used, a direct match is sought
            in the remote container registry. If 'x86_64' or 'amd64' is used,
            the code searches for the values in the remote registry
            interchangeably due to OCI data model standardizing on `amd64` as
            the default value for 64bit x86 Architectures.
        :returns: A dictionary with multiple values to the caller to aid
            in returning the required HTTP URL, but also metadata about the
            selected artifact including size, filename, blob digest, related
            manifest digest, the remote recorded mediaType value, if the file
            appears compressed, if the file appears to be a raw disk image,
            any HTTP Authorization secret, if applicable, and the OCI
            image manifest URL. As needs could be different based upon
            different selection algorithms and evolving standards/approaches
            in use of OCI registries, the dictionary can also be empty, or
            contain different values and any caller should defensively use
            information as needed. If a record is *not* found, a empty
            dictionary is the result set. Under normal circumstances, the
            result looks something like this example.
            {
            'image_url': 'https://fqdn/path',
            'image_size': 1234567,
            'image_filename': 'filename.raw.zstd',
            'image_checksum': 'f00f...',
            'image_container_blob_digest': 'sha256:f00f...',
            'image_media_type': 'application/zstd,
            'image_compression_type': 'zstd',
            'image_disk_format': 'raw',
            'image_request_authorization_secret': None,
            'oci_image_manifest_url': 'https://fqdn/path@sha256:123f...',
            }
        """
        # TODO(TheJulia): Ideally we should call the referrers endpoint
        # in the remote API, however, it is *very* new only having been
        # approved in Mid-2024, is not widely available. It would allow
        # the overall query sequence to take more of streamlined flow
        # as opposed to the existing code which gets the index and then
        # looks into manifest data.
        # See
        # https://github.com/opencontainers/image-spec/pull/934
        # https://github.com/opencontainers/distribution-spec/pull/335

        # An image_url tells us if we've found something matching what
        # we're looking for.
        image_url = None

        requested_image = urlparse.urlparse(image_href)
        if requested_image.path and '@' in requested_image.path:
            LOG.debug('We have been given a specific URL, as such we are '
                      'skipping specific artifact detection.')
            # We have a specific URL, we don't need to do anything else.
            # FIXME(TheJulia): We need to improve this. Essentially we
            # need to go get the image url
            manifest = self.show(image_href)
            # Identify the blob URL from the defining manifest for IPA.
            image_url = self._client.get_blob_url(image_href,
                                                  manifest['digest'])
            cached_auth = self._client.get_cached_auth()
            return {
                # Return an OCI url in case Ironic is doing the download
                'oci_image_manifest_url': image_href,
                # Return a checksum, so we don't make the checksum code
                # angry!
                'image_checksum': manifest['checksum'],
                'image_url': image_url,
                # NOTE(TheJulia) With the OCI data model, there is *no*
                # way for us to know what the disk image format is.
                # We can't look up, we're pointed at a manifest URL
                # with limited information.
                'image_disk_format': 'unknown',
                'image_request_authorization_secret': cached_auth,
            }

        # Query the remote API for a list index list of manifests
        artifact_index = self._client.get_artifact_index(image_href)
        manifests = artifact_index.get('manifests', [])
        if len(manifests) < 1:
            # This is likely not going to happen, but we have nothing
            # to identify and deploy based upon, so nothing found
            # for user consistency.
            raise exception.ImageNotFound(image_id=image_href)

        if image_download_source == 'swift':
            raise exception.InvalidParameterValue(
                err="An image_download_source of swift is incompatible with "
                    "retrieval of artifacts from an OCI container registry.")

        # Determine our preferences for matching
        if image_download_source == 'local':
            # These types are qcow2 images, we can download these and convert
            # them, but it is okay for us to match a raw appearing image
            # if we don't have a qcow available.
            disk_format_priority = {'qcow2': 1,
                                    'qemu': 2,
                                    'raw': 3,
                                    'applehv': 4}
        else:
            # applehv appears to be a raw image,
            # raw is the Ironic community preference.
            disk_format_priority = {'qcow2': 3,
                                    'qemu': 4,
                                    'raw': 1,
                                    'applehv': 2}

        # First thing to do, filter by disk types
        # and assign a selection priority... since Ironic can handle
        # several different formats without issue.
        new_manifests = []
        for manifest in manifests:
            artifact_format = manifest.get('annotations', {}).get('disktype')
            if artifact_format in disk_format_priority.keys():
                manifest['_priority'] = disk_format_priority[artifact_format]
            else:
                manifest['_priority'] = 100
            new_manifests.append(manifest)

        sorted_manifests = sorted(new_manifests, key=itemgetter('_priority'))

        # Iterate through the entries of manifests and evaluate them
        # one by one to identify a likely item.
        for manifest in sorted_manifests:
            # First evaluate the architecture because ironic can operated in
            # an architecture agnostic mode... and we *can* match on it, but
            # it is one of the most constraining factors.
            if cpu_arch:
                # NOTE(TheJulia): amd64 is the noted standard format in the
                # API for x86_64. One thing, at least observing quay.io hosted
                # artifacts is that there is heavy use of x86_64 as instead
                # of amd64 as expected by the specification. This same sort
                # of pattern extends to arm64/aarch64.
                if cpu_arch in ['x86_64', 'amd64']:
                    possible_cpu_arch = ['x86_64', 'amd64']
                elif cpu_arch in ['arm64', 'aarch64']:
                    possible_cpu_arch = ['aarch64', 'arm64']
                else:
                    possible_cpu_arch = [cpu_arch]
                # Extract what the architecture is noted for the image, from
                # the platform field.
                architecture = manifest.get('platform', {}).get('architecture')
                if architecture and architecture not in possible_cpu_arch:
                    # skip onward, we don't have a localized match
                    continue

            # One thing podman is doing, and an ORAS client can set for
            # upload, is annotations. This is ultimately the first point
            # where we can identify likely artifacts.
            # We also pre-sorted on disktype earlier, so in theory based upon
            # preference, we should have the desired result as our first
            # matching hint which meets the criteria.
            disktype = manifest.get('annotations', {}).get('disktype')
            if disktype:
                if disktype in disk_format_priority.keys():
                    identified_manifest_digest = manifest.get('digest')
                    blob_manifest = self._client.get_manifest(
                        image_href, identified_manifest_digest)
                    layers = blob_manifest.get('layers', [])
                    if len(layers) != 1:
                        # This is a *multilayer* artifact, meaning a container
                        # construction, not a blob artifact in the OCI
                        # container registry. Odds are we're at the end of
                        # the references for what the user has requested
                        # consideration of as well, so it is good to log here.
                        LOG.info('Skipping consideration of container '
                                 'registry manifest %s as it has multiple'
                                 'layers.',
                                 identified_manifest_digest)
                        continue

                    # NOTE(TheJulia): The resulting layer contents, has a
                    # mandatory mediaType value, which may be something like
                    # application/zstd or application/octet-stream and the
                    # an optional org.opencontainers.image.title annotation
                    # which would contain the filename the file was stored
                    # with in alignment with OARS annotations. Furthermore,
                    # there is an optional artifactType value with OCI
                    # distribution spec 1.1 (mid-2024) which could have
                    # been stored when the artifact was uploaded,
                    # but is optional. In any event, this is only available
                    # on the manifest contents, not further up unless we have
                    # the newer referrers API available. As of late 2024,
                    # quay.io did not offer the referrers API.
                    chosen_layer = layers[0]
                    blob_digest = chosen_layer.get('digest')

                    # Use the client helper to assemble a blob url, so we
                    # have consistency with what we expect and what we parse.
                    image_url = self._client.get_blob_url(image_href,
                                                          blob_digest)
                    image_size = chosen_layer.get('size')
                    chosen_original_filename = chosen_layer.get(
                        'annotations', {}).get(
                            'org.opencontainers.image.title')
                    manifest_digest = manifest.get('digest')
                    media_type = chosen_layer.get('mediaType')
                    is_raw_image = disktype in ['raw', 'applehv']
                    break
            else:
                # The case of there being no disk type in the entry.
                # The only option here is to query the manifest contents out
                # and based decisions upon that. :\
                # We could look at the layers, count them, and maybe look at
                # artifact types.
                continue
        if image_url:
            # NOTE(TheJulia): Doing the final return dict generation as a
            # last step in order to leave the door open to handling other
            # types and structures for matches which don't use an annotation.

            # TODO(TheJulia): We likely ought to check artifacttype,
            # as well for any marker of the item being compressed.
            # Also, shorthanded for +string format catching which is
            # also a valid storage format.
            if media_type.endswith('zstd'):
                compression_type = 'zstd'
            elif media_type.endswith('gzip'):
                compression_type = 'gzip'
            else:
                compression_type = None
            cached_auth = self._client.get_cached_auth()
            # Generate new URL to reset the image_source to
            # so download calls can use the OCI interface
            # and code path moving forward.
            url = urlparse.urlparse(image_href)
            # Drop any trailing content indicating a tag
            image_path = url.path.split(':')[0]
            manifest = f'{url.scheme}://{url.netloc}{image_path}@{manifest_digest}'  # noqa
            return {
                'image_url': image_url,
                'image_size': image_size,
                'image_filename': chosen_original_filename,
                'image_checksum': blob_digest.split(':')[1],
                'image_container_manifest_digest': manifest_digest,
                'image_media_type': media_type,
                'image_compression_type': compression_type,
                'image_disk_format': 'raw' if is_raw_image else 'qcow2',
                'image_request_authorization_secret': cached_auth,
                'oci_image_manifest_url': manifest,
            }
        else:
            # NOTE(TheJulia): This is likely future proofing, suggesting a
            # future case where we're looking at the container, and we're not
            # finding disk images, but it does look like a legitimate
            # container. As such, here we're just returning an empty dict,
            # and we can sort out the rest of the details once we get there.
            return {}


class FileImageService(BaseImageService):
    """Provides retrieval of disk images available locally on the conductor."""

    def validate_href(self, image_href):
        """Validate local image reference.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed if source image file
            doesn't exist, is in a blocked path, or is not in an allowed path.
        :returns: Path to image file if it exists and is allowed.
        """
        image_path = urlparse.urlparse(image_href).path

        # Check if the path is in the blocklist
        rpath = os.path.abspath(image_path)
        for bad in BLOCKED_FILE_URL_PATHS:
            if rpath == bad or rpath.startswith(bad + os.sep):
                raise exception.ImageRefValidationFailed(
                    image_href=image_href,
                    reason=_("Security: The path %s is not permitted in file "
                             "URLs" % bad)
                )

        # Check if the path is in the allowlist
        for allowed in CONF.conductor.file_url_allowed_paths:
            if rpath == allowed or rpath.startswith(allowed + os.sep):
                break
        else:
            raise exception.ImageRefValidationFailed(
                image_href=image_href,
                reason=_(
                    "Security: Path %s is not allowed for image source "
                    "file URLs" % image_path)
            )

        # Check if the file exists
        if not os.path.isfile(image_path):
            raise exception.ImageRefValidationFailed(
                image_href=image_href,
                reason=_("Specified image file not found."))

        return image_path

    def download(self, image_href, image_file):
        """Downloads image to specified location.

        :param image_href: Image reference.
        :param image_file: File object to write data to.
        :raises: exception.ImageRefValidationFailed if source image file
            doesn't exist.
        :raises: exception.ImageDownloadFailed if exceptions were raised while
            writing to file or creating hard link.
        """
        source_image_path = self.validate_href(image_href)
        dest_image_path = image_file.name
        try:
            image_file.close()
            os.remove(dest_image_path)

            # NOTE(dtantsur): os.link is supposed to follow symlinks, but it
            # does not: https://github.com/python/cpython/issues/81793
            real_image_path = os.path.realpath(source_image_path)
            try:
                os.link(real_image_path, dest_image_path)
            except OSError as exc:
                orig = (f' (real path {real_image_path})'
                        if real_image_path != source_image_path
                        else '')

                LOG.debug('Could not create a link from %(src)s%(orig)s to '
                          '%(dest)s, will copy the content instead. '
                          'Error: %(exc)s.',
                          {'src': source_image_path, 'dest': dest_image_path,
                           'orig': orig, 'exc': exc})
            else:
                return

            # NOTE(dtantsur): starting with Python 3.8, copyfile() uses
            # efficient copying (i.e. sendfile) under the hood.
            shutil.copyfile(source_image_path, dest_image_path)
        except Exception as e:
            raise exception.ImageDownloadFailed(image_href=image_href,
                                                reason=str(e))

    def show(self, image_href):
        """Get dictionary of image properties.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed if image file specified
            doesn't exist.
        :returns: dictionary of image properties. It has three of them: 'size',
            'updated_at' and 'properties'. 'updated_at' attribute is a naive
            UTC datetime object.
        """
        source_image_path = self.validate_href(image_href)
        return {
            'size': os.path.getsize(source_image_path),
            'updated_at': utils.unix_file_modification_datetime(
                source_image_path),
            'properties': {},
            # No point in caching local file images
            'no_cache': True,
        }


protocol_mapping = {
    'http': HttpImageService,
    'https': HttpImageService,
    'file': FileImageService,
    'glance': GlanceImageService,
    'oci': OciImageService,
}


def get_image_service(image_href, client=None, context=None):
    """Get image service instance to download the image.

    :param image_href: String containing href to get image service for.
    :param client: Glance client to be used for download, used only if
        image_href is Glance href.
    :param context: request context, used only if image_href is Glance href.
    :raises: exception.ImageRefValidationFailed if no image service can
        handle specified href.
    :returns: Instance of an image service class that is able to download
        specified image.
    """
    scheme = urlparse.urlparse(image_href).scheme.lower()

    if not scheme:
        if uuidutils.is_uuid_like(str(image_href)):
            cls = GlanceImageService
        else:
            # TODO(TheJulia): Consider looking for a attributes
            # which suggest a container registry reference...
            # because surely people will try.
            raise exception.ImageRefValidationFailed(
                image_href=image_href,
                reason=_('Scheme-less image href is not a UUID.'))
    else:
        cls = protocol_mapping.get(scheme)
        if not cls:
            raise exception.ImageRefValidationFailed(
                image_href=image_href,
                reason=_('Image download protocol %s is not supported.'
                         ) % scheme)

    if cls == GlanceImageService:
        return cls(client, context)
    return cls()


def get_image_service_auth_override(node, permit_user_auth=True):
    """Collect image service authentication overrides

    This method is intended to collect authentication credentials
    together for submission to remote image services which may have
    authentication requirements which are not presently available,
    or where specific authentication details are required.

    :param task: A Node object instance.
    :param permit_user_auth: Option to allow the caller to indicate if
                             user provided authentication should be permitted.
    :returns: A dictionary with username and password keys containing
              credential to utilize or None if no value found.
    """
    # NOTE(TheJulia): This is largely necessary as in a pure OpenStack
    # operating context, we assume the caller is just a glance image UUID
    # and that Glance holds the secret. Ironic would then utilize it's static
    # authentication to interact with Glance.
    # TODO(TheJulia): It was not lost on me that the overall *general* idea
    # here could similarly be leveraged to *enable* private user image access.
    # While that wouldn't necessarily be right here in the code, it would
    # likely need to be able to be picked up for user based authentication.
    if permit_user_auth and 'image_pull_secret' in node.instance_info:
        return {
            # Pull secrets appear to leverage basic auth, but provide a blank
            # username, where the password is understood to be the pre-shared
            # secret to leverage for authentication.
            'username': '',
            'password': node.instance_info.get('image_pull_secret'),
        }
    elif 'image_pull_secret' in node.driver_info:
        # Enables fallback to the driver_info field, as it is considered
        # administratively set.
        return {
            'username': '',
            'password': node.driver_info.get('image_pull_secret'),
        }
    # In the future, we likely want to add logic here to enable condutor
    # configuration housed credentials.
    else:
        return None


def is_container_registry_url(image_href):
    """Determine if the supplied reference string is an OCI registry URL.

    :param image_href: A string containing a url, sourced from the
                       original user request.
    :returns: True if the URL appears to be an OCI image registry
              URL. Otherwise, False.
    """
    if not isinstance(image_href, str):
        return False
    # Possible future idea: engage urlparse, and look at just the path
    # field, since shorthand style gets parsed out without a network
    # location, and parses the entire string as a path so we can detect
    # the shorthand url style without a protocol definition.
    return image_href.startswith('oci://')
