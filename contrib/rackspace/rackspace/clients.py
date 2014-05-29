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

"""Client Libraries for Rackspace Resources."""

import urlparse

from oslo.config import cfg

from heat.common import exception
from heat.engine import clients
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

from glanceclient import client as glanceclient

LOG = logging.getLogger(__name__)

try:
    import pyrax
except ImportError:
    LOG.info(_('pyrax not available'))

cloud_opts = [
    cfg.StrOpt('region_name',
               help=_('Region for connecting to services.'))
]
cfg.CONF.register_opts(cloud_opts)


class Clients(clients.OpenStackClients):

    """Convenience class to create and cache client instances."""

    def __init__(self, context):
        super(Clients, self).__init__(context)
        self.pyrax = None
        self._networks = None
        self._dns = None
        self._autoscale = None
        self._lb = None

    def _get_client(self, name):
        if not self.pyrax:
            self.__authenticate()
        # try and get an end point internal to the DC for faster communication
        try:
            return self.pyrax.get_client(name, cfg.CONF.region_name,
                                         public=False)
        # otherwise use the default public one
        except (pyrax.exceptions.NoEndpointForService,
                pyrax.exceptions.NoSuchClient):
            LOG.warn(_("Could not find private client for %s. "
                       "Trying public client."), name)
            return self.pyrax.get_client(name, cfg.CONF.region_name)

    def auto_scale(self):
        """Rackspace Auto Scale client."""
        if not self._autoscale:
            self._autoscale = self._get_client("autoscale")
        return self._autoscale

    def cloud_lb(self):
        """Rackspace cloud loadbalancer client."""
        if not self._lb:
            self._lb = self._get_client("load_balancer")
        return self._lb

    def cloud_dns(self):
        """Rackspace cloud dns client."""
        if not self._dns:
            self._dns = self._get_client("dns")
        return self._dns

    def nova(self, service_type="compute"):
        """Rackspace cloudservers client.

        Specifying the service type is to
        maintain compatibility with clients.OpenStackClients. It is not
        actually a valid option to change within pyrax.
        """
        if not self._nova:
            self._nova = self._get_client("compute")
        return self._nova

    def cloud_networks(self):
        """Rackspace cloud networks client."""
        if not self._networks:
            if not self.pyrax:
                self.__authenticate()
            # need special handling now since the contextual
            # pyrax doesn't handle "networks" not being in
            # the catalog
            ep = pyrax._get_service_endpoint(self.pyrax, "compute",
                                             region=cfg.CONF.region_name)
            cls = pyrax._client_classes['compute:network']
            self._networks = cls(self.pyrax,
                                 region_name=cfg.CONF.region_name,
                                 management_url=ep)
        return self._networks

    def trove(self):
        """Rackspace trove client."""
        if not self._trove:
            super(Clients, self).trove(service_type='rax:database')
            management_url = self.url_for(service_type='rax:database',
                                          region_name=cfg.CONF.region_name)
            self._trove.client.management_url = management_url
        return self._trove

    def cinder(self):
        """Override the region for the cinder client."""
        if not self._cinder:
            super(Clients, self).cinder()
            management_url = self.url_for(service_type='volume',
                                          region_name=cfg.CONF.region_name)
            self._cinder.client.management_url = management_url
        return self._cinder

    def swift(self):
        # Rackspace doesn't include object-store in the default catalog
        # for "reasons". The pyrax client takes care of this, but it
        # returns a wrapper over the upstream python-swiftclient so we
        # unwrap here and things just work
        if not self._swift:
            self._swift = self._get_client("object_store").connection
        return self._swift

    def glance(self):
        if not self._glance:
            con = self.context
            endpoint_type = self._get_client_option('glance', 'endpoint_type')
            endpoint = self.url_for(service_type='image',
                                    endpoint_type=endpoint_type,
                                    region_name=cfg.CONF.region_name)
            # Rackspace service catalog includes a tenant scoped glance
            # endpoint so we have to munge the url a bit
            glance_url = urlparse.urlparse(endpoint)
            # remove the tenant and following from the url
            endpoint = "%s://%s" % (glance_url.scheme, glance_url.hostname)
            args = {
                'auth_url': con.auth_url,
                'service_type': 'image',
                'project_id': con.tenant,
                'token': self.auth_token,
                'endpoint_type': endpoint_type,
                'ca_file': self._get_client_option('glance', 'ca_file'),
                'cert_file': self._get_client_option('glance', 'cert_file'),
                'key_file': self._get_client_option('glance', 'key_file'),
                'insecure': self._get_client_option('glance', 'insecure')
            }

            self._glance = glanceclient.Client('2', endpoint, **args)
        return self._glance

    def __authenticate(self):
        """Create an authenticated client context."""
        self.pyrax = pyrax.create_context("rackspace")
        self.pyrax.auth_endpoint = self.context.auth_url
        LOG.info(_("Authenticating username: %s") %
                 self.context.username)
        tenant = self.context.tenant_id
        tenant_name = self.context.tenant
        self.pyrax.auth_with_token(self.context.auth_token,
                                   tenant_id=tenant,
                                   tenant_name=tenant_name)
        if not self.pyrax.authenticated:
            LOG.warn(_("Pyrax Authentication Failed."))
            raise exception.AuthorizationFailure()
        LOG.info(_("User %s authenticated successfully."),
                 self.context.username)
