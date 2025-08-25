# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
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

import os
import threading

from oslo_service import backend
backend.init_backend(backend.BackendType.THREADING)

from ironic.common import i18n  # noqa

# NOTE(TheJulia): We are setting a default thread stack size for all the
# following thread invocations. Ultimately, while the python minimum is
# any positive number with a minimum of 32768 Bytes, in 4096 Byte
# increments. On some distributions/kernel configs this value can be
# smaller, however, this works on every tested linux distribution.
threading.stack_size(
    int(os.environ.get('IRONIC_THREAD_STACK_SIZE', 131072)))
i18n.install('ironic')
