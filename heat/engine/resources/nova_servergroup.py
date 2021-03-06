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

from novaclient import exceptions as nova_exceptions

from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.openstack.common.gettextutils import _


class ServerGroup(resource.Resource):
    """
    A resource for managing a Nova server group.
    """

    PROPERTIES = (
        NAME, POLICIES
    ) = (
        'name', 'policies'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Server Group name.')
        ),
        POLICIES: properties.Schema(
            properties.Schema.LIST,
            _('A list of string policies to apply.'
              'Defaults to anti-affinity.'),
            default=['anti-affinity'],
            constraints=[
                constraints.AllowedValues(["anti-affinity", "affinity"])
            ],
            schema=properties.Schema(
                properties.Schema.STRING,
            )
        ),
    }

    def handle_create(self):
        name = self.physical_resource_name()
        policies = self.properties[self.POLICIES]
        server_group = self.nova().server_groups.create(name=name,
                                                        policies=policies)
        self.resource_id_set(server_group.id)

    def handle_delete(self):
        if self.resource_id:
            try:
                self.nova().server_groups.delete(self.resource_id)
            except nova_exceptions.NotFound:
                pass
            self.resource_id_set(None)

    def physical_resource_name(self):
        name = self.properties.get(self.NAME)
        if name:
            return name
        return super(ServerGroup, self).physical_resource_name()


def resource_mapping():
    return {'OS::Nova::ServerGroup': ServerGroup}
