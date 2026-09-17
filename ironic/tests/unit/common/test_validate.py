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

from ironic.common import validate

from ironic.tests import base

from ddt import data
from ddt import ddt
from ddt import unpack


def annotate(name, *args):
    class AnnotatedList(list):
        pass

    al = AnnotatedList([*args])
    al.__name__ = name
    return al


@ddt
class ValidateTestCase(base.TestCase):
    @data(
        annotate('good id', '1', True),
        annotate('another good id', 'some.string', True),
        annotate('bad because of ..', 'some...string', False),
        *[annotate(
            f"Character {c} is considered invalid",
            f'some_id{c}rest_of_id',
            False,) for c in validate.URL_ILLEGAL_CHARS]
    )
    @unpack
    def test_bmc_subscription_id_valid(self,
                                       bmc_subscription_id: str,
                                       expected_result: bool):
        self.assertEqual(
            expected_result,
            validate.is_bmc_subscription_id_valid(bmc_subscription_id))
