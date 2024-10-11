from unittest.mock import Mock

import pytest
from django.urls import reverse
from nav.models.manage import ManagementProfile
from nav.ipdevpoll import shadows
from nav.ipdevpoll.plugins.paloaltoarp import PaloaltoArp
from nav.ipdevpoll.storage import ContainerRepository
from twisted.internet.defer import returnValue, inlineCallbacks

mock_data = b'''
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

@pytest.fixture
def paloalto_netbox(localhost, management_profile, db):
    netbox_url = reverse("seeddb-netbox-edit", args=(localhost.id,))
    management_profile_url = reverse(
        "seeddb-management-profile-edit", args=(management_profile.id,)
    )

    # Manually sending this post request helps reveal regression bugs in case HTTPRestForm.service.choices keys are altered
    # since the post's invalid service field should then cause the form cleaning stage to fail. Changing the HTTPRestForm.choice
    # map to use enums as keys instead of strings would enable static analysis to reveal this.
    client.post(
        management_profile_url,
        follow=True,
        data={
            "name": management_profile.name,
            "description": management_profile.description,
            "protocol": ManagementProfile.PROTOCOL_HTTP_REST,
            "service": "Palo Alto ARP",
            "api_key": "1234",
        }
    )

    client.post(
        netbox_url,
        follow=True,
        data={
            "ip": localhost.ip,
            "room": localhost.room_id,
            "category": localhost.category_id,
            "organization": localhost.organization_id,
            "profiles": [management_profile.id],
        },
    )
    return localhost


@inlineCallbacks
def _do_request_mock(address, key, *args, **kwargs):
    if key == "1234":
        returnValue(mock_data)
    returnValue(None)


@inlineCallbacks
def test_netbox_with_paloalto_management_profile_should_get_arp_mappings(
        paloalto_netbox, client, monkeypatch
):
    assert PaloAltoArp.can_handle(paloalto_netbox)


    monkeypatch.setattr(
        nav.ipdevpoll.plugins.paloaltoarp.PaloaltoArp, "_do_request", _do_request_mock
    )

    plugin = PaloaltoArp(netbox=paloalto_netbox, agent=Mock(), containers=ContainerRepository())

    actual = [
        (arp.ip, arp.mac)
        for arp
        in plugin.containers[shadow.Arp].values()
    ]
    expected = []
    assert sorted(actual) == sorted(expected)

    yield plugin.handle()

    actual = [
        (arp.ip, arp.mac)
        for arp
        in plugin.containers[shadow.Arp].values()
    ]
    expected = [
        (IP('192.168.0.1'), '00:00:00:00:00:01'),
        (IP('192.168.0.2'), '00:00:00:00:00:02'),
        (IP('192.168.0.3'), '00:00:00:00:00:03'),
    ]
    assert sorted(actual) == sorted(expected)
