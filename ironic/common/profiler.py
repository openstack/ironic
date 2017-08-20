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

from oslo_config import cfg
from oslo_log import log as logging
from osprofiler import initializer
from osprofiler import profiler

from ironic.common import context

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def setup(name, host='0.0.0.0'):
    """Setup OSprofiler notifier and enable profiling.

    :param name: name of the service that will be profiled
    :param host: hostname or host IP address that the service will be
                 running on. By default host will be set to 0.0.0.0, but
                 specifying host name / address usage is highly recommended.
    :raises TypeError: in case of invalid connection string for
                       a notifier backend, which is set in
                       osprofiler.initializer.init_from_conf.
    """
    if not CONF.profiler.enabled:
        return

    admin_context = context.get_admin_context()
    initializer.init_from_conf(conf=CONF,
                               context=admin_context.to_dict(),
                               project="ironic",
                               service=name,
                               host=host)
    LOG.info("OSProfiler is enabled. Trace is generated using "
             "[profiler]/hmac_keys specified in ironic.conf. "
             "To disable, set [profiler]/enabled=false")


def trace_cls(name, **kwargs):
    """Wrap the OSProfiler trace_cls decorator

    Wrap the OSProfiler trace_cls decorator so that it will not try to
    patch the class unless OSProfiler is present and enabled in the config

    :param name: The name of action. For example, wsgi, rpc, db, etc..
    :param kwargs: Any other keyword args used by profiler.trace_cls
    """
    def decorator(cls):
        if CONF.profiler.enabled:
            trace_decorator = profiler.trace_cls(name, kwargs)
            return trace_decorator(cls)
        return cls

    return decorator
