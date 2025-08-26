# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
# Copyright (c) 2012 NTT DOCOMO, INC.
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

"""Utilities and helper functions."""

from collections import abc
import contextlib
import copy
import datetime
import errno
import hashlib
import ipaddress
import os
import re
import shlex
import shutil
import tempfile
import time
from urllib import parse as urlparse
import warnings

import jinja2
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import fileutils
from oslo_utils import netutils
from oslo_utils import specs_matcher
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import units
import psutil

from ironic.common import exception
from ironic.common.i18n import _
from ironic.conf import CONF


LOG = logging.getLogger(__name__)


# A dictionary in the form {hint name: hint type}
VALID_ROOT_DEVICE_HINTS = {
    'size': int, 'model': str, 'wwn': str, 'serial': str, 'vendor': str,
    'wwn_with_extension': str, 'wwn_vendor_extension': str, 'name': str,
    'rotational': bool, 'hctl': str, 'by_path': str,
}

ROOT_DEVICE_HINTS_GRAMMAR = specs_matcher.make_grammar()

DATE_RE = r'(?P<year>-?\d{4,})-(?P<month>\d{2})-(?P<day>\d{2})'
TIME_RE = r'(?P<hour>\d{2}):(?P<min>\d{2}):(?P<sec>\d{2})' + \
          r'(\.(?P<sec_frac>\d+))?'
TZ_RE = r'((?P<tz_sign>[+-])(?P<tz_hour>\d{2}):(?P<tz_min>\d{2}))' + \
        r'|(?P<tz_z>Z)'

DATETIME_RE = re.compile(
    '%sT%s(%s)?' % (DATE_RE, TIME_RE, TZ_RE))

USING_SQLITE = None


def execute(*cmd, use_standard_locale=False, log_stdout=True, **kwargs):
    """Convenience wrapper around oslo's execute() method.

    Executes and logs results from a system command. See docs for
    oslo_concurrency.processutils.execute for usage.

    :param cmd: positional arguments to pass to processutils.execute()
    :param use_standard_locale: Defaults to False. If set to True,
                                execute command with standard locale
                                added to environment variables.
    :param log_stdout: Defaults to True. If set to True, logs the output.
    :param kwargs: keyword arguments to pass to processutils.execute()
    :returns: (stdout, stderr) from process execution
    :raises: UnknownArgumentError on receiving unknown arguments
    :raises: ProcessExecutionError
    :raises: OSError
    """
    if use_standard_locale:
        env = kwargs.pop('env_variables', os.environ.copy())
        env['LC_ALL'] = 'C'
        kwargs['env_variables'] = env

    if kwargs.pop('run_as_root', False):
        warnings.warn("run_as_root is deprecated and has no effect",
                      DeprecationWarning)

    def _log(stdout, stderr):
        if log_stdout:
            try:
                LOG.debug('Command stdout is: "%s"', stdout)
            except UnicodeEncodeError:
                LOG.debug('stdout contains invalid UTF-8 characters')
                stdout = (stdout.encode('utf8', 'surrogateescape')
                          .decode('utf8', 'ignore'))
                LOG.debug('Command stdout is: "%s"', stdout)
        try:
            LOG.debug('Command stderr is: "%s"', stderr)
        except UnicodeEncodeError:
            LOG.debug('stderr contains invalid UTF-8 characters')
            stderr = (stderr.encode('utf8', 'surrogateescape')
                      .decode('utf8', 'ignore'))
            LOG.debug('Command stderr is: "%s"', stderr)

    try:
        result = processutils.execute(*cmd, **kwargs)
    except FileNotFoundError:
        with excutils.save_and_reraise_exception():
            LOG.debug('Command not found: "%s"', ' '.join(map(str, cmd)))
    except processutils.ProcessExecutionError as exc:
        with excutils.save_and_reraise_exception():
            _log(exc.stdout, exc.stderr)
    else:
        _log(result[0], result[1])
        return result


def is_valid_datapath_id(datapath_id):
    """Verify the format of an OpenFlow datapath_id.

    Check if a datapath_id is valid and contains 16 hexadecimal digits.
    Datapath ID format: the lower 48-bits are for a MAC address,
    while the upper 16-bits are implementer-defined.

    :param datapath_id: OpenFlow datapath_id to be validated.
    :returns: True if valid. False if not.

    """
    m = "^[0-9a-f]{16}$"
    return (isinstance(datapath_id, str)
            and re.match(m, datapath_id.lower()))


_is_valid_logical_name_re = re.compile(r'^[A-Z0-9-._~]+$', re.I)

# old is_hostname_safe() regex, retained for backwards compat
_is_hostname_safe_re = re.compile(r"""^
[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?  # host
(\.[a-z0-9\-_]{0,62}[a-z0-9])*       # domain
\.?                                  # trailing dot
$""", re.X)


def is_valid_logical_name(hostname):
    """Determine if a logical name is valid.

    The logical name may only consist of RFC3986 unreserved
    characters:

        ALPHA / DIGIT / "-" / "." / "_" / "~"
    """
    if not isinstance(hostname, str) or len(hostname) > 255:
        return False

    return _is_valid_logical_name_re.match(hostname) is not None


def is_hostname_safe(hostname):
    """Old check for valid logical node names.

    Retained for compatibility with REST API < 1.10.

    Nominally, checks that the supplied hostname conforms to:
        * http://en.wikipedia.org/wiki/Hostname
        * http://tools.ietf.org/html/rfc952
        * http://tools.ietf.org/html/rfc1123

    In practice, this check has several shortcomings and errors that
    are more thoroughly documented in bug #1468508.

    :param hostname: The hostname to be validated.
    :returns: True if valid. False if not.
    """
    if not isinstance(hostname, str) or len(hostname) > 255:
        return False

    return _is_hostname_safe_re.match(hostname) is not None


def is_valid_no_proxy(no_proxy):
    """Check no_proxy validity

    Check if no_proxy value that will be written to environment variable by
    ironic-python-agent is valid.

    :param no_proxy: the value that requires validity check. Expected to be a
        comma-separated list of host names, IP addresses and domain names
        (with optional :port).
    :returns: True if no_proxy is valid, False otherwise.
    """
    if not isinstance(no_proxy, str):
        return False
    hostname_re = re.compile('(?!-)[A-Z\\d-]{1,63}(?<!-)$', re.IGNORECASE)
    for hostname in no_proxy.split(','):
        hostname = hostname.strip().split(':')[0]
        if not hostname:
            continue
        max_length = 253
        if hostname.startswith('.'):
            # It is allowed to specify a dot in the beginning of the value to
            # indicate that it is a domain name, which means there will be at
            # least one additional character in full hostname. *. is also
            # possible but may be not supported by some clients, so is not
            # considered valid here.
            hostname = hostname[1:]
            max_length = 251

        if len(hostname) > max_length:
            return False

        if not all(hostname_re.match(part) for part in hostname.split('.')):
            return False

    return True


def validate_and_normalize_mac(address):
    """Validate a MAC address and return normalized form.

    Checks whether the supplied MAC address is formally correct and
    normalize it to all lower case.

    :param address: MAC address to be validated and normalized.
    :returns: Normalized and validated MAC address.
    :raises: InvalidMAC If the MAC address is not valid.

    """
    if not netutils.is_valid_mac(address):
        raise exception.InvalidMAC(mac=address)
    return address.lower()


def validate_and_normalize_datapath_id(datapath_id):
    """Validate an OpenFlow datapath_id and return normalized form.

    Checks whether the supplied OpenFlow datapath_id is formally correct and
    normalize it to all lower case.

    :param datapath_id: OpenFlow datapath_id to be validated and normalized.
    :returns: Normalized and validated OpenFlow datapath_id.
    :raises: InvalidDatapathID If an OpenFlow datapath_id is not valid.

    """

    if not is_valid_datapath_id(datapath_id):
        raise exception.InvalidDatapathID(datapath_id=datapath_id)
    return datapath_id.lower()


def _get_hash_object(hash_algo_name):
    """Create a hash object based on given algorithm.

    :param hash_algo_name: name of the hashing algorithm.
    :raises: InvalidParameterValue, on unsupported or invalid input.
    :returns: a hash object based on the given named algorithm.
    """
    algorithms = hashlib.algorithms_guaranteed
    if hash_algo_name not in algorithms:
        msg = (_("Unsupported/Invalid hash name '%s' provided.")
               % hash_algo_name)
        LOG.error(msg)
        raise exception.InvalidParameterValue(msg)

    return getattr(hashlib, hash_algo_name)()


def file_has_content(path, content, hash_algo='sha256'):
    """Checks that content of the file is the same as provided reference.

    :param path: path to file
    :param content: reference content to check against
    :param hash_algo: hashing algo from hashlib to use, default is 'sha256'
    :returns: True if the hash of reference content is the same as
        the hash of file's content, False otherwise
    """
    file_hash_hex = fileutils.compute_file_checksum(path, algorithm=hash_algo)
    ref_hash = _get_hash_object(hash_algo)
    encoded_content = (content.encode(encoding='utf-8')
                       if isinstance(content, str) else content)
    ref_hash.update(encoded_content)
    return file_hash_hex == ref_hash.hexdigest()


@contextlib.contextmanager
def tempdir(**kwargs):
    tempfile.tempdir = CONF.tempdir
    tmpdir = tempfile.mkdtemp(**kwargs)
    try:
        yield tmpdir
    finally:
        try:
            shutil.rmtree(tmpdir)
        except OSError as e:
            LOG.error('Could not remove tmpdir: %s', e)


def rmtree_without_raise(path):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
    except OSError as e:
        LOG.warning("Failed to remove dir %(path)s, error: %(e)s",
                    {'path': path, 'e': e})


def write_to_file(path, contents, permission=None):
    with open(path, 'w') as f:
        f.write(contents)
    if permission:
        os.chmod(path, permission)


def create_link_without_raise(source, link):
    try:
        os.symlink(source, link)
    except OSError as e:
        if e.errno == errno.EEXIST:
            return
        else:
            LOG.warning("Failed to create symlink from "
                        "%(source)s to %(link)s, error: %(e)s",
                        {'source': source, 'link': link, 'e': e})


def safe_rstrip(value, chars=None):
    """Removes trailing characters from a string if that does not make it empty

    :param value: A string value that will be stripped.
    :param chars: Characters to remove.
    :return: Stripped value.

    """
    if not isinstance(value, str):
        LOG.warning("Failed to remove trailing character. Returning "
                    "original object. Supplied object is not a string: "
                    "%s,", value)
        return value

    return value.rstrip(chars) or value


def check_dir(directory_to_check=None, required_space=1):
    """Check a directory is usable.

    This function can be used by drivers to check that directories
    they need to write to are usable. This should be called from the
    drivers init function. This function checks that the directory
    exists and then calls check_dir_writable and check_dir_free_space.
    If directory_to_check is not provided the default is to use the
    temp directory.

    :param directory_to_check: the directory to check.
    :param required_space: amount of space to check for in MiB.
    :raises: PathNotFound if directory can not be found
    :raises: DirectoryNotWritable if user is unable to write to the
             directory
    :raises InsufficientDiskSpace: if free space is < required space
    """
    # check if directory_to_check is passed in, if not set to tempdir
    if directory_to_check is None:
        directory_to_check = CONF.tempdir

    if not os.path.exists(directory_to_check):
        raise exception.PathNotFound(dir=directory_to_check)

    _check_dir_writable(directory_to_check)
    _check_dir_free_space(directory_to_check, required_space)


def _check_dir_writable(chk_dir):
    """Check that the chk_dir is able to be written to.

    :param chk_dir: Directory to check
    :raises: DirectoryNotWritable if user is unable to write to the
             directory
    """
    is_writable = os.access(chk_dir, os.W_OK)
    if not is_writable:
        raise exception.DirectoryNotWritable(dir=chk_dir)


def _check_dir_free_space(chk_dir, required_space=1):
    """Check that directory has some free space.

    :param chk_dir: Directory to check
    :param required_space: amount of space to check for in MiB.
    :raises InsufficientDiskSpace: if free space is < required space
    """
    # check that we have some free space
    stat = os.statvfs(chk_dir)
    # get dir free space in MiB.
    free_space = float(stat.f_bsize * stat.f_bavail) / 1024 / 1024
    # check for at least required_space MiB free
    if free_space < required_space:
        raise exception.InsufficientDiskSpace(path=chk_dir,
                                              required=required_space,
                                              actual=free_space)


def get_updated_capabilities(current_capabilities, new_capabilities):
    """Returns an updated capability string.

    This method updates the original (or current) capabilities with the new
    capabilities. The original capabilities would typically be from a node's
    properties['capabilities']. From new_capabilities, any new capabilities
    are added, and existing capabilities may have their values updated. This
    updated capabilities string is returned.

    :param current_capabilities: Current capability string
    :param new_capabilities: the dictionary of capabilities to be updated.
    :returns: An updated capability string.
        with new_capabilities.
    :raises: ValueError, if current_capabilities is malformed or
        if new_capabilities is not a dictionary
    """
    if not isinstance(new_capabilities, dict):
        raise ValueError(
            _("Cannot update capabilities. The new capabilities should be in "
              "a dictionary. Provided value is %s") % new_capabilities)

    cap_dict = {}
    if current_capabilities:
        try:
            cap_dict = dict(x.split(':', 1)
                            for x in current_capabilities.split(','))
        except ValueError:
            # Capabilities can be filled by operator.  ValueError can
            # occur in malformed capabilities like:
            # properties/capabilities='boot_mode:bios,boot_option'.
            raise ValueError(
                _("Invalid capabilities string '%s'.") % current_capabilities)

    cap_dict.update(new_capabilities)
    return ','.join('%(key)s:%(value)s' % {'key': key, 'value': value}
                    for key, value in cap_dict.items())


def is_regex_string_in_file(path, string):
    with open(path, 'r') as inf:
        return any(re.search(string, line) for line in inf.readlines())


def unix_file_modification_datetime(file_name):
    return timeutils.normalize_time(
        # normalize time to be UTC without timezone
        datetime.datetime.fromtimestamp(
            # fromtimestamp will return local time by default, make it UTC
            os.path.getmtime(file_name), tz=datetime.timezone.utc
        )
    )


def validate_network_port(port, port_name="Port"):
    """Validates the given port.

    :param port: TCP/UDP port.
    :param port_name: Name of the port.
    :returns: An integer port number.
    :raises: InvalidParameterValue, if the port is invalid.
    """

    if netutils.is_valid_port(port):
        return int(port)

    raise exception.InvalidParameterValue(_(
        '%(port_name)s "%(port)s" is not a valid port.') %
        {'port_name': port_name, 'port': port})


def render_template(template, params, is_file=True, strict=False):
    """Renders Jinja2 template file with given parameters.

    :param template: full path to the Jinja2 template file
    :param params: dictionary with parameters to use when rendering
    :param is_file: whether template is file or string with template itself
    :param strict: Enable strict template rendering. Default is False
    :returns: Rendered template
    :raises: jinja2.exceptions.UndefinedError
    """
    if is_file:
        tmpl_path, tmpl_name = os.path.split(template)
        loader = jinja2.FileSystemLoader(tmpl_path)
    else:
        tmpl_name = 'template'
        loader = jinja2.DictLoader({tmpl_name: template})
    # NOTE(pas-ha) bandit does not seem to cope with such syntaxis
    # and still complains with B701 for that line
    # NOTE(pas-ha) not using default_for_string=False as we set the name
    # of the template above for strings too.
    env = jinja2.Environment(  # nosec B701
        loader=loader,
        autoescape=jinja2.select_autoescape(),
        undefined=jinja2.StrictUndefined if strict else jinja2.Undefined
    )
    tmpl = env.get_template(tmpl_name)
    return tmpl.render(params, enumerate=enumerate)


def parse_instance_info_capabilities(node):
    """Parse the instance_info capabilities.

    One way of having these capabilities set is via Nova, where the
    capabilities are defined in the Flavor extra_spec and passed to
    Ironic by the Nova Ironic driver.

    NOTE: Although our API fully supports JSON fields, to maintain the
    backward compatibility with Juno the Nova Ironic driver is sending
    it as a string.

    :param node: a single Node.
    :raises: InvalidParameterValue if the capabilities string is not a
             dictionary or is malformed.
    :returns: A dictionary with the capabilities if found, otherwise an
              empty dictionary.
    """

    def parse_error():
        error_msg = (_('Error parsing capabilities from Node %s instance_info '
                       'field. A dictionary or a "jsonified" dictionary is '
                       'expected.') % node.uuid)
        raise exception.InvalidParameterValue(error_msg)

    capabilities = node.instance_info.get('capabilities', {})
    if isinstance(capabilities, str):
        try:
            capabilities = jsonutils.loads(capabilities)
        except (ValueError, TypeError):
            parse_error()

    if not isinstance(capabilities, dict):
        parse_error()

    return capabilities


def validate_conductor_group(conductor_group):
    if not isinstance(conductor_group, str):
        raise exception.InvalidConductorGroup(group=conductor_group)
    if not re.match(r'^[a-zA-Z0-9_\-\.]*$', conductor_group):
        raise exception.InvalidConductorGroup(group=conductor_group)


def set_node_nested_field(node, collection, field, value):
    """Set a value in a dictionary field of a node.

    :param node: Node object.
    :param collection: Name of the field with the dictionary.
    :param field: Nested field name.
    :param value: New value.
    """
    col = getattr(node, collection)
    col[field] = value
    setattr(node, collection, col)


def pop_node_nested_field(node, collection, field, default=None):
    """Pop a value from a dictionary field of a node.

    :param node: Node object.
    :param collection: Name of the field with the dictionary.
    :param field: Nested field name.
    :param default: The default value to return.
    :return: The removed value or the default.
    """
    col = getattr(node, collection)
    result = col.pop(field, default)
    setattr(node, collection, col)
    return result


def wrap_ipv6(ip):
    """Wrap the address in square brackets if it's an IPv6 address."""
    try:
        if ipaddress.ip_address(ip).version == 6:
            return "[%s]" % ip
    except ValueError:
        pass

    return ip


def file_mime_type(path):
    """Gets a mime type of the given file."""
    return execute('file', '--brief', '--mime-type', path,
                   use_standard_locale=True)[0].strip()


def _get_mb_ram_available():
    # NOTE(TheJulia): The .available value is the memory that can be given
    # to a process without this process beginning to swap itself.
    return psutil.virtual_memory().available / 1024 / 1024


def is_memory_insufficient(raise_if_fail=False):
    """Checks available system memory and holds the deployment process.

    Evaluates the current system memory available, meaning can be
    allocated to a process by the kernel upon allocation request,
    and delays the execution until memory has been freed,
    or until it has timed out.

    This method will issue a sleep, if the amount of available memory is
    insufficient. This is configured using the
    ``[DEFAULT]minimum_memory_wait_time`` and the
    ``[DEFAULT]minimum_memory_wait_retries``.

    :param raise_if_fail: Default False, but if set to true an
                          InsufficientMemory exception is raised
                          upon insufficient memory.
    :returns: True if the check has timed out. Otherwise None is returned.
    :raises: InsufficientMemory if the raise_if_fail parameter is set to
             True.
    """
    required_memory = CONF.minimum_required_memory
    loop_count = 0

    while _get_mb_ram_available() < required_memory:
        log_values = {
            'available': _get_mb_ram_available(),
            'required': required_memory,
        }
        if CONF.minimum_memory_warning_only:
            LOG.warning('Memory is at %(available)s MiB, required is '
                        '%(required)s. Ironic is in warning-only mode '
                        'which can be changed by altering the '
                        '[DEFAULT]minimum_memory_warning_only',
                        log_values)
            return False
        if loop_count >= CONF.minimum_memory_wait_retries:
            LOG.error('Memory is at %(available)s MiB, required is '
                      '%(required)s. Notifying caller that we have '
                      'exceeded retries.',
                      log_values)
            if raise_if_fail:
                raise exception.InsufficientMemory(
                    free=_get_mb_ram_available(),
                    required=required_memory)
            return True
        LOG.warning('Memory is at %(available)s MiB, required is '
                    '%(required)s, waiting.', log_values)
        # Sleep so interpreter can switch threads.
        time.sleep(CONF.minimum_memory_wait_time)
        loop_count = loop_count + 1


_LARGE_KEYS = frozenset(['system_logs'])


def remove_large_keys(var):
    """Remove specific keys from the var, recursing into dicts and lists."""
    if isinstance(var, abc.Mapping):
        return {key: (remove_large_keys(value)
                      if key not in _LARGE_KEYS else '<...>')
                for key, value in var.items()}
    elif isinstance(var, abc.Sequence) and not isinstance(var, str):
        return var.__class__(map(remove_large_keys, var))
    else:
        return var


def fast_track_enabled(node):
    is_enabled = node.driver_info.get('fast_track')
    if is_enabled is None:
        return CONF.deploy.fast_track
    else:
        try:
            return strutils.bool_from_string(is_enabled, strict=True)
        except ValueError as exc:
            raise exception.InvalidParameterValue(
                _("Invalid value of fast_track: %s") % exc)


def is_fips_enabled():
    """Check if FIPS mode is enabled in the system."""
    try:
        with open('/proc/sys/crypto/fips_enabled', 'r') as f:
            content = f.read()
            if content == "1\n":
                return True
    except Exception:
        pass
    return False


def stop_after_retries(option, group=None):
    """A tenacity retry helper that stops after retries specified in conf."""
    # NOTE(dtantsur): fetch the option inside of the nested call, otherwise it
    # cannot be changed in runtime.
    def should_stop(retry_state):
        if group:
            conf = getattr(CONF, group)
        else:
            conf = CONF
        num_retries = getattr(conf, option)
        return retry_state.attempt_number >= num_retries + 1

    return should_stop


def is_loopback(hostname_or_ip):
    """Check if the provided hostname or IP address is a loopback."""
    try:
        return ipaddress.ip_address(hostname_or_ip).is_loopback
    except ValueError:  # host name
        return hostname_or_ip in ('localhost', 'localhost.localdomain')


def parse_kernel_params(params):
    """Parse kernel parameters into a dictionary.

    ``None`` is used as a value for parameters that are not in
    the ``key=value`` format.

    :param params: kernel parameters as a space-delimited string.
    """
    result = {}
    for s in shlex.split(params):
        try:
            key, value = s.split('=', 1)
        except ValueError:
            result[s] = None
        else:
            result[key] = value
    return result


def is_ironic_using_sqlite():
    """Return True if Ironic is configured to use SQLite"""
    global USING_SQLITE
    if USING_SQLITE is not None:
        return USING_SQLITE

    # We're being called for the first time, lets cache and
    # return the value.
    USING_SQLITE = 'sqlite' in CONF.database.connection.lower()
    return USING_SQLITE


def try_execute(*cmd, **kwargs):
    """The same as execute but returns None on error.

    Executes and logs results from a system command. See docs for
    oslo_concurrency.processutils.execute for usage.

    Instead of raising an exception on failure, this method simply
    returns None in case of failure.

    :param cmd: positional arguments to pass to processutils.execute()
    :param kwargs: keyword arguments to pass to processutils.execute()
    :raises: UnknownArgumentError on receiving unknown arguments
    :returns: tuple of (stdout, stderr) or None in some error cases
    """
    try:
        return execute(*cmd, **kwargs)
    except (processutils.ProcessExecutionError, OSError) as e:
        LOG.debug('Command failed: %s', e)


def mkfs(fs, path, label=None):
    """Format a file or block device

    :param fs: Filesystem type (examples include 'swap', 'ext3', 'ext4'
               'btrfs', etc.)
    :param path: Path to file or block device to format
    :param label: Volume label to use
    """
    if fs == 'swap':
        args = ['mkswap']
    else:
        args = ['mkfs', '-t', fs]
    # add -F to force no interactive execute on non-block device.
    if fs in ('ext3', 'ext4'):
        args.extend(['-F'])
    if label:
        if fs in ('msdos', 'vfat'):
            label_opt = '-n'
        else:
            label_opt = '-L'
        args.extend([label_opt, label])
    args.append(path)
    try:
        execute(*args, use_standard_locale=True)
    except processutils.ProcessExecutionError as e:
        with excutils.save_and_reraise_exception() as ctx:
            if os.strerror(errno.ENOENT) in e.stderr:
                ctx.reraise = False
                LOG.exception('Failed to make file system. '
                              'File system %s is not supported.', fs)
                raise exception.FileSystemNotSupported(fs=fs)
            else:
                LOG.exception('Failed to create a file system '
                              'in %(path)s. Error: %(error)s',
                              {'path': path, 'error': e})


def unlink_without_raise(path):
    try:
        os.unlink(path)
    except OSError as e:
        if e.errno == errno.ENOENT:
            return
        else:
            LOG.warning("Failed to unlink %(path)s, error: %(e)s",
                        {'path': path, 'e': e})


def dd(src, dst, *args):
    """Execute dd from src to dst.

    :param src: the input file for dd command.
    :param dst: the output file for dd command.
    :param args: a tuple containing the arguments to be
        passed to dd command.
    :raises: processutils.ProcessExecutionError if it failed
        to run the process.
    """
    LOG.debug("Starting dd process.")
    execute('dd', 'if=%s' % src, 'of=%s' % dst, *args,
            use_standard_locale=True)


def is_http_url(url):
    url = url.lower()
    return url.startswith('http://') or url.startswith('https://')


def _extract_hint_operator_and_values(hint_expression, hint_name):
    """Extract the operator and value(s) of a root device hint expression.

    A root device hint expression could contain one or more values
    depending on the operator. This method extracts the operator and
    value(s) and returns a dictionary containing both.

    :param hint_expression: The hint expression string containing value(s)
                            and operator (optionally).
    :param hint_name: The name of the hint. Used for logging.
    :raises: ValueError if the hint_expression is empty.
    :returns: A dictionary containing:

        :op: The operator. An empty string in case of None.
        :values: A list of values stripped and converted to lowercase.
    """
    expression = str(hint_expression).strip().lower()
    if not expression:
        raise ValueError(
            _('Root device hint "%s" expression is empty') % hint_name)

    # parseString() returns a list of tokens which the operator (if
    # present) is always the first element.
    ast = ROOT_DEVICE_HINTS_GRAMMAR.parseString(expression)
    if len(ast) <= 1:
        # hint_expression had no operator
        return {'op': '', 'values': [expression]}

    op = ast[0]
    return {'values': [v.strip() for v in re.split(op, expression) if v],
            'op': op}


def _normalize_hint_expression(hint_expression, hint_name):
    """Normalize a string type hint expression.

    A string-type hint expression contains one or more operators and
    one or more values: [<op>] <value> [<op> <value>]*. This normalizes
    the values by url-encoding white spaces and special characters. The
    operators are not normalized. For example: the hint value of "<or>
    foo bar <or> bar" will become "<or> foo%20bar <or> bar".

    :param hint_expression: The hint expression string containing value(s)
                            and operator (optionally).
    :param hint_name: The name of the hint. Used for logging.
    :raises: ValueError if the hint_expression is empty.
    :returns: A normalized string.
    """
    hdict = _extract_hint_operator_and_values(hint_expression, hint_name)
    result = hdict['op'].join([' %s ' % urlparse.quote(t)
                               for t in hdict['values']])
    return (hdict['op'] + result).strip()


def _append_operator_to_hints(root_device):
    """Add an equal (s== or ==) operator to the hints.

    For backwards compatibility, for root device hints where no operator
    means equal, this method adds the equal operator to the hint. This is
    needed when using oslo.utils.specs_matcher methods.

    :param root_device: The root device hints dictionary.
    """
    for name, expression in root_device.items():
        # NOTE(lucasagomes): The specs_matcher from oslo.utils does not
        # support boolean, so we don't need to append any operator
        # for it.
        if VALID_ROOT_DEVICE_HINTS[name] is bool:
            continue

        expression = str(expression)
        ast = ROOT_DEVICE_HINTS_GRAMMAR.parseString(expression)
        if len(ast) > 1:
            continue

        op = 's== %s' if VALID_ROOT_DEVICE_HINTS[name] is str else '== %s'
        root_device[name] = op % expression

    return root_device


def parse_root_device_hints(root_device):
    """Parse the root_device property of a node.

    Parses and validates the root_device property of a node. These are
    hints for how a node's root device is created. The 'size' hint
    should be a positive integer. The 'rotational' hint should be a
    Boolean value.

    :param root_device: the root_device dictionary from the node's property.
    :returns: a dictionary with the root device hints parsed or
              None if there are no hints.
    :raises: ValueError, if some information is invalid.

    """
    if not root_device:
        return

    root_device = copy.deepcopy(root_device)

    invalid_hints = set(root_device) - set(VALID_ROOT_DEVICE_HINTS)
    if invalid_hints:
        raise ValueError(
            _('The hints "%(invalid_hints)s" are invalid. '
              'Valid hints are: "%(valid_hints)s"') %
            {'invalid_hints': ', '.join(invalid_hints),
             'valid_hints': ', '.join(VALID_ROOT_DEVICE_HINTS)})

    for name, expression in root_device.items():
        hint_type = VALID_ROOT_DEVICE_HINTS[name]
        hint_info = _extract_hint_operator_and_values(expression,
                                                      name)
        operator = hint_info['op']
        if name == 'size' and operator == '<range-in>':
            pass
        elif hint_type is str:
            if not isinstance(expression, str):
                raise ValueError(
                    _('Root device hint "%(name)s" is not a string value. '
                      'Hint expression: %(expression)s') %
                    {'name': name, 'expression': expression})
            root_device[name] = _normalize_hint_expression(expression, name)

        elif hint_type is int:
            for v in _extract_hint_operator_and_values(expression,
                                                       name)['values']:
                try:
                    integer = int(v)
                except ValueError:
                    raise ValueError(
                        _('Root device hint "%(name)s" is not an integer '
                          'value. Current value: %(expression)s') %
                        {'name': name, 'expression': expression})

                if integer <= 0:
                    raise ValueError(
                        _('Root device hint "%(name)s" should be a positive '
                          'integer. Current value: %(expression)s') %
                        {'name': name, 'expression': expression})

        elif hint_type is bool:
            try:
                root_device[name] = strutils.bool_from_string(
                    expression, strict=True)
            except ValueError:
                raise ValueError(
                    _('Root device hint "%(name)s" is not a Boolean value. '
                      'Current value: %(expression)s') %
                    {'name': name, 'expression': expression})

    return _append_operator_to_hints(root_device)


def find_devices_by_hints(devices, root_device_hints):
    """Find all devices that match the root device hints.

    Try to find devices that match the root device hints. In order
    for a device to be matched it needs to satisfy all the given hints.

    :param devices: A list of dictionaries representing the devices
                    containing one or more of the following keys:

        :name: (String) The device name, e.g /dev/sda
        :size: (Integer) Size of the device in *bytes*
        :model: (String) Device model
        :vendor: (String) Device vendor name
        :serial: (String) Device serial number
        :wwn: (String) Unique storage identifier
        :wwn_with_extension: (String): Unique storage identifier with
                             the vendor extension appended
        :wwn_vendor_extension: (String): United vendor storage identifier
        :rotational: (Boolean) Whether it's a rotational device or
                     not. Useful to distinguish HDDs (rotational) and SSDs
                     (not rotational).
        :hctl: (String): The SCSI address: Host, channel, target and lun.
                         For example: '1:0:0:0'.
        :by_path: (String): The alternative device name,
                  e.g. /dev/disk/by-path/pci-0000:00

    :param root_device_hints: A dictionary with the root device hints.
    :raises: ValueError, if some information is invalid.
    :returns: A generator with all matching devices as dictionaries.
    """
    LOG.debug('Trying to find devices from "%(devs)s" that match the '
              'device hints "%(hints)s"',
              {'devs': ', '.join([d.get('name') for d in devices]),
               'hints': root_device_hints})
    parsed_hints = parse_root_device_hints(root_device_hints)
    for dev in devices:
        device_name = dev.get('name')

        for hint in parsed_hints:
            hint_type = VALID_ROOT_DEVICE_HINTS[hint]
            device_value = dev.get(hint)
            hint_value = parsed_hints[hint]

            if hint_type is str:
                try:
                    device_value = _normalize_hint_expression(device_value,
                                                              hint)
                except ValueError:
                    LOG.warning(
                        'The attribute "%(attr)s" of the device "%(dev)s" '
                        'has an empty value. Skipping device.',
                        {'attr': hint, 'dev': device_name})
                    break

            if hint == 'size':
                # Since we don't support units yet we expect the size
                # in GiB for now
                device_value = device_value / units.Gi
                if hint_value.startswith('<range-in>'):
                    device_value = str(device_value)

            LOG.debug('Trying to match the device hint "%(hint)s" '
                      'with a value of "%(hint_value)s" against the same '
                      'device\'s (%(dev)s) attribute with a value of '
                      '"%(dev_value)s"', {'hint': hint, 'dev': device_name,
                                          'hint_value': hint_value,
                                          'dev_value': device_value})

            # NOTE(lucasagomes): Boolean hints are not supported by
            # specs_matcher.match(), so we need to do the comparison
            # ourselves
            if hint_type is bool:
                try:
                    device_value = strutils.bool_from_string(device_value,
                                                             strict=True)
                except ValueError:
                    LOG.warning('The attribute "%(attr)s" (with value '
                                '"%(value)s") of device "%(dev)s" is not '
                                'a valid Boolean. Skipping device.',
                                {'attr': hint, 'value': device_value,
                                 'dev': device_name})
                    break
                if device_value == hint_value:
                    continue

            elif specs_matcher.match(device_value, hint_value):
                continue

            LOG.debug('The attribute "%(attr)s" (with value "%(value)s") '
                      'of device "%(dev)s" does not match the hint %(hint)s',
                      {'attr': hint, 'value': device_value,
                       'dev': device_name, 'hint': hint_value})
            break
        else:
            yield dev


def match_root_device_hints(devices, root_device_hints):
    """Try to find a device that matches the root device hints.

    Try to find a device that matches the root device hints. In order
    for a device to be matched it needs to satisfy all the given hints.

    :param devices: A list of dictionaries representing the devices
                    containing one or more of the following keys:

        :name: (String) The device name, e.g /dev/sda
        :size: (Integer) Size of the device in *bytes*
        :model: (String) Device model
        :vendor: (String) Device vendor name
        :serial: (String) Device serial number
        :wwn: (String) Unique storage identifier
        :wwn_with_extension: (String): Unique storage identifier with
                             the vendor extension appended
        :wwn_vendor_extension: (String): United vendor storage identifier
        :rotational: (Boolean) Whether it's a rotational device or
                     not. Useful to distinguish HDDs (rotational) and SSDs
                     (not rotational).
        :hctl: (String): The SCSI address: Host, channel, target and lun.
                         For example: '1:0:0:0'.
        :by_path: (String): The alternative device name,
                  e.g. /dev/disk/by-path/pci-0000:00

    :param root_device_hints: A dictionary with the root device hints.
    :raises: ValueError, if some information is invalid.
    :returns: The first device to match all the hints or None.
    """
    try:
        dev = next(find_devices_by_hints(devices, root_device_hints))
    except StopIteration:
        LOG.warning('No device found that matches the root device hints %s',
                    root_device_hints)
    else:
        LOG.info('Root device found! The device "%s" matches the root '
                 'device hints %s', dev, root_device_hints)
        return dev


def get_route_source(dest, ignore_link_local=True):
    """Get the IP address to send packages to destination."""
    try:
        out, _err = execute('ip', 'route', 'get', dest)
    except (EnvironmentError, processutils.ProcessExecutionError) as e:
        LOG.warning('Cannot get route to host %(dest)s: %(err)s',
                    {'dest': dest, 'err': e})
        return

    try:
        source = out.strip().split('\n')[0].split('src')[1].split()[0]
        if (ipaddress.ip_address(source).is_link_local
                and ignore_link_local):
            LOG.debug('Ignoring link-local source to %(dest)s: %(rec)s',
                      {'dest': dest, 'rec': out})
            return
        return source
    except (IndexError, ValueError):
        LOG.debug('No route to host %(dest)s, route record: %(rec)s',
                  {'dest': dest, 'rec': out})
