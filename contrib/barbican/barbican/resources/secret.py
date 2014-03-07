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


class Secret(resource.Resource):

    PROPERTIES = (
        NAME, PAYLOAD, PAYLOAD_CONTENT_TYPE, PAYLOAD_CONTENT_ENCODING,
        MODE, EXPIRATION, ALGORITHM, BIT_LENGTH,
    ) = (
        'name', 'payload', 'payload_content_type', 'payload_content_encoding',
        'mode', 'expiration', 'algorithm', 'bit_length',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Human readable name for the secret.'),
        ),
        PAYLOAD: properties.Schema(
            properties.Schema.STRING,
            _('The unencrypted plain text of the secret.'),
        ),
        PAYLOAD_CONTENT_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('The type/format the secret data is provided in.'),
            constraints=[
                constraints.AllowedValues([
                    'text/plain',
                    'application/octet-stream',
                ]),
            ],
        ),
        PAYLOAD_CONTENT_ENCODING: properties.Schema(
            properties.Schema.STRING,
            _('The encoding format used to provide the payload data.'),
            constraints=[
                constraints.AllowedValues([
                    'base64',
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
        ),
        BIT_LENGTH: properties.Schema(
            properties.Schema.NUMBER,
            _('The bit-length of the secret.'),
            constraints=[
                constraints.Range(
                    min=0,
                ),
            ],
        ),
        MODE: properties.Schema(
            properties.Schema.STRING,
            _('The type/mode of the algorithm associated with the secret '
              'information.'),
        ),
    }

    attributes_schema = {
        'status': _('The status of the secret'),
        'secret_ref': _('The URI to the secret'),
        'decrypted_payload': _('The decrypted secret payload.'),
    }

    def __init__(self, name, json_snippet, stack):
        super(Secret, self).__init__(name, json_snippet, stack)
        self.client = client.Client(self.context)

    def handle_create(self):
        info = dict(
            (prop, self.properties.get(prop))
            for prop in self.PROPERTIES
        )
        secret_ref = self.client.barbican().secrets.store(**info)
        self.resource_id_set(secret_ref)
        return secret_ref

    def handle_delete(self):
        if not self.resource_id:
            return

        try:
            self.client.barbican().secrets.delete(self.resource_id)
            self.resource_id_set(None)
        except client.barbican_client.HTTPClientError as exc:
            # This is the only exception the client raises
            # Inspecting the message to see if it's a 'Not Found'
            if 'Not Found' in str(exc):
                self.resource_id_set(None)
            else:
                raise

    def _resolve_attribute(self, name):
        if name == 'decrypted_payload':
            return self.client.barbican().secrets.decrypt(self.resource_id)

        secret = self.client.barbican().secrets.get(self.resource_id)
        if name == 'status':
            return secret.status
        if name == 'secret_ref':
            return secret.secret_ref


def resource_mapping():
    return {
        'OS::Barbican::Secret': Secret,
    }


def available_resource_mapping():
    if not client.barbican_client:
        return {}

    return resource_mapping()
