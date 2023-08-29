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


"""Fault definitions."""

POWER_FAILURE = 'power failure'
""" Node is moved to maintenance due to power synchronization failure. """

CLEAN_FAILURE = 'clean failure'
""" Node is moved to maintenance due to failure of a cleaning
    operation. """

RESCUE_ABORT_FAILURE = 'rescue abort failure'
""" Node is moved to maintenance due to failure of cleaning up during
    rescue abort. """

SERVICE_FAILURE = 'service failure'
""" Node is moved to maintenance due to failure of a service operation. """

VALID_FAULTS = (POWER_FAILURE, CLEAN_FAILURE, RESCUE_ABORT_FAILURE,
                SERVICE_FAILURE)
