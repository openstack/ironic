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

from tempest import clients
from tempest.common import credentials_factory as common_creds
from tempest import config

from ironic_tempest_plugin.services.baremetal.v1.json.baremetal_client import \
    BaremetalClient


CONF = config.CONF

ADMIN_CREDS = None


class Manager(clients.Manager):
    def __init__(self,
                 credentials=None):
        """Initialization of Manager class.

        Setup service client and make it available for test cases.
        :param credentials: type Credentials or TestResources
        """
        if credentials is None:
            global ADMIN_CREDS
            if ADMIN_CREDS is None:
                ADMIN_CREDS = common_creds.get_configured_admin_credentials()
            credentials = ADMIN_CREDS
        super(Manager, self).__init__(credentials)
        default_params_with_timeout_values = {
            'build_interval': CONF.compute.build_interval,
            'build_timeout': CONF.compute.build_timeout
        }
        default_params_with_timeout_values.update(self.default_params)

        self.baremetal_client = BaremetalClient(
            self.auth_provider,
            CONF.baremetal.catalog_type,
            CONF.identity.region,
            endpoint_type=CONF.baremetal.endpoint_type,
            **default_params_with_timeout_values)
