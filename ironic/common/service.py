#
# Copyright © 2012 eNovance <licensing@enovance.com>
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

from oslo_config import cfg
from oslo_log import log
try:
    from oslo_reports import guru_meditation_report as gmr
    from oslo_reports import opts as gmr_opts
except ImportError:
    gmr = None
from oslo_service import opts as oslo_service_opts
from oslo_service import service

from ironic.common import config
from ironic.common import profiler
from ironic.conf import CONF
from ironic.conf import opts
from ironic import objects
from ironic import version


LOG = log.getLogger(__name__)


def _get_global_conf():
    """Return the process-local CONF singleton when CONF is unpickled.

    In the parent process this is the fully-configured CONF (the spawn probe
    never actually unpickles it). In a spawned child process it returns the
    initially-empty CONF that ``BaseRPCService.__setstate__`` will have
    already populated via ``prepare_command()``.
    """
    from oslo_config import cfg as _cfg
    return _cfg.CONF


def _make_conf_spawn_safe():
    """Make oslo.config's CONF picklable for oslo.service's spawn probe.

    oslo.service calls ``ForkingPickler.dumps(conf)`` to decide between the
    spawn and fork multiprocessing contexts.  After ``parse_args()``,
    ConfigOpts internals are unpicklable (argparse lambdas per CPython
    gh-144782, oslo.config ``_ConfigFileOpt`` lambdas, stevedore objects).

    ``__reduce__`` returns the module-level CONF singleton so that:

    * The probe succeeds → oslo.service uses spawn (no fork-fallback warning).
    * In an actual spawned child, ``_get_global_conf()`` returns the child's
      own CONF, which ``BaseRPCService.__setstate__`` re-configures via
      ``prepare_command()`` before ``start()`` is called.
    """
    if getattr(cfg.ConfigOpts, '_ironic_spawn_safe', False):
        return
    cfg.ConfigOpts.__reduce__ = lambda self: (_get_global_conf, ())
    cfg.ConfigOpts._ironic_spawn_safe = True


def prepare_command(argv=None):
    """Prepare any Ironic command for execution.

    Sets up configuration and logging, registers objects.
    """
    argv = [] if argv is None else argv
    log.register_options(CONF)
    opts.update_opt_defaults()
    config.parse_args(argv)
    # NOTE(vdrok): We need to setup logging after argv was parsed, otherwise
    # it does not properly parse the options from config file and uses defaults
    # from oslo_log
    log.setup(CONF, 'ironic')
    # Register oslo.service's service opts (including log_options and
    # graceful_shutdown_timeout). These are needed by cotyledon's
    # oslo_config_glue in spawned child processes where the parent's
    # option registrations are not inherited.
    oslo_service_opts.register_service_opts(CONF)
    objects.register_all()


def prepare_service(name, argv=None, conf=CONF):
    """Prepare an Ironic service executable.

    In addition to what `prepare_command` does, set up guru meditation
    reporting and profiling.
    """
    prepare_command(argv)
    _make_conf_spawn_safe()

    if gmr is not None:
        gmr_opts.set_defaults(CONF)
        gmr.TextGuruMeditation.setup_autorun(version, conf=CONF)
    else:
        LOG.debug('Guru meditation reporting is disabled '
                  'because oslo.reports is not installed')

    profiler.setup(name, CONF.host)


def process_launcher(**kwargs):
    return service.ProcessLauncher(CONF, restart_method='mutate', **kwargs)


def ensure_rpc_transport(conf=CONF):
    # Only the combined ironic executable can use rpc_transport = none
    if conf.rpc_transport == 'none':
        raise RuntimeError("This service is not designed to work with "
                           "rpc_transport = none. Please use the combined "
                           "ironic executable or another RPC transport.")
