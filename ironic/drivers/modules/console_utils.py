# coding=utf-8

# Copyright 2014 International Business Machines Corporation
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
Ironic console utilities.
"""

import os
import subprocess
import tempfile
import time

from oslo.config import cfg

from ironic.common import exception
from ironic.common import utils
from ironic.openstack.common import log as logging
from ironic.openstack.common import loopingcall

opts = [
    cfg.StrOpt('terminal',
               default='shellinaboxd',
               help='Path to serial console terminal program'),
    cfg.StrOpt('terminal_cert_dir',
               help='Directory containing the terminal SSL cert(PEM) for '
               'serial console access'),
    cfg.StrOpt('terminal_pid_dir',
               help='Directory for holding terminal pid files. '
               'If not specified, the temporary directory will be used.'),
    cfg.IntOpt('subprocess_checking_interval',
               default=1,
               help='Time interval (in seconds) for checking the status of '
               'console subprocess.'),
    cfg.IntOpt('subprocess_timeout',
               default=10,
               help='Time (in seconds) to wait for the console subprocess '
               'to start.'),
    ]

CONF = cfg.CONF
CONF.register_opts(opts, group='console')

LOG = logging.getLogger(__name__)


def _get_console_pid_file(node_uuid):
    """Generate the pid file name to hold the terminal process id."""

    # make sure the directory exists
    if CONF.console.terminal_pid_dir:
        pid_dir = CONF.console.terminal_pid_dir
    else:
        pid_dir = tempfile.gettempdir()
    if not os.path.exists(pid_dir):
        os.makedirs(pid_dir)

    name = "%s.pid" % node_uuid
    path = os.path.join(pid_dir, name)
    return path


def _get_console_pid(node_uuid):
    """Get the terminal process id from pid file."""

    pid_path = _get_console_pid_file(node_uuid)
    try:
        with open(pid_path, 'r') as f:
            pid_str = f.readline()
            return int(pid_str)
    except (IOError, ValueError):
        raise exception.NoConsolePid(pid_path=pid_path)


def make_persistent_password_file(path, password):
    """Writes a file containing a password until deleted."""

    try:
        utils.delete_if_exists(path)
        os.mknod(path, 0o600)
        with open(path, 'wb') as file:
            file.write(password)
        return path
    except Exception as e:
        utils.delete_if_exists(path)
        raise exception.PasswordFileFailedToCreate(error=str(e))


def get_shellinabox_console_url(port):
    """Get a url to access the console via shellinaboxd.

    :param port: the terminal port for the node.
    """

    console_host = CONF.my_ip
    if utils.is_valid_ipv6(console_host):
        console_host = '[%s]' % console_host
    console_url = "http://%s:%s" % (console_host, port)
    return console_url


def start_shellinabox_console(node_uuid, port, console_cmd):
    """Open the serial console for a node.

    :param node_uuid: the uuid for the node.
    :param port: the terminal port for the node.
    :param console_cmd: the shell command that gets the cosnole.
    :raises: ConsoleSubprocessFailed when invoking the subprocess failed.
    """

    # make sure that the old console for this node is stopped
    # and the files are cleared
    pid_file = _get_console_pid_file(node_uuid)
    try:
        console_pid = _get_console_pid(node_uuid)
        utils.unlink_without_raise(pid_file)
        utils.execute('kill', str(console_pid),
                      check_exit_code=[0, 99])
    except exception.NoConsolePid:
        pass
    except (exception.ProcessExecutionError, exception.UnknownArgumentError):
        LOG.warning(_("Failed to kill the old console process %(pid)s "
                "before starting a new shellinabox console "
                "for node %(node)s.")
                % {'pid': console_pid, 'node': node_uuid})

    # put together the command and arguments for invoking the console
    args = []
    args.append(CONF.console.terminal)
    if CONF.console.terminal_cert_dir:
        args.append("-c")
        args.append(CONF.console.terminal_cert_dir)
    else:
        args.append("-t")
    args.append("-p")
    args.append(str(port))
    args.append("--background=%s" % pid_file)
    args.append("-s")
    args.append(console_cmd)

    # run the command as a subprocess
    try:
        LOG.debug('Running subprocess: %s', ' '.join(args))
        # use pipe here to catch the error in case shellinaboxd
        # failed to start.
        obj = subprocess.Popen(args,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    except (OSError, ValueError) as e:
        error = _("%(exec_error)s\n"
                  "Command: %(command)s") % {'exec_error': str(e),
                                             'command': ' '.join(args)}
        LOG.warning(error)
        raise exception.ConsoleSubprocessFailed(error=error)

    def _wait(node_uuid, popen_obj):
        locals['returncode'] = popen_obj.poll()

        # check if the console pid is created.
        # if it is, then the shellinaboxd is invoked successfully as a daemon.
        # otherwise check the error.
        if locals['returncode'] is not None:
            if locals['returncode'] == 0 and os.path.exists(pid_file):
                raise loopingcall.LoopingCallDone()
            else:
                (stdout, stderr) = popen_obj.communicate()
                locals['errstr'] = _("Command: %(command)s.\n"
                        "Exit code: %(return_code)s.\n"
                        "Stdout: %(stdout)r\n"
                        "Stderr: %(stderr)r") % {'command': ' '.join(args),
                                'return_code': locals['returncode'],
                                'stdout': stdout,
                                'stderr': stderr}
                LOG.warning(locals['errstr'])
                raise loopingcall.LoopingCallDone()

        if (time.time() > expiration):
            locals['errstr'] = _("Timeout while waiting for console"
                    " subprocess to start for node %s.") % node_uuid
            LOG.warning(locals['errstr'])
            raise loopingcall.LoopingCallDone()

    locals = {'returncode': None, 'errstr': ''}
    expiration = time.time() + CONF.console.subprocess_timeout
    timer = loopingcall.FixedIntervalLoopingCall(_wait, node_uuid, obj)
    timer.start(interval=CONF.console.subprocess_checking_interval).wait()

    if locals['errstr']:
        raise exception.ConsoleSubprocessFailed(error=locals['errstr'])


def stop_shellinabox_console(node_uuid):
    """Close the serial console for a node."""

    try:
        console_pid = _get_console_pid(node_uuid)
    except exception.NoConsolePid:
        LOG.warning(_("No console pid found for node %s"
                " while trying to stop shellinabox console.")
                % node_uuid)
    else:
        # Allow exitcode 99 (RC_UNAUTHORIZED)
        utils.execute('kill', str(console_pid),
                      check_exit_code=[0, 99])
    finally:
        utils.unlink_without_raise(_get_console_pid_file(node_uuid))
