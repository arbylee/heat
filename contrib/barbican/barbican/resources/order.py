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

from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource

from .. import client  # noqa


class Order(resource.Resource):

    PROPERTIES = (
        NAME, PAYLOAD_CONTENT_TYPE, MODE, EXPIRATION,
        ALGORITHM, BIT_LENGTH,
    ) = (
        'name', 'payload_content_type', 'mode', 'expiration',
        'algorithm', 'bit_length',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Human readable name for the secret.'),
        ),
        PAYLOAD_CONTENT_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('The type/format the secret data is provided in.'),
            default='application/octet-stream',
            constraints=[
                constraints.AllowedValues([
                    'application/octet-stream',
                ]),
            ],
        ),
        EXPIRATION: properties.Schema(
            properties.Schema.STRING,
            _('The expiration date for the secret in ISO-8601 format.'),
        ),
        ALGORITHM: properties.Schema(
            properties.Schema.STRING,
            _('The algorithm type used to generate the secret.'),
            default='aes',
            constraints=[
                constraints.AllowedValues([
                    'aes',
                ]),
            ],
        ),
        BIT_LENGTH: properties.Schema(
            properties.Schema.NUMBER,
            _('The bit-length of the secret.'),
            constraints=[
                constraints.Range(min=1),
            ],
        ),
        MODE: properties.Schema(
            properties.Schema.STRING,
            _('The type/mode of the algorithm associated with the secret '
              'information.'),
            default='cbc',
            constraints=[
                constraints.AllowedValues([
                    'cbc',
                ]),
            ],
        ),
    }

    attributes_schema = {
        'status': _('The status of the order'),
        'order_ref': _('The URI to the order'),
        'secret_ref': _('The URI to the created secret'),
    }

    def __init__(self, name, json_snippet, stack):
        super(Order, self).__init__(name, json_snippet, stack)
        self.client = client.Client(self.context)

    def handle_create(self):
        info = dict(
            (prop, self.properties.get(prop))
            for prop in self.PROPERTIES
        )
        order_ref = self.client.barbican().orders.create(**info)
        self.resource_id_set(order_ref)
        return order_ref

    def check_create_complete(self, order_href):
        order = self.client.barbican().orders.get(order_href)
        return order.status == 'ACTIVE'

    def handle_delete(self):
        if not self.resource_id:
            return

        try:
            self.client.barbican().orders.delete(self.resource_id)
            self.resource_id_set(None)
        except client.barbican_client.HTTPClientError as exc:
            # This is the only exception the client raises
            # Inspecting the message to see if it's a 'Not Found'
            if 'Not Found' in str(exc):
                self.resource_id_set(None)
            else:
                raise

    def _resolve_attribute(self, name):
        order = self.client.barbican().orders.get(self.resource_id)
        if name == 'order_ref':
            return order.order_ref
        if name == 'secret_ref':
            return order.secret_ref


def resource_mapping():
    return {
        'OS::Barbican::Order': Order,
    }


def available_resource_mapping():
    if not client.barbican_client:
        return {}

    return resource_mapping()
