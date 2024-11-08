from unittest.mock import Mock

import pytest
import pytest_twisted
from twisted.internet import defer

from nav.models.manage import ManagementProfile, Netbox, NetboxProfile
from nav.ipdevpoll.jobs import JobHandler
from nav.ipdevpoll.plugins.paloaltoarp import PaloaltoArp
from nav.ipdevpoll.plugins import plugin_registry


@pytest.mark.twisted
@pytest_twisted.inlineCallbacks
def test_netbox_with_paloalto_management_profile_with_valid_api_key_should_get_arp_mappings(
    paloalto_netbox_1234, monkeypatch
):
    can_handle = yield PaloaltoArp.can_handle(paloalto_netbox_1234)
    assert can_handle

    # Set up a single ipdevpoll job for this netbox:
    # Assure PaloAltoArp is a known ipdevpoll plugin
    plugin_registry['paloaltoarp'] = PaloaltoArp
    job = JobHandler('paloaltoarp', paloalto_netbox_1234.pk, plugins=['paloaltoarp'])
    # Disable implicit SNMP requests done during job.run()
    job._create_agentproxy = Mock()
    job._destroy_agentproxy = Mock()

    monkeypatch.setattr(PaloaltoArp, "_do_request", _only_accept_1234)

    assert paloalto_netbox_1234.arp_set.count() == 0

    yield job.run()

    actual = [(arp.ip, arp.mac) for arp in paloalto_netbox_1234.arp_set.all()]
    expected = [
        ('192.168.0.1', '00:00:00:00:00:01'),
        ('192.168.0.2', '00:00:00:00:00:02'),
        ('192.168.0.3', '00:00:00:00:00:03'),
    ]
    assert sorted(actual) == sorted(expected)


@pytest.mark.twisted
@pytest_twisted.inlineCallbacks
def test_netbox_with_paloalto_management_profile_with_invalid_api_key_should_not_get_arp_mappings(
    paloalto_netbox_1234, monkeypatch
):
    can_handle = yield PaloaltoArp.can_handle(paloalto_netbox_1234)
    assert can_handle

    plugin_registry['paloaltoarp'] = PaloaltoArp
    job = JobHandler('paloaltoarp', paloalto_netbox_1234.pk, plugins=['paloaltoarp'])
    job._create_agentproxy = Mock()
    job._destroy_agentproxy = Mock()

    monkeypatch.setattr(PaloaltoArp, "_do_request", _only_accept_5678)

    assert paloalto_netbox_1234.arp_set.count() == 0
    yield job.run()
    assert paloalto_netbox_1234.arp_set.count() == 0


valid_http_response_body = b'''
    <response status="success">
    <result>
            <max>132000</max>
            <total>3</total>
            <timeout>1800</timeout>
            <dp>s3dp1</dp>
            <entries>
                <entry>
                    <status>  s  </status>
                    <ip>192.168.0.1</ip>
                    <mac>00:00:00:00:00:01</mac>
                    <ttl>100</ttl>
                    <interface>ae2</interface>
                    <port>ae2</port>
                </entry>
                <entry>
                    <status>  e  </status>
                    <ip>192.168.0.2</ip>
                    <mac>00:00:00:00:00:02</mac>
                    <ttl>200</ttl>
                    <interface>ae2</interface>
                    <port>ae2</port>
                </entry>
                <entry>
                    <status>  c  </status>
                    <ip>192.168.0.3</ip>
                    <mac>00:00:00:00:00:03</mac>
                    <ttl>300</ttl>
                    <interface>ae3.61</interface>
                    <port>ae3</port>
                </entry>
                <entry>
                    <status>  i  </status>
                    <ip>192.168.0.4</ip>
                    <mac>00:00:00:00:00:04</mac>
                    <ttl>400</ttl>
                    <interface>ae3.61</interface>
                    <port>ae3</port>
                </entry>
            </entries>
        </result>
    </response>
    '''


@pytest.fixture(scope="function")
def paloalto_netbox_1234():
    netbox = Netbox(
        ip='127.0.0.1',
        sysname='localhost.example.org',
        organization_id='myorg',
        room_id='myroom',
        category_id='SRV',
    )
    netbox.save()

    profile = ManagementProfile(
        name="PaloAlto Test Management Profile",
        protocol=ManagementProfile.PROTOCOL_HTTP_API,
        configuration={
            "api_key": "1234",
            "service": "Palo Alto ARP",
        },
    )
    profile.save()
    NetboxProfile(netbox=netbox, profile=profile).save()

    yield netbox
    netbox.delete()
    profile.delete()


@classmethod
def _only_accept_1234(cls, address, key, *args, **kwargs):
    """Mimic PaloaltoArp._do_request() but only succeed if supplied key is '1234'"""
    if key == "1234":
        return defer.succeed(valid_http_response_body)
    return defer.succeed(None)


@classmethod
def _only_accept_5678(cls, address, key, *args, **kwargs):
    """Mimic PaloaltoArp._do_request() but only succeed if supplied key is '5678'"""
    if key == "5678":
        return defer.succeed(valid_http_response_body)
    return defer.succeed(None)
