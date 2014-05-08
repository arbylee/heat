from copy import deepcopy
import json
from netaddr import IPAddress
import re

from heat.common import template_format
from heat.engine import stack_resource
from heat.engine.resources import nova_utils
from heat.engine.resources.loadbalancer import LoadBalancer as AWSLoadBalancer

from .cloud_loadbalancer import CloudLoadBalancer as clb

class LoadBalancer(stack_resource.StackResource):
    properties_schema = deepcopy(AWSLoadBalancer.properties_schema)
    attributes_schema = deepcopy(AWSLoadBalancer.attributes_schema)

    def __init__(self, name, json_snippet, stack):
        super(LoadBalancer, self).__init__(name, json_snippet, stack)

    def instance_ip(self, instance):
        return nova_utils.server_to_ipaddress(self.nova(), instance)

    def ports(self):
        listeners = self.properties['Listeners']
        return set(map(lambda x: x['InstancePort'], listeners))

    def nodes(self):
        listeners = self.properties.get('Listeners', [])
        instances = self.properties.get('Instances', [])
        
        port = next(iter(self.ports()))
        address = lambda x: (self.instance_ip(x) or
                             str(IPAddress(x)))
        node = lambda x: {
            'addresses': [address(x)],
            'port': port,
            'condition': 'ENABLED',
        }

        if instances:
            return [node(instance) for instance in instances]
        return []

    def protocols(self):
        listeners = self.properties['Listeners']
        return set(map(lambda x: x['Protocol'], listeners))

    def lb_ports(self):
        listeners = self.properties['Listeners']
        return set(map(lambda x: x['LoadBalancerPort'], listeners))

    def health_monitor(self):
        healthCheck = self.properties.get('HealthCheck')
        if healthCheck:
            target = healthCheck.get('Target')
            if re.match('^(TCP|SSL)', target):
                return {
                    'type': 'CONNECT',
                    'timeout': healthCheck['Timeout'],
                    'delay': healthCheck['Interval'],
                    'attemptsBeforeDeactivation': healthCheck[
                        'UnhealthyThreashold']
                }

            elif re.match('^HTTP[S]?', target):
                match = re.match('(HTTP[S]?)(:(\d+)(\S+)$)?', target)
                if match:
                    _type, _path = match.group(1), match.group(4)
                else:
                    _type, _path = target, '/'

                return {
                    'type': _type,
                    'timeout': healthCheck['Timeout'],
                    'delay': healthCheck['Interval'],
                    'attemptsBeforeDeactivation': healthCheck[
                        'UnhealthyThreshold'],
                    'bodyRegex': '.*',
                    'path': _path,
                    'statusRegex': '.*',
                    'timeout': healthCheck['Timeout'],
                }

    def handle_create(self):
        """Create a Rackspace CloudLoadbalancer from an ELB resource.
        """
        def no_none(properties):
            return dict((k, v) for k, v in properties.iteritems()
                        if v is not None)

        properties = {
            #cfn HealthCheck
            'healthMonitor': self.health_monitor(),
            #cfn Listeners:Protocol
            'protocol': next(iter(self.protocols())),
            'virtualIps': [{"type": "PUBLIC"}],
            #cfn Instances/Listeners
            'nodes': self.nodes(),
            #cfn Listener:LoadBalancerPort
            'port': next(iter(self.lb_ports()))
        }

        template = {'heat_template_version': '2013-05-23',
                    'resources': {
                        'lb': {
                            'type': 'Rackspace::Cloud::LoadBalancer',
                            'properties': no_none(properties)
                        }
                    }}

        return self.create_with_template(
                template_format.parse(
                    json.dumps(template)
                ), None)

    def handle_delete(self):
        return self.delete_nested()

    def validate(self):
        if not len(self.lb_ports()) == 1:
            raise ValueError("Rackspace CloudLoadBalancer can only listen on a "
                             "single port.")

        protocols = self.protocols()
        if not len(protocols) == 1:
            raise ValueError("Rackspace CloudLoadBalancer can only accept a "
                             "single protocol.")

        allowed_protocols = ['HTTP', 'HTTPS', 'TCP', 'SSL']
        if next(iter(protocols)) not in allowed_protocols:
            raise ValueError("Rackspace CloudLoadBalancer protocol must be in "
                             "%s" % allowed_protocols)

        if not self.instance_ip is not None:
            raise ValueError("A valid node ip must be specified")

        if not len(self.ports()) <= 1:
            raise ValueError("All instance ports must be the same.")


def resource_mapping():
    return {'AWS::ElasticLoadBalancing::LoadBalancer': LoadBalancer}

