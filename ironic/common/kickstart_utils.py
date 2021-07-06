# Copyright 2021 Verizon Media
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
import base64
import gzip
import io
import os
import tempfile

from ironic_lib import utils as ironic_utils
from oslo_log import log as logging
import pycdlib
import requests

from ironic.common import exception

LOG = logging.getLogger(__name__)


def _get_config_drive_dict_from_iso(
        iso_reader, drive_dict,
        target_path='/var/lib/cloud/seed/config_drive'):
    """Traverse the config drive iso and extract content and filenames

    :param iso_reader: pycdlib.PyCdlib object representing ISO files.
    :param drive_dict: Mutable dictionary to store path and contents.
    :param target_path: Path on the local disk in which the files in config
                        drive files has to be written.
    """
    for path, dirlist, filelist in iso_reader.walk(iso_path='/'):
        for f in filelist:
            # In iso9660 file extensions are mangled. Example '/FOO/BAR;1'.
            iso_file_path = os.path.join(path, f)
            file_record = iso_reader.get_record(iso_path=iso_file_path)
            # This converts /FOO/BAR;1 -> /foo/bar
            posix_file_path = iso_reader.full_path_from_dirrecord(
                file_record, rockridge=True
            )
            # Path to which the file in config drive to be written on the
            # server.
            posix_file_path = posix_file_path.lstrip('/')
            target_file_path = os.path.join(target_path, posix_file_path)
            b_buf = io.BytesIO()
            iso_reader.get_file_from_iso_fp(
                iso_path=iso_file_path, outfp=b_buf
            )
            b_buf.seek(0)
            content = b"\n".join(b_buf.readlines()).decode('utf-8')
            drive_dict[target_file_path] = content


def read_iso9600_config_drive(config_drive):
    """Read config drive and store it's contents in a dict

    :param config_drive: Config drive in iso9600 format
    :returns: A dict containing path as key and contents of the configdrive
              file as value.
    """
    config_drive_dict = dict()
    with tempfile.NamedTemporaryFile(suffix='.iso') as iso:
        iso.write(config_drive)
        iso.flush()
        try:
            iso_reader = pycdlib.PyCdlib()
            iso_reader.open(iso.name)
            _get_config_drive_dict_from_iso(iso_reader, config_drive_dict)
            iso_reader.close()
        except Exception as e:
            msg = "Error reading the config drive iso: %s" % e
            LOG.error(msg)
    return config_drive_dict


def decode_and_extract_config_drive_iso(config_drive_iso_gz):
    try:
        iso_gz_obj = io.BytesIO(base64.b64decode(config_drive_iso_gz))
        iso_gz_obj.seek(0)
    except Exception as exc:
        if isinstance(config_drive_iso_gz, bytes):
            LOG.debug('Config drive is not base64 encoded (%(error)s), '
                      'assuming binary', {'error': exc})
            iso_gz_obj = config_drive_iso_gz
        else:
            error_msg = ('Config drive is not base64 encoded or the content '
                         'is malformed. %(cls)s: %(err)s.'
                         % {'err': exc, 'cls': type(exc).__name__})
            raise exception.InstanceDeployFailure(error_msg)

    try:
        with gzip.GzipFile(fileobj=iso_gz_obj, mode='rb') as f:
            config_drive_iso = f.read()
    except Exception as exc:
        error_msg = "Decoding/Extraction of config drive failed: %s" % exc
        raise exception.InstanceDeployFailure(error_msg)
    return config_drive_iso


def _fetch_config_drive_from_url(url):
    try:
        config_drive = requests.get(url).content
    except requests.exceptions.RequestException as e:
        raise exception.InstanceDeployFailure(
            "Can't download the configdrive content from '%(url)s'. "
            "Reason: %(reason)s" %
            {'url': url, 'reason': e})
    config_drive_iso = decode_and_extract_config_drive_iso(config_drive)
    return read_iso9600_config_drive(config_drive_iso)


def _write_config_drive_content(content, file_path):
    """Generate post ks script to write each userdata content."""

    content = base64.b64encode(str.encode(content))
    kickstart_data = []
    kickstart_data.append("\n")
    kickstart_data.append("%post\n")
    kickstart_data.append(("DIRPATH=`/usr/bin/dirname "
                           "{file_path}`\n").format(
        file_path=file_path))
    kickstart_data.append("/bin/mkdir -p $DIRPATH\n")
    kickstart_data.append("CONTENT='{content}'\n".format(
        content=content))
    kickstart_data.append("echo $CONTENT | "
                          "/usr/bin/base64 --decode > "
                          "{file_path}".format(file_path=file_path))
    kickstart_data.append("\n")
    kickstart_data.append(
        "/bin/chmod 600 {file_path}\n".format(file_path=file_path)
    )
    kickstart_data.append("%end\n\n")

    return "".join(kickstart_data)


def prepare_config_drive(task,
                         config_drive_path='/var/lib/cloud/seed/config_drive'):
    """Prepare config_drive for writing to kickstart file"""
    LOG.debug("Preparing config_drive to write to kickstart file")
    node = task.node
    config_drive = node.instance_info.get('configdrive')
    ks_config_drive = ''
    if not config_drive:
        return ks_config_drive

    if not isinstance(config_drive, dict) and \
            ironic_utils.is_http_url(config_drive):
        config_drive = _fetch_config_drive_from_url(config_drive)

    for key in sorted(config_drive.keys()):
        target_path = os.path.join(config_drive_path, key)
        ks_config_drive += _write_config_drive_content(
            config_drive[key], target_path
        )

    return ks_config_drive
