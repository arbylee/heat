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

import json
import os
import paramiko
import tempfile

from eventlet import sleep
from functools import wraps

from heat.common import exception
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


def connection_manager(function):
    """This decorator handles cleaning up sftp connections.
    :kwarg close_connection: True if you would like to close the connection
        after the function is called. Default False
    :kwarg close_on_error: Close the connection if there was an error. Default
        True.
    :kwarg retry: True if the function should be retried when a connection
        error happens. Default False.
    """
    @wraps(function)
    def wrapper(remote, *args, **kwargs):
            assert isinstance(remote, RemoteCommands)

            close_connection = kwargs.get('close_connection', False)
            close_on_error = kwargs.get('close_on_error', True)
            retry = kwargs.get('retry', False)
            try:
                return function(remote, *args, **kwargs)
            except (EOFError, paramiko.SSHException):
                if retry is True:
                    remote.reconnect_sftp()
                    return function(remote, *args, **kwargs)
                else:
                    raise
            except Exception as e:
                if (not remote.sftp_connection.sock.closed) and close_on_error:
                    remote.sftp_connection.close()
                raise e
            finally:
                if close_connection:
                    if not remote.sftp_connection.sock.closed:
                        remote.sftp_connection.close()
    return wrapper


class RemoteCommandException(exception.HeatException):
    def __init__(self, **kwargs):
        self.msg_fmt = _("Host:%(host)s\n"
                         "Output:\n%(output)s\n"
                         "Command:%(command)s\n"
                         "Exit Code:%(exit_code)s\n"
                         "Remote Log:%(remote_log)s")
        super(RemoteCommandException, self).__init__(**kwargs)


class RemoteCommands(object):
    """Must call connection_info(username, host, private_key)."""

    def __init__(self, username, host, private_key):
        self.private_key = private_key
        self.username = username
        self.host = host
        self._sftp_connection = None

    def get_sftp_connection(self, username, host, private_key):
        with tempfile.NamedTemporaryFile() as private_key_file:
            private_key_file.write(private_key)
            private_key_file.seek(0)
            pkey = paramiko.RSAKey.from_private_key_file(
                private_key_file.name)

            transport = None
            for x in range(0, 30):
                try:
                    transport = paramiko.Transport((host, 22))
                    transport.connect(hostkey=None, username=username,
                                      pkey=pkey)
                    return paramiko.SFTPClient.from_transport(transport)
                except Exception as e:
                    logger.debug(str(e))
                    sleep(seconds=5)
            raise

    @property
    def sftp_connection(self):
        if self._sftp_connection is None or self._sftp_connection.sock.closed:
            self._sftp_connection = self.get_sftp_connection(self.username,
                                                             self.host,
                                                             self.private_key)
        return self._sftp_connection

    def reconnect_sftp(self):
        if not self._sftp_connection.sock.closed:
            self._sftp_connection.close()
        self._sftp_connection = self.get_sftp_connection(self.username,
                                                         self.host,
                                                         self.private_key)

    @connection_manager
    def create_remote_folder(self, path, name=None):
        if name:
            folder = os.path.join(path, name)
        else:
            folder = path

        try:
            self.sftp_connection.mkdir(folder)
        except IOError as ioe:
            if ioe.errno == 13:
                logger.warn(_("Permission denied to create %(folder)s on "
                              "%(remote)s") % dict(folder=folder,
                                                   remote=self.host))
                raise ioe
            logger.warn(_("There was an error creating the remote folder "
                          "%(folder)s. The remote folder already exists."
                          ) % dict(folder=folder))
        return folder

    @connection_manager
    def read_remote_file(self, path):
        with self.sftp_connection.open(path, 'r') as remote_file:
            return [x for x in remote_file]

    @connection_manager
    def write_remote_file(self, path, name, data, mode=None):
        remote_file = os.path.join(path, name)
        sftp_file = None
        try:
            sftp_file = self.sftp_connection.open(remote_file, 'w')
            sftp_file.write(data)
            if mode is not None:
                self.sftp_connection.chmod(remote_file, mode)
        finally:
            if sftp_file is not None:
                sftp_file.close()
        return remote_file

    @connection_manager
    def write_remote_json(self, path, name, data):
        return self.write_remote_file(path, name, json.dumps(data))

    def execute_remote_command(self, name, script, save=True, logfile=None,
                               exec_path='/tmp'):
        logger.debug(_("Executing remote script %(name)s.") % {'name': name})
        wrap = ("#!/bin/bash -x\n"
                "cd %(path)s\n"
                "%(script)s"
                % dict(path=exec_path,
                       script=script))

        if save:
            if logfile is None:
                logfile = os.path.join(exec_path, name + ".log")

            script_path = self.write_remote_file(exec_path, name, wrap,
                                                 mode=700)
            command = "%s > %s 2>&1" % (script_path, logfile)
            return self._execute_remote_command(command, logfile=logfile)
        else:
            return self._execute_remote_command(wrap)

    def _execute_remote_command(self, command, logfile=None):
        """Executes a remote command over ssh without blocking."""
        with tempfile.NamedTemporaryFile() as private_key_file:
            private_key_file.write(self.private_key)
            private_key_file.seek(0)
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(
                    paramiko.MissingHostKeyPolicy())
                ssh.connect(self.host,
                            username=self.username,
                            key_filename=private_key_file.name)

                logger.debug("Executing command:%s" % command)
                x, stdout_buf, stderr_buf = ssh.exec_command(command)

                exit_code = stdout_buf.channel.recv_exit_status()
                stdout, stderr = (stdout_buf.read(), stderr_buf.read())
                if exit_code != 0:
                    if logfile is not None:
                        logger.debug("Reading remote log:%s" % logfile)
                        output = self.read_remote_file(logfile)
                    else:
                        output = stderr
                    raise RemoteCommandException(command=command,
                                                 exit_code=exit_code,
                                                 remote_log=logfile,
                                                 output=output,
                                                 host=self.host)
                else:
                    return(stdout, stderr)
            finally:
                if ssh:
                    ssh.close()


def remote_execute(function):
    """
    kwargs (The decorated function should accept):
        :kwarg exec_path: The path to execute the remote command in. defaults
               to /tmp
        :kwarg logfile: The file contents to return in the event of an error.

        ex: function(self, logfile=None, exec_path=None)

    returns (The function should return):
        :returns dict:
            :key script: The commands to execute.
            :key save: True if the script should be saved on the
                remote server.
            :key post_run: A function to call after the script is executed.

        ex: return dict(script="ls -al", save=True)
    """
    @wraps(function)
    def wrapper(remote, *args, **kwargs):
        assert isinstance(remote, RemoteCommands)
        # Get function kwargs
        logfile = kwargs.get('logfile', None)
        exec_path = kwargs.get('exec_path', '/tmp')

        results = function(remote, *args, **kwargs)

        # Get function return values
        save = results.get('save', True)
        script = results['script']
        post_run = results.get('post_run', lambda: None)

        name = function.__name__
        try:
            return remote.execute_remote_command(name, script, save=save,
                                                 logfile=logfile,
                                                 exec_path=exec_path)
        except Exception:
            raise
        else:
            post_run()
    return wrapper
