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

import eventlet


# NOTE(JayF): We must green all python stdlib modules before anything else
#             is imported for consistent behavior. For instance, sqlalchemy
#             creates a threading.RLock early, and if it was imported before
eventlet.monkey_patch() # noqa


from oslo_config import cfg # noqa E402
from oslo_log import log # noqa E402

from ironic import objects # noqa E402


log.register_options(cfg.CONF)
log.setup(cfg.CONF, 'ironic')

# NOTE(comstud): Make sure we have all of the objects loaded. We do this
# at module import time, because we may be using mock decorators in our
# tests that run at import time.
objects.register_all()

# NOTE(dtantsur): this module creates mocks which may be used at random points
# of time, so it must be imported as early as possible.
from ironic.tests.unit.drivers import third_party_driver_mocks   # noqa
