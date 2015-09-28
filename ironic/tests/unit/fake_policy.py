# Copyright (c) 2012 OpenStack Foundation
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


policy_data = """
{
    "admin_api": "role:admin or role:administrator",
    "public_api": "is_public_api:True",
    "trusted_call": "rule:admin_api or rule:public_api",
    "default": "rule:trusted_call",
    "show_password": "tenant:admin"
}
"""


policy_data_compat_juno = """
{
    "admin": "role:admin or role:administrator",
    "admin_api": "is_admin:True",
    "default": "rule:admin_api"
}
"""


def get_policy_data(compat):
    if not compat:
        return policy_data
    elif compat == 'juno':
        return policy_data_compat_juno
    else:
        raise Exception('Policy data for %s not available' % compat)
