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

from heat.tests import utils
from heat.tests.common import HeatTestCase
from .. import client  # noqa


class TestClient(HeatTestCase):

    def setUp(self):
        super(TestClient, self).setUp()
        self.ctx = utils.dummy_context()

    @mock.patch.object(client.heat_clients, 'Clients')
    @mock.patch.object(client, 'barbican_client')
    @mock.patch.object(client, 'auth')
    def test_barbican_passes_in_heat_keystone_client(self, mock_auth,
                                                     mock_barbican_client,
                                                     mock_heat_clients):
        mock_ks = mock.Mock()
        mock_heat_clients.return_value.keystone.return_value.client = mock_ks
        mock_plugin = mock.Mock()
        mock_auth.KeystoneAuthV2.return_value = mock_plugin

        client.Client(self.ctx).barbican()
        mock_auth.KeystoneAuthV2.assert_called_once_with(keystone=mock_ks)
        mock_barbican_client.Client.assert_called_once_with(auth_plugin=
                                                            mock_plugin)
