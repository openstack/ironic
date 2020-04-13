# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

# NOTE(tenbrae): since __init__ is loaded before the files in the same
#             directory, and some third-party driver tests may need to have
#             their external libraries mocked, we load the file which does
#             that mocking here -- in the __init__.

from ironic.tests.unit.drivers import third_party_driver_mocks   # noqa
