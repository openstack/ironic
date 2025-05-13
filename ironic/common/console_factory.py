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

from oslo_concurrency import lockutils
from oslo_log import log as logging
import stevedore

from ironic.common import exception
from ironic.conf import CONF

EM_SEMAPHORE = 'console_container_provider'

LOG = logging.getLogger(__name__)


class ConsoleContainerFactory(object):

    _provider = None

    def __init__(self, **kwargs):
        if not ConsoleContainerFactory._provider:
            ConsoleContainerFactory._set_provider(**kwargs)

    @classmethod
    @lockutils.synchronized(EM_SEMAPHORE)
    def _set_provider(cls, **kwargs):
        """Initialize the provider

        :raises: ConsoleContainerError if the provider cannot be loaded.
        """

        # In case multiple greenthreads queue up on
        # this lock before _provider is initialized,
        # prevent creation of multiple DriverManager.
        if cls._provider:
            return

        provider_name = CONF.vnc.container_provider
        try:
            _extension_manager = stevedore.driver.DriverManager(
                'ironic.console.container',
                provider_name,
                invoke_kwds=kwargs,
                invoke_on_load=True)
        except Exception as e:
            LOG.exception('Could not create console container provider')
            raise exception.ConsoleContainerError(
                provider=provider_name, reason=e
            )

        cls._provider = _extension_manager.driver

    @property
    def provider(self):
        return self._provider
