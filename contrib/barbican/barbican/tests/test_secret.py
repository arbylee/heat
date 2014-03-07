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

import mock

from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine import scheduler
from heat.tests import utils
from heat.tests.common import HeatTestCase

from ..resources import secret  # noqa


stack_template = '''
heat_template_version: 2013-05-23
description: Test template
resources:
  secret:
    type: OS::Barbican::Secret
    properties: {}
'''


@mock.patch.object(secret.client, 'Client')
class TestSecret(HeatTestCase):

    def setUp(self):
        super(TestSecret, self).setUp()
        utils.setup_dummy_db()
        self.ctx = utils.dummy_context()
        self.template = template_format.parse(stack_template)
        self.stack = utils.parse_stack(self.template)

        self.props = {
            'name': 'foobar-secret',
            'payload': 'foobar',
        }
        self.res_template = self.template['Resources']['Secret']
        self.res_template['Properties'] = self.props

        self._register_resources()

    def _register_resources(self):
        for res_name, res_class in secret.resource_mapping().iteritems():
            resource._register_class(res_name, res_class)

    def test_create_secret(self, mock_client):
        barbican = mock_client.return_value.barbican.return_value
        resource = secret.Secret('secret', self.res_template, self.stack)
        scheduler.TaskRunner(resource.create)()

        expected_state = (resource.CREATE, resource.COMPLETE)
        self.assertEqual(expected_state, resource.state)
        args = barbican.secrets.store.call_args[1]
        self.assertEqual('foobar', args['payload'])
        self.assertEqual('foobar-secret', args['name'])

    def test_attributes(self, mock_client):
        mock_secret = mock.Mock()
        mock_secret.status = 'test-status'
        mock_secret.secret_ref = 'test-secret-ref'

        mock_barbican = mock_client.return_value.barbican
        mock_barbican.return_value.secrets.get.return_value = mock_secret
        resource = secret.Secret('secret', self.res_template, self.stack)

        self.assertEqual('test-status', resource.FnGetAtt('status'))
        self.assertEqual('test-secret-ref', resource.FnGetAtt('secret_ref'))

    def test_decrypted_payload_attribute(self, mock_client):
        mock_barbican = mock_client.return_value.barbican
        mock_barbican.return_value.secrets.decrypt.return_value = 'foo'
        resource = secret.Secret('secret', self.res_template, self.stack)

        self.assertEqual('foo', resource.FnGetAtt('decrypted_payload'))

    def test_create_secret_sets_resource_id(self, mock_client):
        barbican = mock_client.return_value.barbican.return_value
        barbican.secrets.store.return_value = 'foo'
        resource = secret.Secret('secret', self.res_template, self.stack)
        scheduler.TaskRunner(resource.create)()

        self.assertEqual('foo', resource.resource_id)

    def test_create_secret_with_plain_text(self, mock_client):
        barbican = mock_client.return_value.barbican.return_value
        content_type = 'text/plain'
        self.props['payload_content_type'] = content_type
        resource = secret.Secret('secret', self.res_template, self.stack)
        scheduler.TaskRunner(resource.create)()

        args = barbican.secrets.store.call_args[1]
        self.assertEqual(content_type, args[resource.PAYLOAD_CONTENT_TYPE])

    def test_create_secret_with_octet_stream(self, mock_client):
        barbican = mock_client.return_value.barbican.return_value
        content_type = 'application/octet-stream'
        self.props['payload_content_type'] = content_type
        resource = secret.Secret('secret', self.res_template, self.stack)
        scheduler.TaskRunner(resource.create)()

        args = barbican.secrets.store.call_args[1]
        self.assertEqual(content_type, args[resource.PAYLOAD_CONTENT_TYPE])

    def test_create_secret_other_content_types_not_allowed(self, mock_client):
        self.props['payload_content_type'] = 'not/allowed'
        resource = secret.Secret('secret', self.res_template, self.stack)

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(resource.create))

    def test_delete_secret(self, mock_client):
        barbican = mock_client.return_value.barbican.return_value
        barbican.secrets.store.return_value = 'foo'
        resource = secret.Secret('secret', self.res_template, self.stack)
        scheduler.TaskRunner(resource.create)()

        self.assertEqual('foo', resource.resource_id)

        mock_delete = barbican.secrets.delete
        scheduler.TaskRunner(resource.delete)()

        self.assertIsNone(resource.resource_id)
        mock_delete.assert_called_once_with('foo')

    @mock.patch.object(secret.client, 'barbican_client', new=mock.Mock())
    def test_handle_delete_ignores_not_found_errors(self, mock_client):
        barbican = mock_client.return_value.barbican.return_value
        resource = secret.Secret('secret', self.res_template, self.stack)
        scheduler.TaskRunner(resource.create)()

        secret.client.barbican_client.HTTPClientError = Exception
        exc = secret.client.barbican_client.HTTPClientError('Not Found. Nope.')
        barbican.secrets.delete.side_effect = exc
        scheduler.TaskRunner(resource.delete)()
        self.assertTrue(barbican.secrets.delete.called)

    @mock.patch.object(secret.client, 'barbican_client', new=mock.Mock())
    def test_handle_delete_raises_resource_failure_on_error(self, mock_client):
        barbican = mock_client.return_value.barbican.return_value
        resource = secret.Secret('secret', self.res_template, self.stack)
        scheduler.TaskRunner(resource.create)()

        secret.client.barbican_client.HTTPClientError = Exception
        exc = secret.client.barbican_client.HTTPClientError('Boom.')
        barbican.secrets.delete.side_effect = exc
        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(resource.delete))
        self.assertIn('Boom.', str(exc))
