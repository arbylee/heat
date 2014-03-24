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

from Crypto.PublicKey import RSA
import os
from oslo.config import cfg
import subprocess

from heat.openstack.common.gettextutils import _

from .remote_utils import connection_manager  # noqa
from .remote_utils import remote_execute  # noqa
from .remote_utils import RemoteCommands  # noqa

from .chef_solo import ChefSolo  # noqa

chef_ops = [
    cfg.StrOpt('rubygem_path',
               default="/opt/chef/embedded/bin",
               help=_('Path where the gem binary is located.')),
    cfg.StrOpt('berkshelf_version',
               default="2.0.15",
               help=_('The version of berkshelf to install on the client '
                      'instance.')),
    cfg.StrOpt('librarian_chef_version',
               default="0.0.2",
               help=_('The version of librarian-chef to install on the client '
                      'instance.')),
]
cfg.CONF.register_opts(chef_ops)


class ChefScripts(RemoteCommands):
    def __init__(self, username, host, private_key):
        super(ChefScripts, self).__init__(username, host, private_key)

        self.COOKBOOKS, self.ENCRYPTED = ('cookbooks', 'encrypted')

    def execute_command(self, path, command):
        cmd = ("set -e\n"
               "cd %(path)s\n"
               "%(command)s" % dict(path=path, command=command))
        return subprocess.check_output(cmd,
                                       shell=True,
                                       stderr=subprocess.STDOUT,
                                       executable="/bin/bash")

    @connection_manager
    def create_secrets_file(self, path, name):
        key = RSA.generate(2048)
        self.secret_key = key.exportKey('PEM')
        return self.write_remote_file(path, name, self.secret_key)

    @remote_execute
    def encrypt_data_bag(self, databag, item_path, config_path,
                         databag_secret_path, exec_path=None):
        outputs = dict(databag=databag,
                       path=item_path,
                       config=config_path,
                       encrypt=databag_secret_path)
        return dict(script="knife data bag from file %(databag)s %(path)s -c "
                           "%(config)s --secret-file %(encrypt)s -z" % outputs)

    @connection_manager
    def write_data_bags(self, path, data_bags, kitchen_path,
                        knife_path, close_connection=False,
                        data_bag_secret=None):
        databag_dir = self.create_remote_folder(path, name=ChefSolo.DATA_BAGS)
        for data_bag, item in data_bags.iteritems():
            databag_path = self.create_remote_folder(databag_dir,
                                                     name=data_bag)
            #write databags
            item_name = item['id'] + ".json"
            if self.ENCRYPTED in item and item[self.ENCRYPTED] is True:
                del item[self.ENCRYPTED]
                item_path = os.path.join(databag_path, item_name)
                self.write_remote_json(databag_path, item_name, item)
                self.encrypt_data_bag(data_bag,
                                      item_path,
                                      knife_path,
                                      data_bag_secret,
                                      exec_path=kitchen_path)
            else:
                self.write_remote_json(databag_path, item_name, item)
        return databag_dir

    @remote_execute
    def bootstrap(self, version=None, exec_path=None):
        outputs = dict(output=os.path.join(exec_path, 'install.sh'),
                       url="https://www.opscode.com/chef/install.sh",
                       version=' -v %s' % str(version) if version else '')

        return dict(script="wget -O %(output)s %(url)s\n"
                           "bash %(output)s %(version)s"
                           % outputs)

    def get_knife_command(self, knife_path, node_file, command):
        return "knife %s -c %s -z -j %s" % (command,
                                            knife_path,
                                            node_file)

    @remote_execute
    def run_chef(self, knife_config_path, node_file, exec_path=None):
        return dict(script="chef-solo -c %s -j %s"
                    % (knife_config_path, node_file))

    def create_kitchen_folder(self, properties, prop, kitchen_path):
        if properties.get(prop) is not None:
            path = self.create_remote_folder(kitchen_path, name=prop)
            for name, contents in properties[prop].iteritems():
                self.write_remote_json(path, name, contents)

    def _update_package_manager(self):
        return """
        case node[:platform]
        when "redhat", "centos"
          execute "yum makecache"
        when "ubuntu", "debian"
          execute 'apt-get update'
        end
         """

    def installer_dependencies(self, installer, kitchen_path, cookbook_path,
                               version, gem_path=cfg.CONF.rubygem_path):
        script = """
        %s
        case node[:platform]
        when "redhat", "centos"
          package "ruby-devel"
          package "avr-gcc-c++"
          package "gecode-devel"
          package "gcc-c++"
        when "ubuntu", "debian"
          package "libgecode-dev"
          package "ruby1.9.1-dev"
          package "g++"
        end
        package "gcc"
        package "make"
        package "git"

        ENV["USE_SYSTEM_GECODE"] = "1"

        gem_package "%s" do
          gem_binary("%s")
          version "%s"
        end""" % (self._update_package_manager(), installer,
                  os.path.join(gem_path, 'gem'), version)
        self.run_recipe('installer_dependencies', script, kitchen_path,
                        cookbook_path, gem_path=gem_path)

    def run_recipe(self, cookbook_name, recipe, kitchen_path, cookbook_path,
                   gem_path=cfg.CONF.rubygem_path):
        cookbook = self.create_remote_folder(cookbook_path, cookbook_name)
        recipes = self.create_remote_folder(cookbook, 'recipes')
        self.write_remote_file(recipes, 'default.rb', recipe)

        kniferb = self.write_remote_file(kitchen_path,
                                         'knife.rb',
                                         'cookbook_path "%s"' % cookbook_path)
        nodejson = self.write_remote_json(
            kitchen_path, 'localhost.json', {'run_list': [
                                             'recipe[%s]' % cookbook_name]})

        self.execute_remote_command('run_recipe',
                                    'chef-solo -c %s -j %s' % (kniferb,
                                                               nodejson))

    def install_cookbooks(self, properties, kitchen_path, cookbook_path,
                          rubygem_path=cfg.CONF.rubygem_path):
        installer_content = properties.get(ChefSolo.BERKSFILE)
        installer_type = None
        if installer_content is not None:
            installer_type = ChefSolo.BERKSFILE
            installer_cmd = 'berks'
            installer_package = 'berkshelf'
            version = cfg.CONF.berkshelf_version
            lock_file = properties.get('Berksfile.lock')
        else:
            installer_content = properties.get(ChefSolo.CHEFFILE)
            installer_type = ChefSolo.CHEFFILE
            installer_cmd = 'librarian-chef'
            installer_package = 'librarian-chef'
            version = cfg.CONF.librarian_chef_version
            lock_file = None

        if installer_content is not None:
            self.installer_dependencies(installer_package, kitchen_path,
                                        cookbook_path, version)
            # Write Berksfile/Cheffile
            self.write_remote_file(kitchen_path, installer_type,
                                   installer_content)
            if lock_file is not None:
                self.write_remote_file(kitchen_path,
                                       "%s.lock" % installer_type, lock_file)

            installer_path = os.path.join(rubygem_path, installer_cmd)
            self.execute_remote_command('install_cookbooks',
                                        ("%s install --path %s"
                                         % (installer_path, cookbook_path)),
                                        exec_path=kitchen_path)

    def databags(self, properties, kitchen_path, knife_path):
        data_bag_secret = None
        if properties.get(ChefSolo.DATA_BAGS) is not None:
            for data_bag, item in properties[ChefSolo.DATA_BAGS].iteritems():
                if 'encrypted' in item:
                    secrets_path = self.create_remote_folder(kitchen_path,
                                                             name=
                                                             'certificates')
                    #write encrypted data bag secret if we have any encrypted
                    #data_bags
                    data_bag_secret = self.create_secrets_file(secrets_path,
                                                               'secrets.pem')
                    break
            self.write_data_bags(kitchen_path, properties[ChefSolo.DATA_BAGS],
                                 kitchen_path, knife_path,
                                 data_bag_secret=data_bag_secret)
        return data_bag_secret

    def kniferb(self, properties, kitchen_path, knife_path, file_cache_path,
                data_bag_secret=None):
        with self.sftp_connection.open(knife_path, 'w') as knife_rb:
            log_path = os.path.join(kitchen_path, 'chef.log')
            knife_rb_str = ('log_level :info\n'
                            'log_location "%s"\n'
                            'verbose_logging true\n'
                            'ssl_verify_mode :verify_none\n'
                            'file_cache_path "%s"\n'
                            'data_bag_path "%s"\n'
                            'cookbook_path ["%s", "%s"]\n'
                            'environments_path "%s"\n'
                            'role_path "%s"\n'
                            % (log_path,
                               file_cache_path,
                               os.path.join(kitchen_path, ChefSolo.DATA_BAGS),
                               os.path.join(kitchen_path, self.COOKBOOKS),
                               os.path.join(kitchen_path, 'site-cookbooks'),
                               os.path.join(kitchen_path,
                                            ChefSolo.ENVIRONMENTS),
                               os.path.join(kitchen_path, ChefSolo.ROLES)))
            if data_bag_secret is not None:
                knife_rb_str += 'encrypted_data_bag_secret "%s"\n' % (
                    data_bag_secret)
            knife_rb.write(knife_rb_str)

    def create_remote_kitchen(self, properties, kitchen_path, knife_path):
        '''Create the kitchen directory structure on the remote server.'''
        config = {}
        self.create_kitchen_folder(properties, ChefSolo.ROLES, kitchen_path)
        # Only in chef-zero
        self.create_kitchen_folder(properties, ChefSolo.USERS, kitchen_path)
        # Only in chef-zero
        self.create_kitchen_folder(properties, ChefSolo.CLIENTS, kitchen_path)
        self.create_kitchen_folder(properties, ChefSolo.ENVIRONMENTS,
                                   kitchen_path)
        cookbook_path = self.create_remote_folder(kitchen_path,
                                                  name=self.COOKBOOKS)
        self.install_cookbooks(properties, kitchen_path, cookbook_path)
        return config

    @remote_execute
    def clone_kitchen(self, properties, exec_path=None):
        cookbook_path = self.create_remote_folder(exec_path, 'cookbooks')

        script = """%s
        package "git"
        """ % (self._update_package_manager())

        self.run_recipe('install_git', script, exec_path,
                        cookbook_path)
        return dict(script="""
                    git clone %s kitchen
                    cp -r kitchen/* .
                    rm -rf kitchen
                    """
                    % properties[ChefSolo.KITCHEN])
