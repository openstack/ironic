# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
:mod:`ironic.tests.unit` -- ironic unit tests
=====================================================

.. automodule:: ironic.tests.unit
   :platform: Unix
"""

# TODO(deva): move eventlet imports to ironic.__init__ once we move to PBR

import eventlet

from ironic import objects

eventlet.monkey_patch(os=False)

# NOTE(comstud): Make sure we have all of the objects loaded. We do this
# at module import time, because we may be using mock decorators in our
# tests that run at import time.
objects.register_all()
