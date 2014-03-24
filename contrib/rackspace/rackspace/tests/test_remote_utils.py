#    vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import paramiko

from ..resources import remote_utils  # noqa

from heat.tests.common import HeatTestCase


class RemoteStubs(HeatTestCase):
    def setUp(self):
        super(RemoteStubs, self).setUp()
        self.script = remote_utils.RemoteCommands('username', 'host',
                                                  'private_key')

    def _setup_connection_manager(self, closed=False):
        self.m.StubOutWithMock(self.script.__class__, 'sftp_connection')
        self.m.StubOutWithMock(self.script.sftp_connection, 'sock')
        self.m.StubOutWithMock(self.script.sftp_connection.sock, 'closed')
        self.script.sftp_connection.sock.closed = closed
        self.m.StubOutWithMock(self.script.sftp_connection, 'close')
        self.script.sftp_connection.close().AndReturn(None)


class TestRemoteUtils(RemoteStubs):
    def test_connection_manager_close_connection(self):
        self._setup_connection_manager()
        self.m.ReplayAll()

        def test(self, close_connection=True):
            pass
        remote_utils.connection_manager(test)(self.script,
                                              close_connection=True)
        self.m.VerifyAll()

    def test_connection_manager_close_on_error(self):
        self._setup_connection_manager()
        self.m.ReplayAll()

        def test(self, close_on_error=True):
            raise ValueError
        wrapped = remote_utils.connection_manager(test)
        self.assertRaises(ValueError, wrapped, self.script,
                          close_on_error=True)
        self.m.VerifyAll()

    def _stub_execute_remote_command(self, exit_code=0, logfile=None,
                                     stdout='stdout', stderr='stderr',
                                     command='ls',
                                     close=True):
        self.m.StubOutWithMock(paramiko, "SSHClient")
        self.m.StubOutWithMock(paramiko, "MissingHostKeyPolicy")
        ssh = self.m.CreateMockAnything()
        paramiko.SSHClient().AndReturn(ssh)
        paramiko.MissingHostKeyPolicy()
        ssh.set_missing_host_key_policy(None)
        ssh.connect(self.script.host,
                    username=self.script.username,
                    key_filename=mox.IgnoreArg())

        stdout_buf = self.m.CreateMockAnything()
        stderr_buf = self.m.CreateMockAnything()
        ssh.exec_command(command).AndReturn(('x', stdout_buf, stderr_buf))

        stdout_buf.channel = self.m.CreateMockAnything()
        stdout_buf.channel.recv_exit_status().AndReturn(exit_code)
        stdout_buf.read().AndReturn(stdout)
        stderr_buf.read().AndReturn(stderr)
        if close:
            ssh.close()
        return ssh

    def test_execute_remote_command_pass(self):
        self._stub_execute_remote_command()
        self.m.ReplayAll()
        (stdout, stderr) = self.script._execute_remote_command('ls')
        self.m.VerifyAll()
        self.assertEqual(stdout, 'stdout')
        self.assertEqual(stderr, 'stderr')

    def test_execute_remote_command_fail_no_log(self):
        self._stub_execute_remote_command(exit_code=1)
        self.m.ReplayAll()
        self.assertRaises(remote_utils.RemoteCommandException,
                          self.script._execute_remote_command, 'ls')
        self.m.VerifyAll()

    def test_execute_remote_command_fail_with_log(self):
        ssh = self._stub_execute_remote_command(exit_code=1, logfile='log',
                                                close=False)
        self.m.StubOutWithMock(self.script, 'read_remote_file')
        self.script.read_remote_file('log')
        ssh.close()
        self.m.ReplayAll()
        self.assertRaises(remote_utils.RemoteCommandException,
                          self.script._execute_remote_command,
                          'ls', logfile='log')
        self.m.VerifyAll()

    def test_remote_execute_save(self):
        path = "/tmp"
        logfile = "/tmp/log"

        @remote_utils.remote_execute
        def test_fn(self, path=path, logfile=logfile):
            return dict(script="ls -al", save=True)

        script_path = os.path.join("/tmp", test_fn.__name__)

        wrap = ("#!/bin/bash -x\n"
                "cd %(path)s\n"
                "%(script)s"
                % dict(path=path,
                       script="ls -al"))

        self.m.StubOutWithMock(self.script, 'write_remote_file')
        self.script.write_remote_file(path, test_fn.__name__, wrap,
                                      mode=700).AndReturn(script_path)

        command = "%s > %s 2>&1" % (script_path, logfile)
        self._stub_execute_remote_command(command=command)
        self.m.ReplayAll()
        test_fn(self.script, path="/tmp", logfile="/tmp/log")
        self.m.VerifyAll()

    def test_remote_execute_no_save(self):
        path = "/tmp"
        logfile = "/tmp/log"

        @remote_utils.remote_execute
        def test_fn(self, path=path, logfile=logfile):
            return dict(script="ls -al", save=False)

        os.path.join("/tmp", test_fn.__name__)

        wrap = ("#!/bin/bash -x\n"
                "cd %(path)s\n"
                "%(script)s"
                % dict(path=path,
                       script="ls -al"))

        self._stub_execute_remote_command(command=wrap)
        self.m.ReplayAll()
        test_fn(self.script, path="/tmp")
        self.m.VerifyAll()

    def test_remote_execute_no_logfile(self):
        path = "/tmp"

        @remote_utils.remote_execute
        def test_fn(self, path=path):
            return dict(script="ls -al", save=True)

        script_path = os.path.join("/tmp", test_fn.__name__)

        wrap = ("#!/bin/bash -x\n"
                "cd %(path)s\n"
                "%(script)s"
                % dict(path=path,
                       script="ls -al"))

        self.m.StubOutWithMock(self.script, 'write_remote_file')
        self.script.write_remote_file(path, test_fn.__name__, wrap,
                                      mode=700).AndReturn(script_path)

        created_logfile = os.path.join(path, test_fn.__name__ + ".log")
        command = "%s > %s 2>&1" % (script_path, created_logfile)
        self._stub_execute_remote_command(command=command,
                                          logfile=created_logfile)
        self.m.ReplayAll()
        test_fn(self.script, path="/tmp")
        self.m.VerifyAll()
