# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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
Handling of VM disk images.
"""

import os

from oslo.config import cfg

from ironic.common import exception
from ironic.common import image_service as service
from ironic.common import utils
from ironic.openstack.common import fileutils
from ironic.openstack.common import imageutils
from ironic.openstack.common import log as logging

LOG = logging.getLogger(__name__)

image_opts = [
    cfg.BoolOpt('force_raw_images',
                default=True,
                help='Force backing images to raw format.'),
]

CONF = cfg.CONF
CONF.register_opts(image_opts)


def qemu_img_info(path):
    """Return an object containing the parsed output from qemu-img info."""
    if not os.path.exists(path):
        return imageutils.QemuImgInfo()

    out, err = utils.execute('env', 'LC_ALL=C', 'LANG=C',
                             'qemu-img', 'info', path)
    return imageutils.QemuImgInfo(out)


def convert_image(source, dest, out_format, run_as_root=False):
    """Convert image to other format."""
    cmd = ('qemu-img', 'convert', '-O', out_format, source, dest)
    utils.execute(*cmd, run_as_root=run_as_root)


def fetch(context, image_href, path, image_service=None):
    # TODO(vish): Improve context handling and add owner and auth data
    #             when it is added to glance.  Right now there is no
    #             auth checking in glance, so we assume that access was
    #             checked before we got here.
    if not image_service:
        image_service = service.Service(version=1, context=context)

    with fileutils.remove_path_on_error(path):
        with open(path, "wb") as image_file:
            image_service.download(image_href, image_file)


def fetch_to_raw(context, image_href, path, image_service=None):
    path_tmp = "%s.part" % path
    fetch(context, image_href, path_tmp, image_service)
    image_to_raw(image_href, path, path_tmp)


def image_to_raw(image_href, path, path_tmp):
    with fileutils.remove_path_on_error(path_tmp):
        data = qemu_img_info(path_tmp)

        fmt = data.file_format
        if fmt is None:
            raise exception.ImageUnacceptable(
                    reason=_("'qemu-img info' parsing failed."),
                    image_id=image_href)

        backing_file = data.backing_file
        if backing_file is not None:
            raise exception.ImageUnacceptable(image_id=image_href,
                reason=_("fmt=%(fmt)s backed by: %(backing_file)s") %
                                              {'fmt': fmt,
                                               'backing_file': backing_file})

        if fmt != "raw" and CONF.force_raw_images:
            staged = "%s.converted" % path
            LOG.debug("%(image)s was %(format)s, converting to raw" %
                    {'image': image_href, 'format': fmt})
            with fileutils.remove_path_on_error(staged):
                convert_image(path_tmp, staged, 'raw')
                os.unlink(path_tmp)

                data = qemu_img_info(staged)
                if data.file_format != "raw":
                    raise exception.ImageConvertFailed(image_id=image_href,
                        reason=_("Converted to raw, but format is now %s") %
                                 data.file_format)

                os.rename(staged, path)
        else:
            os.rename(path_tmp, path)


def download_size(context, image_href, image_service=None):
    if not image_service:
        image_service = service.Service(version=1, context=context)
    return image_service.show(image_href)['size']
