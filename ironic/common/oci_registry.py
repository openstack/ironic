#   Copyright 2025 Red Hat, Inc.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.
#

# NOTE(TheJulia): This file is based upon, in part, some of the TripleO
# project container uploader.
# https://github.com/openstack-archive/tripleo-common/blame/stable/wallaby/tripleo_common/image/image_uploader.py

import base64
import json
import re
import requests
from requests import auth as requests_auth
import tenacity
from urllib import parse

from oslo_log import log as logging

from ironic.common import checksum_utils
from ironic.common import exception
from ironic.conf import CONF

LOG = logging.getLogger(__name__)


(
    CALL_MANIFEST,
    CALL_BLOB,
    CALL_TAGS,
) = (
    '%(image)s/manifests/%(tag)s',
    '%(image)s/blobs/%(digest)s',
    '%(image)s/tags/list',
)

(
    MEDIA_OCI_MANIFEST_V1,
    MEDIA_OCI_INDEX_V1,
) = (
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.oci.image.index.v1+json',
)


class MakeSession(object):
    """Class method to uniformly create sessions.

    Sessions created by this class will retry on errors with an exponential
    backoff before raising an exception. Because our primary interaction is
    with the container registries the adapter will also retry on 401 and
    404. This is being done because registries commonly return 401 when an
    image is not found, which is commonly a cache miss. See the adapter
    definitions for more on retry details.
    """
    def __init__(self, verify=True):
        self.session = requests.Session()
        self.session.verify = verify

    def create(self):
        return self.__enter__()

    def __enter__(self):
        return self.session

    def __exit__(self, *args, **kwargs):
        self.session.close()


class RegistrySessionHelper(object):
    """Class with various registry session helpers

    This class contains a bunch of static methods to be used when making
    session requests against a container registry. The methods are primarily
    used to handle authentication/reauthentication for the requests against
    registries that require auth.
    """
    @staticmethod
    def check_status(session, request, allow_reauth=True):
        """Check request status and trigger reauth

        This function can be used to check if we need to perform authentication
        for a container registry request because we've gotten a 401.
        """
        text = getattr(request, 'text', 'unknown')
        reason = getattr(request, 'reason', 'unknown')
        status_code = getattr(request, 'status_code', None)
        headers = getattr(request, 'headers', {})

        if status_code >= 300 and status_code != 401:
            LOG.info(
                'OCI client got a Non-2xx: status %s, reason %s, text %s',
                status_code,
                reason,
                text)

        if status_code == 401:
            LOG.warning(
                'OCI client failed: status %s, reason %s text %s',
                status_code,
                reason,
                text)
            www_auth = headers.get(
                'www-authenticate',
                headers.get(
                    'Www-Authenticate'
                )
            )
            if www_auth:
                error = None
                # Handle docker.io shenanigans. docker.io will return 401
                # for 403 and 404 but provide an error string. Other registries
                # like registry.redhat.io and quay.io do not do this. So if
                # we find an error string, check to see if we should reauth.
                do_reauth = allow_reauth
                if 'error=' in www_auth:
                    error = re.search('error="(.*?)"', www_auth).group(1)
                    LOG.warning(
                        'Error detected in auth headers: error %s', error)
                    do_reauth = (error == 'invalid_token' and allow_reauth)
                if do_reauth:
                    if hasattr(session, 'reauthenticate'):
                        # This is a re-auth counter
                        reauth = int(session.headers.get('_ReAuth', 0))
                        reauth += 1
                        session.headers['_ReAuth'] = str(reauth)
                        session.reauthenticate(**session.auth_args)

        if status_code == 429:
            raise exception.ImageHostRateLimitFailure(image_ref=request.url)

        request.raise_for_status()

    @staticmethod
    def check_redirect_trusted(request_response, request_session,
                               stream=True, timeout=60):
        """Check if we've been redirected to a trusted source

        Because we may be using auth, we may not want to leak authentication
        keys to an untrusted source. If we get a redirect, we need to check
        that the redirect url is one of our sources that we trust. Otherwise
        we drop the Authorization header from the redirect request. We'll
        add the header back into the request session after performing the
        request to ensure that future usage of the session.

        :param: request_response: Response object of the request to check
        :param: request_session: Session to use when redirecting
        :param: stream: Should we stream the response of the redirect
        :param: timeout: Timeout for the redirect request
        """
        # we're not a redirect, just return the original response
        if not (request_response.status_code >= 300
                and request_response.status_code < 400):
            return request_response
        # parse the destination location
        redir_url = parse.urlparse(request_response.headers['Location'])
        # close the response since we're going to replace it
        request_response.close()
        auth_header = request_session.headers.pop('Authorization', None)
        # ok we got a redirect, let's check where we are going
        secure_cdn = CONF.oci.secure_cdn_registries
        # TODO(TheJulia): Consider breaking the session calls below into
        # a helper method, because as-is, this is basically impossible
        # to unit test the delienation in behavior.
        if len([h for h in secure_cdn if h in redir_url.netloc]) > 0:
            # we're going to a trusted location, add the header back and
            # return response
            request_session.headers.update({'Authorization': auth_header})
            request_response = request_session.get(redir_url.geturl(),
                                                   stream=stream,
                                                   timeout=timeout)
        else:
            # we didn't trust the place we're going, request without auth but
            # add the auth back to the request session afterwards
            request_response = request_session.get(redir_url.geturl(),
                                                   stream=stream,
                                                   timeout=timeout)
            request_session.headers.update({'Authorization': auth_header})

        request_response.encoding = 'utf-8'
        # recheck status here to make sure we didn't get a 401 from
        # our redirect host path.
        RegistrySessionHelper.check_status(session=request_session,
                                           request=request_response)
        return request_response

    def get_token_from_config(fqdn):
        """Takes a FQDN for a container registry and consults auth config.

        This method evaluates named configuration parameter
        [oci]authentication_config and looks for pre-shared secrets
        in the supplied json file. It is written to defensively
        handle the file such that errors are not treated as fatal to
        the overall lookup process, but errors are logged.

        The expected file format is along the lines of:

        {
          "auths": {
            "domain.name": {
              "auth": "pre-shared-secret-value"
            }
          }
        }

        :param fqdn: A fully qualified domain name for interacting
                     with the remote image registry.
        :returns: String value for the "auth" key which matches
                  the supplied FQDN.
        """
        if not CONF.oci.authentication_config:
            return

        auth = None
        try:
            with open(CONF.oci.authentication_config, 'r') as auth_file:
                auth_dict = json.load(auth_file)
        except OSError as e:
            LOG.error('Failed to load pre-shared authentication token '
                      'data: %s', e)
            return
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            LOG.error('Unable to decode pre-shared authentication token '
                      'data: %s', e)
            return
        try:
            # Limiting all key interactions here to capture any formatting
            # errors in one place.
            auth_dict = auth_dict['auths']
            fqdn_dict = auth_dict.get(fqdn)
            auth = fqdn_dict.get('auth')
        except (AttributeError, KeyError):
            LOG.error('There was an error while looking up authentication '
                      'for dns name %s. Possible misformatted file?')
            return

        return auth

    @staticmethod
    def get_bearer_token(session, username=None, password=None,
                         realm=None, service=None, scope=None):
        auth = None
        token_param = {}
        if service:
            token_param['service'] = service
        if scope:
            token_param['scope'] = scope
        if username:
            # NOTE(TheJulia): This won't be invoked under the current
            # client code which does not use a username. Tokens
            # have the username encoded within and the remote servers
            # know how to decode it.
            auth = requests.auth.HTTPBasicAuth(username, password)
        elif password:
            # This is a case where we have a pre-shared token.
            LOG.debug('Using user provided pre-shared authentication '
                      'token to authenticate to the remote registry.')
            auth = requests.auth.HTTPBasicAuth('', password)
        else:
            realm_url = parse.urlparse(realm)
            local_token = RegistrySessionHelper.get_token_from_config(
                realm_url.netloc)
            if local_token:
                LOG.debug('Using a locally configured pre-shared key '
                          'for authentication to the remote registry.')
                auth = requests.auth.HTTPBasicAuth('', local_token)

        auth_req = session.get(realm, params=token_param, auth=auth,
                               timeout=CONF.webserver_connection_timeout)
        auth_req.raise_for_status()
        resp = auth_req.json()
        if 'token' not in resp:
            raise AttributeError('Invalid auth response, no token provide')
        return resp['token']

    @staticmethod
    def parse_www_authenticate(header):
        auth_type = None
        auth_type_match = re.search('^([A-Za-z]*) ', header)
        if auth_type_match:
            auth_type = auth_type_match.group(1)
        if not auth_type:
            return (None, None, None)
        realm = None
        service = None
        if 'realm=' in header:
            realm = re.search('realm="(.*?)"', header).group(1)
        if 'service=' in header:
            service = re.search('service="(.*?)"', header).group(1)
        return (auth_type, realm, service)

    @staticmethod
    @tenacity.retry(  # Retry up to 5 times with longer time for rate limit
        reraise=True,
        retry=tenacity.retry_if_exception_type(
            exception.ImageHostRateLimitFailure
        ),
        wait=tenacity.wait_random_exponential(multiplier=1.5, max=60),
        stop=tenacity.stop_after_attempt(5)
    )
    def _action(action, request_session, *args, **kwargs):
        """Perform a session action and retry if auth fails

        This function dynamically performs a specific type of call
        using the provided session (get, patch, post, etc). It will
        attempt a single re-authentication if the initial request
        fails with a 401.
        """
        _action = getattr(request_session, action)
        try:
            req = _action(*args, **kwargs)
            if not kwargs.get('stream'):
                # The caller has requested a stream, likely download so
                # we really can't call check_status because it would force
                # full content transfer.
                RegistrySessionHelper.check_status(session=request_session,
                                                   request=req)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                req = _action(*args, **kwargs)
                RegistrySessionHelper.check_status(session=request_session,
                                                   request=req)
            else:
                raise
        return req

    @staticmethod
    def get(request_session, *args, **kwargs):
        """Perform a get and retry if auth fails

        This function is designed to be used when we perform a get to
        an authenticated source. This function will attempt a single
        re-authentication request if the first one fails.
        """
        return RegistrySessionHelper._action('get',
                                             request_session,
                                             *args,
                                             **kwargs)


class OciClient(object):

    # The cached client authorization which may be used by for an
    # artifact being accessed by ironic-python-agent so we can retrieve
    # the authorization data and convey it to IPA without needing to
    # directly handle credentials to IPA.
    _cached_auth = None

    def __init__(self, verify):
        """Initialize the OCI container registry client class.

        :param verify: If certificate verification should be leveraged for
                       the underlying HTTP client.
        """
        # FIXME(TheJulia): This should come from configuration
        self.session = MakeSession(verify=verify).create()

    def authenticate(self, image_url, username=None, password=None):
        """Authenticate to the remote container registry.

        :param image_url: The URL to utilise for the remote container
                          registry.
        :param username: The username paraemter.
        :param password: The password parameter.

        :raises: AttributeError when an unknown authentication attribute has
                 been specified by the remote service.
        :raises: ImageServiceAuthenticationRequired when the remote Container
                 registry requires authentication but we do not have a
                 credentials.
        """
        url = self._image_to_url(image_url)
        image, tag = self._image_tag_from_url(url)
        scope = 'repository:%s:pull' % image[1:]

        url = self._build_url(url, path='/')

        # If authenticate is called an additional time....
        # clear the authorization in the client.
        if self.session:
            self.session.headers.pop('Authorization', None)

        r = self.session.get(url, timeout=CONF.webserver_connection_timeout)
        LOG.debug('%s status code %s', url, r.status_code)
        if r.status_code == 200:
            # "Auth" was successful, returning.
            return self.session
        if r.status_code != 401:
            # Auth was rejected.
            r.raise_for_status()
        if 'www-authenticate' not in r.headers:
            # Something is wrong and unexpected.
            raise AttributeError(
                'Unknown authentication method for headers: %s' % r.headers)

        auth = None
        www_auth = r.headers['www-authenticate']
        token_param = {}
        (auth_type, realm, service) = \
            RegistrySessionHelper.parse_www_authenticate(www_auth)

        if auth_type and auth_type.lower() == 'bearer':
            LOG.debug('Using bearer token auth')
            token = RegistrySessionHelper.get_bearer_token(
                self.session,
                username=username,
                password=password,
                realm=realm,
                service=service,
                scope=scope)
        elif auth_type and auth_type.lower() == 'basic':
            if not username or not password:
                raise exception.ImageServiceAuthenticationRequired(
                    image_ref=image_url)
            auth = requests_auth.HTTPBasicAuth(username, password)
            rauth = self.session.get(
                url, params=token_param,
                auth=auth,
                timeout=CONF.webserver_connection_timeout)
            rauth.raise_for_status()
            token = (
                base64.b64encode(
                    bytes(username + ':' + password, 'utf-8')).decode('ascii')
            )
        else:
            raise AttributeError(
                'Unknown www-authenticate value: %s', www_auth)
        auth_header = '%s %s' % (auth_type, token)
        self.session.headers['Authorization'] = auth_header
        # Set a cached Authorization token value so we can extract it
        # if needed, useful for enabling something else to be able to
        # make that actual call.
        self._cached_auth = auth_header
        setattr(self.session, 'reauthenticate', self.authenticate)
        setattr(
            self.session,
            'auth_args',
            dict(
                image_url=image_url,
                username=username,
                password=password,
                session=self.session
            )
        )

    @staticmethod
    def _get_response_text(response, encoding='utf-8', force_encoding=False):
        """Return request response text

        We need to set the encoding for the response other wise it
        will attempt to detect the encoding which is very time consuming.
        See https://github.com/psf/requests/issues/4235 for additional
        context.

        :param: response: requests Respoinse object
        :param: encoding: encoding to set if not currently set
        :param: force_encoding: set response encoding always
        """

        if force_encoding or not response.encoding:
            response.encoding = encoding
        return response.text

    @classmethod
    def _build_url(cls, url, path):
        """Build an HTTPS URL from the input urlparse data.

        :param url: The urlparse result object with the netloc object which
                    is extracted and used by this method.
        :param path: The path in the form of a string which is then assembled
                     into an HTTPS URL to be used for access.
        :returns: A fully formed url in the form of https://ur.
        """
        netloc = url.netloc
        scheme = 'https'
        return '%s://%s/v2%s' % (scheme, netloc, path)

    def _get_manifest(self, image_url, digest=None):

        if not digest:
            # Caller has the digest in the url, that's fine, lets
            # use that.
            digest = image_url.path.split('@')[1]
        image_path = image_url.path.split(':')[0]

        manifest_url = self._build_url(
            image_url, CALL_MANIFEST % {'image': image_path,
                                        'tag': digest})

        # Explicitly ask for the OCI artifact index
        manifest_headers = {'Accept': ", ".join([MEDIA_OCI_MANIFEST_V1])}
        try:
            manifest_r = RegistrySessionHelper.get(
                self.session,
                manifest_url,
                headers=manifest_headers,
                timeout=CONF.webserver_connection_timeout
            )
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                # Authorization Required.
                raise exception.ImageServiceAuthenticationRequired(
                    image_ref=manifest_url)
            if e.response.status_code in (403, 404):
                raise exception.ImageNotFound(
                    image_id=image_url.geturl())
            if e.response.status_code >= 500:
                raise exception.TemporaryFailure()
            raise
        manifest_str = self._get_response_text(manifest_r)
        checksum_utils.validate_text_checksum(manifest_str, digest)
        return json.loads(manifest_str)

    def _get_artifact_index(self, image_url):
        LOG.debug('Attempting to get the artifact index for: %s',
                  image_url)
        parts = self._resolve_tag(image_url)
        index_url = self._build_url(
            image_url, CALL_MANIFEST % parts
        )
        # Explicitly ask for the OCI artifact index
        index_headers = {'Accept': ", ".join([MEDIA_OCI_INDEX_V1])}

        try:
            index_r = RegistrySessionHelper.get(
                self.session,
                index_url,
                headers=index_headers,
                timeout=CONF.webserver_connection_timeout
            )
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                # Authorization Required.
                raise exception.ImageServiceAuthenticationRequired(
                    image_ref=index_url)
            if e.response.status_code in (403, 404):
                raise exception.ImageNotFound(
                    image_id=image_url.geturl())
            if e.response.status_code >= 500:
                raise exception.TemporaryFailure()
            raise
        index_str = self._get_response_text(index_r)
        # Return a dictionary to the caller so it can house the
        # filtering/sorting application logic.
        return json.loads(index_str)

    def _resolve_tag(self, image_url):
        """Attempts to resolve tags from a container URL."""
        LOG.debug('Attempting to resolve tag for: %s',
                  image_url)
        image, tag = self._image_tag_from_url(image_url)
        parts = {
            'image': image,
            'tag': tag
        }
        tags_url = self._build_url(
            image_url, CALL_TAGS % parts
        )
        tag_headers = {'Accept': ", ".join([MEDIA_OCI_INDEX_V1])}
        try:
            tags_r = RegistrySessionHelper.get(
                self.session, tags_url,
                headers=tag_headers,
                timeout=CONF.webserver_connection_timeout)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                # Authorization Required.
                raise exception.ImageServiceAuthenticationRequired(
                    image_ref=tags_url)
            if e.response.status_code >= 500:
                raise exception.TemporaryFailure()
            raise
        tags = tags_r.json()['tags']
        while 'next' in tags_r.links:
            next_url = parse.urljoin(tags_url, tags_r.links['next']['url'])
            tags_r = RegistrySessionHelper.get(
                self.session, next_url,
                headers=tag_headers,
                timeout=CONF.webserver_connection_timeout)
            tags.extend(tags_r.json()['tags'])
        if tag not in tags:
            raise exception.ImageNotFound(
                image_id=image_url.geturl())
        return parts

    def get_artifact_index(self, image):
        """Retrieve an index of artifacts in the Container Registry.

        :param image: The remote container registry URL in the form of
                      oci://host/user/container:tag.

        :returns: A dictionary object representing the index of artifacts
                  present in the container registry, in the form of manifest
                  references along with any other metadata per entry which
                  the remote registry returns such as annotations, and
                  platform labeling which aids in artifact selection.
        """
        image_url = self._image_to_url(image)
        return self._get_artifact_index(image_url)

    def get_manifest(self, image, digest=None):
        """Retrieve a manifest from the remote API.

        This method is a wrapper for the _get_manifest helper, which
        normalizes the input URL, performs basic sanity checking,
        and then calls the underlying method to retrieve the manifest.

        The manifest is then returned to the caller in the form of a
        dictionary.

        :param image: The full URL to the desired manifest or the URL
                      of the container and an accompanying digest parameter.
        :param digest: The Digest value for the requested manifest.
        :returns: A dictionary object representing the manifest as stored
                  in the remote API.
        """
        LOG.debug('Attempting to get manifest for: %s', image)
        if not digest and '@' in image:
            # Digest must be part of the URL, this is fine!
            url_split = image.split("@")
            image_url = self._image_to_url(url_split[0])
            digest = url_split[1]
        elif digest and '@' in image:
            raise AttributeError('Invalid request - Appears to attempt '
                                 'to use a digest value and a digest in '
                                 'the provided URL.')
        else:
            image_url = self._image_to_url(image)
        return self._get_manifest(image_url, digest)

    def get_blob_url(self, image, blob_digest):
        """Generates an HTTP representing an blob artifact.

        :param image: The OCI Container URL.
        :param blob_digest: The digest value representing the desired blob
                            artifact.
        :returns: A HTTP URL string representing the blob URL which can be
                  utilized by an HTTP client to retrieve the artifact.
        """
        if not blob_digest and '@' in image:
            split_url = image.split('@')
            image_url = parse.urlparse(split_url[0])
            blob_digest = split_url[1]
        elif blob_digest and '@' in image:
            split_url = image.split('@')
            image_url = parse.urlparse(split_url[0])
            # The caller likely has a bug or bad pattern
            # which needs to be fixed
        else:
            image_url = parse.urlparse(image)
        # just in caes, split out the tag since it is not
        # used for a blob manifest lookup.
        image_path = image_url.path.split(':')[0]
        manifest_url = self._build_url(
            image_url, CALL_BLOB % {'image': image_path,
                                    'digest': blob_digest})
        return manifest_url

    def get_cached_auth(self):
        """Retrieves the cached authentication header for reuse."""
        # This enables the cached authentication data to be retrieved
        # to enable Ironic to provide that the data without shipping
        # credentials around directly.
        return self._cached_auth

    def download_blob_from_manifest(self, manifest_url, image_file):
        """Retrieves the requested blob from the manifest URL...

        And saves the requested manifest's artifact as the requested
        image_file location, and then returns the verified checksum.

        :param manifest_url: The URL, in oci://host/user/container@digest
                             formatted artifact manifest URL. This is *not*
                             the digest value for the blob, which can only
                             be discovered by retrieving the manifest.
        :param image_file: The image file object to write the blob to.
        :returns: The verified digest value matching the saved artifact.
        """
        LOG.debug('Starting download blob download sequence for %s',
                  manifest_url)
        manifest = self.get_manifest(manifest_url)
        layers = manifest.get('layers', [])
        layer_count = len(layers)
        if layer_count != 1:
            # This is not a blob manifest, it is the container,
            # or something else we don't understand.
            raise exception.ImageRefValidationFailed(
                'Incorrect number of layers. Expected 1 layer, '
                'found %s layers.' % layer_count)
        blob_digest = layers[0].get('digest')
        blob_url = self.get_blob_url(manifest_url, blob_digest)
        LOG.debug('Identified download url for blob: %s', blob_url)
        # One which is an OCI URL with a manifest.
        try:
            resp = RegistrySessionHelper.get(
                self.session,
                blob_url,
                stream=True,
                timeout=CONF.webserver_connection_timeout
            )
            resp = RegistrySessionHelper.check_redirect_trusted(
                resp, self.session, stream=True)
            if resp.status_code != 200:
                raise exception.ImageRefValidationFailed(
                    image_href=blob_url,
                    reason=("Got HTTP code %s instead of 200 in response "
                            "to GET request.") % resp.status_code)
            # Reminder: image_file, is a file object handler.
            split_digest = blob_digest.split(':')

            # Invoke the transfer helper so the checksum can be calculated
            # in transfer.
            download_helper = checksum_utils.TransferHelper(
                resp, split_digest[0], split_digest[1])
            # NOTE(TheJuila): If we *ever* try to have retry logic here,
            # remember to image_file.seek(0) to reset position.
            for chunk in download_helper:
                # write the desired file out
                image_file.write(chunk)
            LOG.debug('Download of %(manifest)s has completed. Transferred '
                      '%(bytes)s of %(total)s total bytes.',
                      {'manifest': manifest_url,
                       'bytes': download_helper.bytes_transferred,
                       'total': download_helper.content_length})
            if download_helper.checksum_matches:
                return blob_digest
            else:
                raise exception.ImageChecksumError()

        except requests.exceptions.HTTPError as e:
            LOG.debug('Encountered error while attempting to download %s',
                      blob_url)
            # Stream changes the behavior, so odds of hitting
            # this area area a bit low unless an actual exception
            # is raised.
            if e.response.status_code == 401:
                # Authorization Required.
                raise exception.ImageServiceAuthenticationRequired(
                    image_ref=blob_url)
            if e.response.status_code in (403, 404):
                raise exception.ImageNotFound(image_id=blob_url)
            if e.response.status_code >= 500:
                raise exception.TemporaryFailure()
            raise

        except (OSError, requests.ConnectionError, requests.RequestException,
                IOError) as e:
            raise exception.ImageDownloadFailed(image_href=blob_url,
                                                reason=str(e))

    @classmethod
    def _image_tag_from_url(cls, image_url):
        """Identify image and tag from image_url.

        :param image_url: Input image url.
        :returns: Tuple of values, image URL which has been reconstructed
                  and the requested tag. Defaults to 'latest' when a tag has
                  not been identified as part of the supplied URL.
        """
        if '@' in image_url.path:
            parts = image_url.path.split('@')
            tag = parts[-1]
            image = ':'.join(parts[:-1])
        elif ':' in image_url.path:
            parts = image_url.path.split(':')
            tag = parts[-1]
            image = ':'.join(parts[:-1])
        else:
            tag = 'latest'
            image = image_url.path
        return image, tag

    @classmethod
    def _image_to_url(cls, image):
        """Helper to create an OCI URL."""
        if '://' not in image:
            # Slight bit of future proofing in case we ever support
            # identifying bare URLs.
            image = 'oci://' + image
        url = parse.urlparse(image)
        return url
