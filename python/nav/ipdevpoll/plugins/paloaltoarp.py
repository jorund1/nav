#
# Copyright (C) 2023, 2024 University of Tromsø
# Copyright (C) 2024 Sikt
#
# This file is part of Network Administration Visualized (NAV).
#
# NAV is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License version 3 as published by the Free
# Software Foundation.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.  You should have received a copy of the GNU General Public
# License along with NAV. If not, see <http://www.gnu.org/licenses/>.
#

"""
ipdevpoll plugin for fetching arp mappings from Palo Alto firewalls

Configure a netbox to work with this plugin by assigning it a
HTTP_REST_API management profile with service set to "Palo Alto ARP"
in seedDB.
"""

import xml.etree.ElementTree as ET

from IPy import IP
from nav.models.manage import Netbox, ManagementProfile, NetboxProfile
from twisted.internet import defer, reactor, ssl
from twisted.internet.defer import returnValue
from twisted.web import client
from twisted.web.client import Agent
from twisted.web.http_headers import Headers

from nav import buildconf
from nav.ipdevpoll.plugins.arp import Arp


class PaloaltoArp(Arp):
    @classmethod
    @defer.inlineCallbacks
    def can_handle(cls, netbox):
        """Return True if this plugin can handle the given netbox."""
        has_configurations = yield cls._has_paloalto_configurations(netbox)
        returnValue(has_configurations)

    @defer.inlineCallbacks
    def handle(self):
        """Handle plugin business, return a deferred."""
        self._logger.debug("Collecting IP/MAC mappings for Paloalto device")

        configurations = yield self._get_paloalto_configurations(self.netbox)
        all_mappings = []
        for configuration in configurations:
            mappings = yield self._fetch_paloalto_arp_mappings(self.netbox.ip, api_keys)
            mappings and all_mappings.extend(mappings)

        yield self._process_data(mappings)

    @defer.inlineCallbacks
    def _fetch_paloalto_arp_mappings(self, ip: IP, api_keys: list[str]):
        """
        Make a HTTP request to get ARP mappings from Paloalto device

        The Paloalto device is expected to give the same result for two correct but different keys in api_keys.
        Hence, a request to the Paloalto device is made for each api key only until a successful response from the device.
        """
        arptable = yield self._do_request(ip, api_key)
        mappings = parse_arp(arptable) if arptable is not None else None
        returnValue(mappings)

    @classmethod
    @defer.inlineCallbacks
    def _has_paloalto_configurations(cls, netbox: Netbox):
        """
        Make a database request to check if the netbox has any
        management profile that configures access to Palo Alto ARP data via HTTP
        """
        query = NetboxProfile.objects.filter(
            netbox_id=netbox.id,
            profile__protocol=ManagementProfile.PROTOCOL_HTTP_REST,
            profile__configuration__contains={"service": "Palo Alto ARP"},
        )
        response = yield run_in_thread(query.exists)
        returnValue(response)

    @classmethod
    @defer.inlineCallbacks
    def _get_paloalto_configurations(cls, netbox: Netbox):
        """
        Make a database request that fetches all management profiles of
        the netbox that configures access to Palo Alto ARP data via HTTP
        """
        query = NetboxProfile.objects.filter(
            netbox_id=netbox.id,
            profile__protocol=ManagementProfile.PROTOCOL_HTTP_REST,
            profile__configuration__contains={"service": "Palo Alto ARP"},
        ).values_list("profile__configuration", flat=True)
        response = yield run_in_thread(list, query)
        returnValue(response)

    @defer.inlineCallbacks
    def _do_request(self, address: IP, key: str):
        """
        Make a HTTP request to Paloalto device
        """
        class SslPolicy(client.BrowserLikePolicyForHTTPS):
            def creatorForNetloc(self, hostname, port):
                return ssl.CertificateOptions(verify=False)

        url = f"https://{address}/api/?type=op&cmd=<show><arp><entry+name+=+'all'/></arp></show>&key={key}"
        self._logger.debug("making request: %s", url)

        agent = Agent(reactor, contextFactory=SslPolicy())

        try:
            response = yield agent.request(
                b'GET',
                url.encode('utf-8'),
                Headers(
                    {'User-Agent': [f'NAV/PaloaltoArp; version {buildconf.VERSION}']}
                ),
                None,
            )
        except Exception:  # noqa
            self._logger.exception(
                "Error when talking to PaloAlto API. "
                "Make sure the device is reachable and the API key is correct."
            )
            returnValue(None)

        response = yield client.readBody(response)
        returnValue(response)


def parse_arp(arpbytes: bytes) -> list[tuple[str, IP, str]]:
    """
    Create mappings from arp table
    xml.etree.ElementTree is considered insecure: https://docs.python.org/3/library/xml.html#xml-vulnerabilities
    However, since we are not parsing untrusted data, this should not be a problem.
    """
    arps = []

    root = ET.fromstring(arpbytes.decode("utf-8"))
    entries = root.find("result").find("entries")
    for entry in entries:
        status = entry.find("status").text
        ip = entry.find("ip").text
        mac = entry.find("mac").text
        if status.strip() != "i":
            if mac != "(incomplete)":
                arps.append(('ifindex', IP(ip), mac))

    return arps
