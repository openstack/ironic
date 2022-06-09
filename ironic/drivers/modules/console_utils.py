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

import errno
import hashlib
import fcntl
import ipaddress
import os
import signal
import socket
import subprocess
import time

from base64 import urlsafe_b64encode
from datetime import datetime, timedelta
from ironic_lib import utils as ironic_utils
from oslo_concurrency import lockutils
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import fileutils
import psutil

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils
from ironic.conf import CONF


LOG = logging.getLogger(__name__)

ALLOCATED_PORTS = set()  # in-memory set of already allocated ports
SERIAL_LOCK = 'ironic-console-lock'


def _get_console_pid_dir():
    """Return the directory for the pid file."""

    return CONF.console.terminal_pid_dir or CONF.tempdir


def _ensure_console_pid_dir_exists():
    """Ensure that the console PID directory exists

    Checks that the directory for the console PID file exists
    and if not, creates it.

    :raises: ConsoleError if the directory doesn't exist and cannot be created
    """

    dir = _get_console_pid_dir()
    if not os.path.exists(dir):
        try:
            os.makedirs(dir)
        except OSError as exc:
            msg = (_("Cannot create directory '%(path)s' for console PID file."
                     " Reason: %(reason)s.") % {'path': dir, 'reason': exc})
            LOG.error(msg)
            raise exception.ConsoleError(message=msg)


def _get_console_unix_socket(node_uuid):
    """Generate the unix socket file name."""

    pid_dir = _get_console_pid_dir()
    name = "%s.sock" % node_uuid
    path = os.path.join(pid_dir, name)
    return path


def _get_console_pid_file(node_uuid):
    """Generate the pid file name to hold the terminal process id."""

    pid_dir = _get_console_pid_dir()
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


def _stop_console(node_uuid):
    """Close the serial console for a node

    Kills the console process and deletes the PID file.

    :param node_uuid: the UUID of the node
    :raises: NoConsolePid if no console PID was found
    :raises: ConsoleError if unable to stop the console process
    """

    try:
        console_pid = _get_console_pid(node_uuid)

        os.kill(console_pid, signal.SIGTERM)

        # make sure the process gets killed hard if required
        attempt = 0
        max_attempts = CONF.console.kill_timeout // 0.2

        while attempt < max_attempts:
            if psutil.pid_exists(console_pid):
                if attempt == max_attempts - 1:
                    os.kill(console_pid, signal.SIGKILL)
                LOG.debug("Waiting for the console process with PID %(pid)s "
                          "to exit. Node: %(node)s.",
                          {'pid': console_pid, 'node': node_uuid})
                time.sleep(0.2)
                attempt += 1
            else:
                break

    except OSError as exc:
        if exc.errno != errno.ESRCH:
            msg = (_("Could not stop the console for node '%(node)s'. "
                     "Reason: %(err)s.") % {'node': node_uuid, 'err': exc})
            raise exception.ConsoleError(message=msg)
        else:
            LOG.warning("Console process for node %s is not running "
                        "but pid file exists.", node_uuid)
    finally:
        ironic_utils.unlink_without_raise(_get_console_pid_file(node_uuid))


def make_persistent_password_file(path, password):
    """Writes a file containing a password until deleted."""

    try:
        fileutils.delete_if_exists(path)
        with open(path, 'wb') as file:
            os.chmod(path, 0o600)
            file.write(password.encode())
        return path
    except Exception as e:
        fileutils.delete_if_exists(path)
        raise exception.PasswordFileFailedToCreate(error=e)


def _get_port_range():
    config_range = CONF.console.port_range

    start, stop = map(int, config_range.split(':'))
    if start >= stop:
        msg = _("[console]port_range should be in the "
                "format <start>:<stop> and start < stop")
        raise exception.InvalidParameterValue(msg)
    return start, stop


def _verify_port(port, host=None):
    """Check whether specified port is in use."""
    ip_version = None
    if host is not None:
        try:
            ip_version = ipaddress.ip_address(host).version
        except ValueError:
            # Assume it's a hostname
            pass
    else:
        host = CONF.host
    if ip_version == 6:
        s = socket.socket(socket.AF_INET6)
    else:
        s = socket.socket()

    try:
        s.bind((host, port))
    except socket.error:
        raise exception.Conflict()
    finally:
        s.close()


@lockutils.synchronized(SERIAL_LOCK)
def acquire_port(host=None):
    """Returns a free TCP port on current host.

    Find and returns a free TCP port in the range
    of 'CONF.console.port_range'.
    """

    start, stop = _get_port_range()

    for port in range(start, stop):
        if port in ALLOCATED_PORTS:
            continue
        try:
            _verify_port(port, host=host)
            ALLOCATED_PORTS.add(port)
            return port
        except exception.Conflict:
            pass

    raise exception.NoFreeIPMITerminalPorts(host=CONF.host)


@lockutils.synchronized(SERIAL_LOCK)
def release_port(port):
    """Release specified TCP port."""
    ALLOCATED_PORTS.discard(port)


def get_shellinabox_console_url(port, uuid=None):
    """Get a url to access the console via shellinaboxd.

    :param port: the terminal port for the node.
    """

    digest = None
    expiry = None
    if CONF.console.url_auth_digest_secret:
        try:
            hash_algorithm, digest_algorithm = CONF.console.url_auth_digest_algorithm.split(':', 1)
            h = hashlib.new(hash_algorithm)
            expiry = int((datetime.utcnow() - datetime(1970,1,1) + timedelta(seconds=CONF.console.url_auth_digest_expiry)).total_seconds())
            to_sign = CONF.console.url_auth_digest_pattern % {
                'uuid': uuid,
                'expiry': expiry,
                'secret': CONF.console.url_auth_digest_secret }
            h.update(to_sign)
            if digest_algorithm == 'base64':
                digest = urlsafe_b64encode(h.digest())
            else:
                digest = h.hexdigest()
        except ValueError as e:
            LOG.warning("Could not setup authenticated url due to %s", e)

    console_host = utils.wrap_ipv6(CONF.my_ip)
    scheme = 'https' if CONF.console.terminal_cert_dir else 'http'
    return CONF.console.terminal_url_scheme % {'scheme': scheme,
                                               'host': console_host,
                                               'port': port,
                                               'uuid': uuid,
                                               'digest': digest,
                                               'expiry': expiry }


class _PopenNonblockingPipe(object):
    def __init__(self, source):
        self._source = source
        self._output = b''
        self._wait = False
        self._finished = False
        self._set_async()

    def _set_async(self):
        flags = fcntl.fcntl(self._source, fcntl.F_GETFL)
        fcntl.fcntl(self._source, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def read(self, num_bytes=4096):
        if self._finished:
            return
        try:
            if self._wait:
                time.sleep(1)
                self._wait = False
            data = os.read(self._source.fileno(), num_bytes)
            self._output += data
            if len(data) < num_bytes:
                self._wait = True
        except OSError:
            self._finished = True

    @property
    def output(self):
        return self._output

    @property
    def finished(self):
        return self._finished


def start_shellinabox_console(node_uuid, port, console_cmd):
    """Open the serial console for a node.

    :param node_uuid: the uuid for the node.
    :param port: the terminal port for the node.
    :param console_cmd: the shell command that gets the console.
    :raises: ConsoleError if the directory for the PID file cannot be created
        or an old process cannot be stopped.
    :raises: ConsoleSubprocessFailed when invoking the subprocess failed.
    """

    # make sure that the old console for this node is stopped
    # and the files are cleared
    try:
        _stop_console(node_uuid)
    except exception.NoConsolePid:
        pass

    _ensure_console_pid_dir_exists()
    pid_file = _get_console_pid_file(node_uuid)

    # put together the command and arguments for invoking the console
    args = []
    args.append(CONF.console.terminal)
    if CONF.console.terminal_cert_dir:
        args.append("-c")
        args.append(CONF.console.terminal_cert_dir)
    else:
        args.append("-t")
    if port == 'unix' or port is None:
        args.append('--unixdomain-only')
        args.append(('%(path)s:%(uid)s:%(gid)s:%(mode)s' % {
            'path': _get_console_unix_socket(node_uuid),
            'uid': os.getuid(),
            'gid': CONF.console.socket_gid,
            'mode': CONF.console.socket_permission }))
    else:
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

    error_message = _(
        "Timeout or error while waiting for console subprocess to start for "
        "node: %(node)s.\nCommand: %(command)s.\n") % {
            'node': node_uuid,
            'command': ' '.join(args)}

    stdout_pipe, stderr_pipe = (
        _PopenNonblockingPipe(obj.stdout), _PopenNonblockingPipe(obj.stderr))

    def _wait(node_uuid, popen_obj):
        locals['returncode'] = popen_obj.poll()

        # check if the console pid is created and the process is running.
        # if it is, then the shellinaboxd is invoked successfully as a daemon.
        # otherwise check the error.
        if (locals['returncode'] == 0 and os.path.exists(pid_file)
                and psutil.pid_exists(_get_console_pid(node_uuid))):
            raise loopingcall.LoopingCallDone()

        if locals['returncode'] is not None:
            watched = (stdout_pipe, stderr_pipe)
            while time.time() < expiration and not all(
                    (i.finished for i in watched)):
                for pipe in watched:
                    pipe.read()
            locals['errstr'] = error_message + _(
                "Exit code: %(return_code)s.\nStdout: %(stdout)r\n"
                "Stderr: %(stderr)r") % {
                    'return_code': locals['returncode'],
                    'stdout': stdout_pipe.output, 'stderr': stderr_pipe.output}
            raise loopingcall.LoopingCallDone()

        if time.time() > expiration:
            locals['errstr'] = error_message
            raise loopingcall.LoopingCallDone()

    locals = {'returncode': None, 'errstr': ''}
    expiration = time.time() + CONF.console.subprocess_timeout
    timer = loopingcall.FixedIntervalLoopingCall(_wait, node_uuid, obj)
    timer.start(interval=CONF.console.subprocess_checking_interval).wait()

    if locals['errstr']:
        LOG.warning(locals['errstr'])
        raise exception.ConsoleSubprocessFailed(error=locals['errstr'])


def stop_shellinabox_console(node_uuid):
    """Close the serial console for a node.

    :param node_uuid: the UUID of the node
    :raises: ConsoleError if unable to stop the console process
    """

    try:
        _stop_console(node_uuid)
    except exception.NoConsolePid:
        LOG.warning("No console pid found for node %s while trying to "
                    "stop shellinabox console.", node_uuid)


def get_socat_console_url(port):
    """Get a URL to access the console via socat.

    :param port: the terminal port (integer) for the node
    :return: an access URL to the socat console of the node
    """
    console_host = utils.wrap_ipv6(CONF.console.socat_address)
    return 'tcp://%(host)s:%(port)s' % {'host': console_host,
                                        'port': port}


def start_socat_console(node_uuid, port, console_cmd):
    """Open the serial console for a node.

    :param node_uuid: the uuid of the node
    :param port: the terminal port for the node
    :param console_cmd: the shell command that will be executed by socat to
        establish console to the node
    :raises ConsoleError: if the directory for the PID file or the PID file
        cannot be created
    :raises ConsoleSubprocessFailed: when invoking the subprocess failed
    """
    # Make sure that the old console for this node is stopped.
    # If no console is running, we may get exception NoConsolePid.
    try:
        _stop_console(node_uuid)
    except exception.NoConsolePid:
        pass

    _ensure_console_pid_dir_exists()
    pid_file = _get_console_pid_file(node_uuid)

    # put together the command and arguments for invoking the console
    args = ['socat']
    # set timeout check for user's connection. If the timeout value
    # is not 0, after timeout seconds of inactivity on the client side,
    # the connection will be closed.
    if CONF.console.terminal_timeout > 0:
        args.append('-T%d' % CONF.console.terminal_timeout)
    args.append('-L%s' % pid_file)

    console_host = CONF.console.socat_address
    if ipaddress.ip_address(console_host).version == 6:
        arg = ('TCP6-LISTEN:%(port)s,bind=[%(host)s],reuseaddr,fork,'
               'max-children=1')
    else:
        arg = ('TCP4-LISTEN:%(port)s,bind=%(host)s,reuseaddr,fork,'
               'max-children=1')
    args.append(arg % {'host': console_host,
                       'port': port})

    args.append('EXEC:"%s",pty,stderr' % console_cmd)

    # run the command as a subprocess
    try:
        LOG.debug('Running subprocess: %s', ' '.join(args))
        # Use pipe here to catch the error in case socat
        # fails to start. Note that socat uses stdout as transferring
        # data, so we only capture stderr for checking if it fails.
        obj = subprocess.Popen(args, stderr=subprocess.PIPE)
    except (OSError, ValueError) as e:
        error = _("%(exec_error)s\n"
                  "Command: %(command)s") % {'exec_error': str(e),
                                             'command': ' '.join(args)}
        LOG.exception('Unable to start socat console')
        raise exception.ConsoleSubprocessFailed(error=error)

    # NOTE: we need to check if socat fails to start here.
    # If it starts successfully, it will run in non-daemon mode and
    # will not return until the console session is stopped.

    def _wait(node_uuid, popen_obj):
        wait_state['returncode'] = popen_obj.poll()

        # socat runs in non-daemon mode, so it should not return now
        if wait_state['returncode'] is None:
            # If the pid file is created and the process is running,
            # we stop checking it periodically.
            if (os.path.exists(pid_file)
                    and psutil.pid_exists(_get_console_pid(node_uuid))):
                raise loopingcall.LoopingCallDone()
        else:
            # socat returned, it failed to start.
            # We get the error (out should be None in this case).
            (_out, err) = popen_obj.communicate()
            wait_state['errstr'] = _(
                "Command: %(command)s.\n"
                "Exit code: %(return_code)s.\n"
                "Stderr: %(error)r") % {
                    'command': ' '.join(args),
                    'return_code': wait_state['returncode'],
                    'error': err}
            LOG.error(wait_state['errstr'])
            raise loopingcall.LoopingCallDone()

        if time.time() > expiration:
            wait_state['errstr'] = (_("Timeout while waiting for console "
                                      "subprocess to start for node %s.") %
                                    node_uuid)
            LOG.error(wait_state['errstr'])
            raise loopingcall.LoopingCallDone()

    wait_state = {'returncode': None, 'errstr': ''}
    expiration = time.time() + CONF.console.subprocess_timeout
    timer = loopingcall.FixedIntervalLoopingCall(_wait, node_uuid, obj)
    timer.start(interval=CONF.console.subprocess_checking_interval).wait()

    if wait_state['errstr']:
        raise exception.ConsoleSubprocessFailed(error=wait_state['errstr'])


def stop_socat_console(node_uuid):
    """Close the serial console for a node.

    :param node_uuid: the UUID of the node
    :raise ConsoleError: if unable to stop the console process
    """
    try:
        _stop_console(node_uuid)
    except exception.NoConsolePid:
        LOG.warning("No console pid found for node %s while trying to "
                    "stop socat console.", node_uuid)
