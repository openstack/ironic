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
import os
from unittest import mock

from oslo_config import cfg

from ironic.common import kickstart_utils as ks_utils
from ironic.conductor import task_manager
from ironic.drivers.modules import ipxe
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as object_utils

CONF = cfg.CONF
INST_INFO_DICT = db_utils.get_test_pxe_instance_info()
DRV_INFO_DICT = db_utils.get_test_pxe_driver_info()
DRV_INTERNAL_INFO_DICT = db_utils.get_test_pxe_driver_internal_info()
CONFIG_DRIVE = ('H4sICDw0S2AC/3RtcGhYdnFvdADt3X1vFMcdAOBZkwbTIquiL6oiJ9kkkJBKN'
                'mcTkTiVKl3Oa3uTe9PdOYK/0AmOvNqO4IJatZWav5pK/UztV8kXiPoR2tm98x'
                's+fCQQMPA8i71zs7Mz4/VJvx0vMxcCAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
                'AAAAAAAAAAJDUViuVpSTU8+bm1fT+buxs3/rsk4Xl+x3fre8/h3bHtBv/FV9h'
                'dja8P8p6/9f7h39bfHs9zI9ezYfZYjcb/nzqbDI//93M7vnpE7bTH36a7nw12'
                'L4z7N/4Ih0O+lvp82Q9a+bdVt6ormdpTKQrV65ULm2sddO1vJ51r3V7WSOtdb'
                'Jqr9VJL9beTpdWVi6n2eK11mZzfbVaz3Yz311YrlSupB8utrNqp9tqXvpwsVv'
                'byOvxXblelikOF2XeTWurnY/yXtrLqo3H/uMuV5aXKpeXlitLy+8tv1epfHck'
                'o3KPcKTEk3/T8mQJOpwYM+P4H+ohD82wGa6GdOJ2I+yE7XArfBY+CQth+cjxe'
                '+L/hUvZA8f/5iir+bv9wy+N4v+42vR+8f8+fX18207oh2H4tEx9FQbxCt2Jr/'
                'vxan0R84Yxpx+2nngvf7ptPWTx15eHbmjF741QLXPScU4aVsKVuFXC9bAR1mJ'
                'eGr/n8b2WxfS1+NWLqUbMrYVOTFXj61ZMpeFizHk77pdiDSvhckxlYTGe0Yrv'
                '0GZsYzWWrZctTd8eXSHxH/GfZ8j/duM/AAAA8MxKymfsxfj/THi5TO09zg6nw'
                '6sxZybc2NkeDraH4cXwSvn6y/5wcGfo2gEAAMDTM/4Pxf+vT4rxf/RySA6O/6'
                'NXw8z++D96JcwY/wMAAMDTNv5Px38FOBdeG6WOzGSbC2+E4rn/eA7gsDw6PBt'
                'eH+V+Wc6BG5TlAQAAgBM5/g/F2idJMf6PXismABwd/0dvFBMBDo//Q7FEz4zx'
                'PwAAAJx0305dY7/bPp38+7+h0/lZ8k376vlkq1qUq26dGp136t4ae2svJXPjS'
                'g7vatl8cn5U6Pxu6e/Hu1vT+pE8gg6Ev5ZrHIRinsPEVs7sTX4oWvtnszF3YD'
                '2Eg22/MKrmhR/QNgCcHLemRMTkaOD/EbHv8UT3P5XrFYVizuLEVk6PJzKOY/v'
                'ZZHdlo4PtzoyqmPkB7d4t10UKxdzIie2+OJ4wOW73F8l4BaWHbBYAHiL+Hx+7'
                'JsT/HxGqpt5lJI/iLuPbcGFU5sJuF/dDZdHKL7cGw/71m/1hf/HzOzvbf1jaj'
                'ci/SkJxaGHvUNGR898UVXxzfvzZCMmDd+Tv4c1RkTfnRvu5w/04+/Wdwe1RP/'
                'b7MJeEveyHaz78K7w1KvPW5Otw7u5g++bO7UlX4jdJuPfgQ3YGgBMa/48fMz9'
                'N8X8YLo7KXJwd7WcPx73TxSeyxZA7jnVnklBkiG8APH+mf8bu1BLJO+XKAaGY'
                'PTCxxLkJH44LADzJ+H987H6Q+F8p1wcKxRzBiSXmDk8cDIvlykFl4xPLnzWlE'
                'AB+4vh/fCxOpt8hJH+c8tx9PmzFWF6M/BfCzTKy9+M9wOcxuhd3Be9MeVp+Ln'
                'wdSw7C7XB97+wPpjzhTsPd8l7jZmzh4Hn7rQLA8x3/jx+7P0j8//2U5+6zoTL'
                'eAICTIOt8n/y894+k08nb15dWVpaqvY0s7bRqH6WdfHU9S/NmL+vUNqrNmG53'
                'Wr1WrVUvEh/nq1k37W62261OL11rddJ2q5tfTdfyepZ2r3V7WSPtZo1qs5fXu'
                'u16Vu1maa3V7FVrvXQ179bS9uYH9by7kXXKk7vtrJav5bVqL281025rs1PLFt'
                'NYQ3agYGwyVreWF8lm7ETeqHaupR+36puNLI3dqcUfotcaVbjbVt6MrxpltYt'
                '+3QBQ+svfXAMAeN4U69CkexPPXQ8AMP4HAJ5F24PhgpE/AAAAAAAAAAAAAAAA'
                'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
                'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
                'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
                'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
                'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
                'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
                'AAAAAAAAAAAAAAAAAn3f8BeXAIEgD4BQA=')


@mock.patch.object(ipxe.iPXEBoot, '__init__', lambda self: None)
class KSUtilsTestCase(db_base.DbTestCase):
    def setUp(self):
        super(KSUtilsTestCase, self).setUp()
        n = {
            'driver': 'fake-hardware',
            'boot_interface': 'ipxe',
            'instance_info': INST_INFO_DICT,
            'driver_info': DRV_INFO_DICT,
            'driver_internal_info': DRV_INTERNAL_INFO_DICT,
        }
        self.config(enabled_boot_interfaces=['ipxe'])
        self.config_temp_dir('http_root', group='deploy')
        self.node = object_utils.create_test_node(self.context, **n)
        self.config_drive_dict = {
            "openstack/content/0000": "net-data",
            "openstack/latest/meta-data.json": "{}",
            "openstack/latest/user_data": "test user_data",
            "openstack/latest/vendor_data.json": "{}"
        }

    def _get_expected_ks_config_drive(self, config_drive_dict):
        config_drive_ks_template = """\
\n%post\nDIRPATH=`/usr/bin/dirname {file_path}`\n\
/bin/mkdir -p $DIRPATH\n\
CONTENT='{content}'\n\
echo $CONTENT | /usr/bin/base64 --decode > {file_path}\n\
/bin/chmod 600 {file_path}\n\
%end\n\n"""

        target_path = '/var/lib/cloud/seed/config_drive'
        config_drive_ks = ''
        for key in sorted(config_drive_dict.keys()):
            config_drive_ks += config_drive_ks_template.format(
                file_path=os.path.join(target_path, key),
                content=base64.b64encode(str.encode(config_drive_dict[key]))
            )
        return config_drive_ks

    def test_prepare_config_drive(self):

        expected = self._get_expected_ks_config_drive(self.config_drive_dict)
        with task_manager.acquire(self.context, self.node.uuid) as task:
            i_info = task.node.instance_info
            i_info['configdrive'] = self.config_drive_dict
            task.node.instance_info = i_info
            task.node.save()
            self.assertEqual(expected, ks_utils.prepare_config_drive(task))

    @mock.patch('requests.get', autospec=True)
    def test_prepare_config_drive_in_swift(self, mock_get):
        expected = self._get_expected_ks_config_drive(self.config_drive_dict)
        mock_get.return_value = mock.MagicMock(content=CONFIG_DRIVE)
        with task_manager.acquire(self.context, self.node.uuid) as task:
            i_info = task.node.instance_info
            i_info['configdrive'] = 'http://server/fake-configdrive-url'
            task.node.instance_info = i_info
            task.node.save()
            self.assertEqual(expected, ks_utils.prepare_config_drive(task))
            mock_get.assert_called_with('http://server/fake-configdrive-url')
