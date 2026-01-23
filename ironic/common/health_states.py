# Copyright 2024 Red Hat, Inc.
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

"""
Mapping of hardware health states.

These states represent the overall health condition of the server hardware,
as reported by the BMC. Drivers should convert vendor-specific health values
to these Ironic-level constants.
"""

import enum


class HealthState(enum.Enum):
    """Hardware health states reported by BMC."""

    OK = 'OK'
    """Hardware is functioning normally with no issues detected."""

    WARNING = 'Warning'
    """Hardware has non-critical issues that may require attention."""

    CRITICAL = 'Critical'
    """Hardware has critical issues requiring immediate attention."""
