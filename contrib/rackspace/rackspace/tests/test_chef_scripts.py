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

import mox
import os

from ..resources import chef_scripts  # noqa

from test_remote_utils import RemoteStubs


class TestChefScripts(RemoteStubs):
    def setUp(self):
        super(TestChefScripts, self).setUp()
        self.script = chef_scripts.ChefScripts('username', 'host',
                                               'private_key')

    def test_encrypt_data_bag(self):
        databag = 'databag'
        item_path = 'item_path'
        exec_path = 'exec_path'
        config = 'config'
        encrypt = 'encrypt'

        self.m.StubOutWithMock(self.script, 'write_remote_file')
        self.script.write_remote_file(exec_path, 'encrypt_data_bag',
                                      mox.IgnoreArg(), mode=700)

        self.m.StubOutWithMock(self.script, '_execute_remote_command')
        self.script._execute_remote_command(mox.IgnoreArg(),
                                            logfile=('%s/encrypt_data_bag.log'
                                                     % exec_path))

        self.m.ReplayAll()
        self.script.encrypt_data_bag(databag, item_path, config, encrypt,
                                     exec_path=exec_path)
        self.m.VerifyAll()

    def test_write_data_bags(self):
        path = 'path'
        databags = {'db1': {"id": "test"}}

        databag_dir = "/tmp/data_bags"

        self._setup_connection_manager()

        self.m.StubOutWithMock(self.script, 'create_remote_folder')
        self.script.create_remote_folder(path, name='data_bags').AndReturn(
            databag_dir)

        self.script.create_remote_folder(databag_dir, name='db1').AndReturn(
            'databag_path')

        self.m.StubOutWithMock(self.script, 'write_remote_json')
        self.script.write_remote_json('databag_path', 'test.json',
                                      databags['db1'])
        self.m.ReplayAll()
        self.script.write_data_bags(path, databags, mox.IgnoreArg(),
                                    mox.IgnoreArg(), close_connection=True)
        self.m.VerifyAll()

    def test_write_encrypted_data_bags(self):
        path = 'path'
        databags = {'db1': {"id": "test", 'encrypted': True}}
        config = {'knife_path': '/tmp/kitchen/knife.rb',
                  'encrypted_data_bag_secret': 'edbs',
                  'kitchen_path': '/tmp/kitchen'}

        databag_dir = "/tmp/data_bags"

        self._setup_connection_manager()

        self.m.StubOutWithMock(self.script, 'create_remote_folder')
        self.script.create_remote_folder(path, name='data_bags').AndReturn(
            databag_dir)

        self.script.create_remote_folder(databag_dir, name='db1').AndReturn(
            'databag_path')

        self.m.StubOutWithMock(self.script, 'write_remote_json')
        self.script.write_remote_json('databag_path', 'test.json',
                                      databags['db1'])
        self.m.StubOutWithMock(self.script, 'encrypt_data_bag')
        self.script.encrypt_data_bag('db1', 'databag_path/test.json',
                                     config['knife_path'],
                                     config['encrypted_data_bag_secret'],
                                     exec_path=config['kitchen_path'])

        self.m.ReplayAll()
        self.script.write_data_bags(path, databags,
                                    config['kitchen_path'],
                                    config['knife_path'],
                                    data_bag_secret=
                                    config['encrypted_data_bag_secret'],
                                    close_connection=True)
        self.m.VerifyAll()

    def test_bootstrap(self):
        exec_path = 'exec_path'

        outputs = dict(output=os.path.join(exec_path, 'install.sh'),
                       url="https://www.opscode.com/chef/install.sh",
                       version='')
        script = ("wget -O %(output)s %(url)s\n"
                  "bash %(output)s %(version)s" % outputs)

        wrap = ("#!/bin/bash -x\n"
                "cd %(path)s\n"
                "%(script)s"
                % dict(path=exec_path, script=script))
        self.m.StubOutWithMock(self.script, 'write_remote_file')
        self.script.write_remote_file(exec_path, 'bootstrap',
                                      wrap, mode=700)

        self.m.StubOutWithMock(self.script, '_execute_remote_command')
        self.script._execute_remote_command(mox.IgnoreArg(),
                                            logfile=('%s/bootstrap.log'
                                                     % exec_path))

        self.m.ReplayAll()
        self.script.bootstrap(exec_path=exec_path)
        self.m.VerifyAll()
