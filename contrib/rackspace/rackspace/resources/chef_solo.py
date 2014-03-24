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

import os
import uuid

from oslo.config import cfg

from heat.engine import properties
from heat.engine import resource
from heat.engine import scheduler

from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging
from heat.openstack.common.versionutils import deprecated

import chef_scripts  # noqa

logger = logging.getLogger(__name__)

chef_ops = [
    cfg.StrOpt('chef_solo_path',
               default="/tmp/heat_chef",
               help=_('Path to cache chef solo kitchens.')),
]
cfg.CONF.register_opts(chef_ops)


class ChefSolo(resource.Resource):

    PROPERTIES = (
        BERKSFILE, BERKSFILE_LOCK, CHEFFILE, USERNAME, HOST, PRIVATE_KEY,
        DATA_BAGS, NODE, ROLES, USERS, ENVIRONMENTS, CLIENTS, CHEF_VERSION,
        KITCHEN
    ) = (
        'Berksfile', 'Berksfile.lock', 'Cheffile', 'username', 'host',
        'private_key', 'data_bags', 'node', 'roles', 'users', 'environments',
        'clients', 'chef_version', 'kitchen'
    )

    properties_schema = {
        BERKSFILE_LOCK: properties.Schema(
            properties.Schema.STRING,
            _('The Berksfile.lock to use with berkshelf to specify cookbook '
              'versions for the chef run.')
        ),
        BERKSFILE: properties.Schema(
            properties.Schema.STRING,
            _('The Berksfile to use with berkshelf todownload cookbooks on the'
              ' host for the chef run.')
        ),
        CHEFFILE: properties.Schema(
            properties.Schema.STRING,
            _('The Cheffile to use with librarian-chef to download cookbooks '
              'on the host for the chef run.')
        ),
        KITCHEN: properties.Schema(
            properties.Schema.STRING,
            _('A git url to the kitchen to clone. This can be used in place of'
              ' a (Berks|Chef)file to install cookbooks on the host.'),
        ),
        USERNAME: properties.Schema(
            properties.Schema.STRING,
            _('The username to connect to the host with.'),
            default="root",
            required=True
        ),
        HOST: properties.Schema(
            properties.Schema.STRING,
            _('The host to run chef-solo on.'),
            required=True
        ),
        PRIVATE_KEY: properties.Schema(
            properties.Schema.STRING,
            _('The ssh key to connect to the host with.'),
            required=True
        ),
        DATA_BAGS: properties.Schema(
            properties.Schema.MAP,
            _('Data_bags to write to the kitchen during the chef run.'),
        ),
        NODE: properties.Schema(
            properties.Schema.MAP,
            _('The node file for the chef run. May have a run_list, '
              'attributes, etc.'),
        ),
        ROLES: properties.Schema(
            properties.Schema.MAP,
            _('Roles to be written to the kitchen for the chef run.'),
        ),
        USERS: properties.Schema(
            properties.Schema.MAP,
            _('Users to be written to the kitchen for the chef run.'),
        ),
        ENVIRONMENTS: properties.Schema(
            properties.Schema.MAP,
            _('Environments to be written to the kitchen for the chef run.'),
        ),
        CLIENTS: properties.Schema(
            properties.Schema.MAP,
            _('Clients to be written to the kitchen for the chef run.'),
        ),
        CHEF_VERSION: properties.Schema(
            properties.Schema.STRING,
            _('The version of chef to install on the host.'),
        )
    }

    def __init__(self, name, json_snippet, stack):
        super(ChefSolo, self).__init__(name, json_snippet, stack)

    def handle_create(self):
        script = chef_scripts.ChefScripts(username=
                                          self.properties[self.USERNAME],
                                          host=self.properties[self.HOST],
                                          private_key=
                                          self.properties[self.PRIVATE_KEY])
        self.resource_id_set(str(uuid.uuid4()))

        def _dependent_tasks():

            remote_path = script.create_remote_folder(cfg.CONF.chef_solo_path)
            kitchen_path = script.create_remote_folder(remote_path,
                                                       name=self.resource_id)
            script.bootstrap(version=self.properties[self.CHEF_VERSION],
                             exec_path=kitchen_path)
            yield
            knife_path = os.path.join(kitchen_path, 'knife.rb')
            if self.properties[self.KITCHEN] is not None:
                script.clone_kitchen(self.properties, exec_path=kitchen_path)
            else:
                script.create_remote_kitchen(self.properties,
                                             kitchen_path, knife_path)
            yield
            data_bag_secret = script.databags(self.properties, kitchen_path,
                                              knife_path)
            script.kniferb(self.properties, kitchen_path, knife_path,
                           remote_path, data_bag_secret=data_bag_secret)
            node_folder = script.create_remote_folder(kitchen_path,
                                                      name="nodes")
            node_file_name = self.properties[self.HOST] + ".json"
            node_path = script.write_remote_json(node_folder,
                                                 node_file_name,
                                                 self.properties[self.NODE])
            yield
            script.run_chef(knife_path, node_path, exec_path=kitchen_path)
            script.sftp_connection.close()

        return scheduler.TaskRunner(_dependent_tasks)

    def check_create_complete(self, tasks):
        if not tasks.started():
            tasks.start()
            return tasks.done()
        return tasks.step()


def approved_mapping():
    return ('Rackspace::Cloud::ChefSolo', ChefSolo)


@deprecated(as_of=deprecated.ICEHOUSE, in_favor_of=str(approved_mapping()))
def deprecated_mapping():
    return ('OS::Heat::ChefSolo', ChefSolo)


def resource_mapping():
    approved = approved_mapping()
    deprecated = deprecated_mapping()
    return {
        approved[0]: approved[1],
        deprecated[0]: deprecated[1]
    }
