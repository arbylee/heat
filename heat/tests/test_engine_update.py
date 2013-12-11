# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from heat.engine import parser
from heat.engine import scheduler
from heat.engine import update

from heat.tests.common import HeatTestCase
from heat.tests import generic_resource
from heat.tests import utils


class StackUpdateTest(HeatTestCase):
    def setUp(self):
        super(StackUpdateTest, self).setUp()
        utils.setup_dummy_db()
        self.context = utils.dummy_context()
        template = parser.Template({})
        self.existing_stack = parser.Stack(self.context, 'stack1', template)
        self.new_stack = self.previous_stack = parser.Stack(
            self.context, 'stack2', template)
        self.r1 = generic_resource.GenericResource('r1',
                                                   {'Type': 'Foo'},
                                                   self.new_stack)
        self.existing_stack._resources = {}
        self.new_stack._resources = {'r1': self.r1}
        self.stack_update = update.StackUpdate(self.existing_stack,
                                               self.new_stack,
                                               self.previous_stack,
                                               update_type='check')

    def test_call_raises_resource_failure_exception(self):
        exc = Exception('foo')
        self.r1.handle_check = mock.Mock(side_effect=exc)

        runner = scheduler.TaskRunner(self.stack_update)
        self.assertRaises(exception.ResourceFailure, runner)

    def test_aggregate_exceptions(self):
        self.stack_update.update_type = 'foobar'
        self.assertFalse(self.stack_update.aggregate_exceptions)

        self.stack_update.update_type = update.rpc_api.UPDATE_CHECK
        self.assertTrue(self.stack_update.aggregate_exceptions)

    @mock.patch.object(scheduler, 'DependencyTaskGroup')
    def test_check_makes_call_aggregate_exceptions(self, mock_dependency):
        def _call():
            pass
        mock_dependency.return_value = _call
        scheduler.TaskRunner(self.stack_update)()

        kwargs = mock_dependency.call_args[1]
        self.assertTrue(kwargs['aggregate_exceptions'])

    def test_check_resource_doesnt_check_if_not_same_resource(self):
        self.r1.handle_check = mock.Mock()
        self.existing_stack._resources = {'r1': 'some'}
        scheduler.TaskRunner(self.stack_update._check_resource, self.r1)()
        self.assertFalse(self.r1.handle_check.called)

    def test_check_resource_only_checks_if_same_resource(self):
        def generator():
            yield
        self.r1.check = mock.Mock(return_value=generator())
        self.existing_stack._resources = {'r1': self.r1}
        scheduler.TaskRunner(self.stack_update._check_resource, self.r1)()
        self.assertTrue(self.r1.check.called)
