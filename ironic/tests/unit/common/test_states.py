#    Copyright (C) 2015 Intel Corporation. All Rights Reserved.
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

from ironic.common import states
from ironic.tests import base


class StatesTest(base.TestCase):

    def test_state_values_length(self):
        """test_state_values_length

        State values can be a maximum of 15 characters because they are stored
        in the database and the size of the database entry is 15 characters.
        This is specified in db/sqlalchemy/models.py

    """
        for key, value in states.__dict__.items():
            # Assumption: A state variable name is all UPPERCASE and contents
            # are a string.
            if key.upper() == key and isinstance(value, str):
                self.assertLessEqual(
                    len(value), 15,
                    "Value for state: {} is greater than 15 characters".format(
                        key))
