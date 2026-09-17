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

# Consider extra, national, and punctuation character sets from RFC 1738
# illegal.
URL_ILLEGAL_CHARS = [
 '!', '*', '\'', '(', ')', ',', '{', '}', '|', '\\', '^', '~', '[', ']', '`',
 '<', '>', '#', '%', '"'
]

def is_bmc_subscription_id_valid(bmc_subscription_id: str) -> bool:
    """Validate BMC IDs to be sent to Redfish subscription endpoints.

    Note there's no well-defined type or schema for these subscription IDs.
    Therefore we try to reject illegal characters or some short illegal
    substrings.
    """
    for ic in URL_ILLEGAL_CHARS:
        if ic in bmc_subscription_id:
            return False

    # Dots '.' are allowed... but we consider double dots '..' illegal since
    # they could be misused for traversal.
    if '..' in bmc_subscription_id:
        return False

    return True
