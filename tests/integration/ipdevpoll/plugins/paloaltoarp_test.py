from unittest.mock import Mock

from django.urls import reverse
import pytest
import pytest_twisted
from twisted.internet import defer

from nav.models.manage import ManagementProfile, Netbox, NetboxProfile
from nav.ipdevpoll.jobs import JobHandler
from nav.ipdevpoll.plugins.paloaltoarp import PaloaltoArp
from nav.ipdevpoll.plugins import plugin_registry


class TestCanHandleNetbox:
    """
    Check that the PaloaltoArp plugin signifies it can handle netboxes with at
    least one management profile containing a paloalto configuration.
    """

    @pytest.mark.parametrize(
        "netbox",
        ["paloalto_netbox_1234", "paloalto_netbox_5678"],
    )
    @pytest.mark.twisted
    @pytest_twisted.inlineCallbacks
    def test_it_should_accept_netbox_having_some_paloalto_http_api_management_profile(
        self, netbox, request
    ):
        netbox = request.getfixturevalue(netbox)

        can_handle = yield PaloaltoArp.can_handle(netbox)
        assert can_handle

    @pytest.mark.parametrize(
        "netbox",
        ["no_paloalto_http_api_netbox", "no_http_api_netbox"],
    )
    @pytest.mark.twisted
    @pytest_twisted.inlineCallbacks
    def test_it_should_not_accept_netbox_without_any_paloalto_http_api_management_profile(
        self, netbox, request
    ):
        netbox = request.getfixturevalue(netbox)

        can_handle = yield PaloaltoArp.can_handle(netbox)
        assert not can_handle


class TestGetArpMappings:
    """
    Run the PaloaltoArp plugin on disparate pre-configured netboxes, then check
    that the expected arp mappings are assigned afterwards.
    """

    @pytest.mark.parametrize(
        "netbox",
        ["paloalto_netbox_1234"],
    )
    @pytest.mark.twisted
    @pytest_twisted.inlineCallbacks
    def test_it_should_get_arp_mappings_of_netbox_having_some_paloalto_management_profile_with_valid_api_key(
        self, netbox, monkeypatch, request
    ):
        netbox = request.getfixturevalue(netbox)

        # Set up a single ipdevpoll job for this netbox:
        # Assure PaloAltoArp is a known ipdevpoll plugin
        plugin_registry['paloaltoarp'] = PaloaltoArp
        job = JobHandler('paloaltoarp', netbox.pk, plugins=['paloaltoarp'])
        # Disable implicit SNMP requests done during job.run()
        job._create_agentproxy = Mock()
        job._destroy_agentproxy = Mock()

        monkeypatch.setattr(PaloaltoArp, "_do_request", _only_accept_1234)

        assert netbox.arp_set.count() == 0

        yield job.run()

        actual = [(arp.ip, arp.mac) for arp in netbox.arp_set.all()]
        expected = [
            ('192.168.0.1', '00:00:00:00:00:01'),
            ('192.168.0.2', '00:00:00:00:00:02'),
            ('192.168.0.3', '00:00:00:00:00:03'),
        ]
        assert sorted(actual) == sorted(expected)

    @pytest.mark.parametrize(
        "netbox",
        ["paloalto_netbox_5678", "no_paloalto_http_api_netbox", "no_http_api_netbox"],
    )
    @pytest.mark.twisted
    @pytest_twisted.inlineCallbacks
    def test_it_should_not_get_arp_mappings_of_netbox_without_any_paloalto_http_api_management_profile_with_valid_api_key(
        self, netbox, monkeypatch, request
    ):
        netbox = request.getfixturevalue(netbox)

        plugin_registry['paloaltoarp'] = PaloaltoArp
        job = JobHandler('paloaltoarp', netbox.pk, plugins=['paloaltoarp'])
        job._create_agentproxy = Mock()
        job._destroy_agentproxy = Mock()

        monkeypatch.setattr(PaloaltoArp, "_do_request", _only_accept_1234)

        assert netbox.arp_set.count() == 0
        yield job.run()
        assert netbox.arp_set.count() == 0


class TestEndToEnd:
    """Tests that mimic actual usage of the plugin"""

    @pytest.mark.twisted
    @pytest_twisted.inlineCallbacks
    def test_it_should_get_arp_mappings_of_netbox_configured_with_paloalto_management_profile_using_seeddb(
        self, client, no_http_api_netbox, blank_management_profile, monkeypatch
    ):
        """
        Manually configure a netbox for use with the PaloaltoArp plugin, using
        SeedDB. Then run the PaloaltoArp plugin on this netbox and check that the
        expected arp mappings are assigned afterwards.
        """

        # Using SeedDB, edit a blank profile so that it now configures access to Palo Alto ARP
        profile = blank_management_profile
        management_profile_url = reverse(
            "seeddb-management-profile-edit", args=(profile.id,)
        )
        client.post(
            management_profile_url,
            follow=True,
            data={
                "name": profile.name,
                "description": "",
                "protocol": ManagementProfile.PROTOCOL_HTTP_API,
                "service": "Palo Alto ARP",
                "api_key": "1234",
            },
        )

        # Using SeedDB, add the profile to a netbox with no prior Palo Alto ARP management profile
        netbox = no_http_api_netbox
        netbox_url = reverse("seeddb-netbox-edit", args=(netbox.id,))
        client.post(
            netbox_url,
            follow=True,
            data={
                "ip": netbox.ip,
                "room": netbox.room_id,
                "category": netbox.category_id,
                "organization": netbox.organization_id,
                "profiles": [profile.id],
            },
        )
        profile.refresh_from_db()
        netbox.refresh_from_db()

        # Now check that the plugin correctly fetches arp mappings from this netbox
        plugin_registry['paloaltoarp'] = PaloaltoArp
        job = JobHandler('paloaltoarp', netbox.pk, plugins=['paloaltoarp'])

        job._create_agentproxy = Mock()
        job._destroy_agentproxy = Mock()

        monkeypatch.setattr(PaloaltoArp, "_do_request", _only_accept_1234)

        assert netbox.arp_set.count() == 0

        yield job.run()

        actual = [(arp.ip, arp.mac) for arp in netbox.arp_set.all()]
        expected = [
            ('192.168.0.1', '00:00:00:00:00:01'),
            ('192.168.0.2', '00:00:00:00:00:02'),
            ('192.168.0.3', '00:00:00:00:00:03'),
        ]
        assert sorted(actual) == sorted(expected)


class TestTLS:
    """Tests that the plugin uses TLS as expected"""
    @pytest.fixture
    def test_do_request_should_not_accept_invalid_cert_by_default(https_server):
        pass


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


def _only_accept_1234(self, address, key, *args, **kwargs):
    """Mimic PaloaltoArp._do_request() but only succeed if supplied key is '1234'"""
    if key == "1234":
        return defer.succeed(valid_http_response_body)
    return defer.succeed(None)


@pytest.fixture
def paloalto_netbox_1234():
    """
    Netbox with a PaloAlto HTTP
    """
    netbox = Netbox(
        ip="10.0.0.1",
        sysname="fw1.example.org",
        organization_id="myorg",
        room_id="myroom",
        category_id="SRV",
    )
    netbox.save()

    profile = ManagementProfile(
        name="PaloAlto Profile 1",
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


@pytest.fixture
def paloalto_netbox_5678():
    netbox = Netbox(
        ip="10.0.0.2",
        sysname="fw2.example.org",
        organization_id="myorg",
        room_id="myroom",
        category_id="SRV",
    )
    netbox.save()

    profile = ManagementProfile(
        name="PaloAlto Profile 2",
        protocol=ManagementProfile.PROTOCOL_HTTP_API,
        configuration={
            "api_key": "5678",
            "service": "Palo Alto ARP",
        },
    )
    profile.save()
    NetboxProfile(netbox=netbox, profile=profile).save()

    yield netbox
    netbox.delete()
    profile.delete()


@pytest.fixture
def no_http_api_netbox():
    netbox = Netbox(
        ip="10.0.0.3",
        sysname="gw1.example.org",
        organization_id="myorg",
        room_id="myroom",
        category_id="GW",
    )
    netbox.save()

    profile = ManagementProfile(
        name="SNMP v1 write profile",
        protocol=ManagementProfile.PROTOCOL_SNMP,
        configuration={
            "community": "secret",
            "version": 1,
            "write": True,
            "api_key": "1234",
            "service": "Palo Alto ARP",
        },
    )
    profile.save()
    NetboxProfile(netbox=netbox, profile=profile).save()

    yield netbox
    netbox.delete()
    profile.delete()


@pytest.fixture
def no_paloalto_http_api_netbox():
    netbox = Netbox(
        ip="10.0.0.4",
        sysname="dns.example.org",
        organization_id="myorg",
        room_id="myroom",
        category_id="SRV",
    )
    netbox.save()

    profile = ManagementProfile(
        name="PaloAlto Test Management Profile",
        protocol=ManagementProfile.PROTOCOL_HTTP_API,
        configuration={
            "api_key": "1234",
            "service": "DNS",
        },
    )
    profile.save()
    NetboxProfile(netbox=netbox, profile=profile).save()

    yield netbox
    netbox.delete()
    profile.delete()


@pytest.fixture
def blank_management_profile():
    profile = ManagementProfile(
        name="Manually Configured Paloaltoarp Profile",
        protocol=ManagementProfile.PROTOCOL_DEBUG,
        configuration={},
    )
    profile.save()
    yield profile
    profile.delete()


@pytest.fixture
def https_server():
    class Root(resource.Resource):
        isLeaf = True

        def render_GET(self, request):
            return b"get"

        def render_POST(self, request):
            return b"post"

    certificate = ssl.PrivateCertificate.loadPEM(ssl_key + ssl_cert)
    endpoint = SSL4ServerEndpoint(reactor, 0, certificate.options())
    d = endpoint.listen(server.Site(Root()))
    d.addCallback(lambda sock: sock.getHost().port)

    yield d, ssl_cert

    d.result.stopListening()


ssl_key = """\
-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCVyc3xma1h++L4
Ky+idwK80vKCYyjQsS2renUWbB+29gLQpntn4oN7KMxejgArGCzulJcQDIRBxhMo
DycjhEemRGlu7Bpvn+Zf1EYNKtP64mMOEXlIw6yLOqSRUgMedfxtOBabUEpzR26a
/Jmlb8jf5xKbdKizrJvwXm8wXw1/WeyxJ6+CCc2hm5KZ6AXNZry/j4H9KeHTlp40
ZzDwV3EHmXbw3xfWbt8IHw0R4cGZZK+Xs5Szof93fV7BcY4eEO53VGiNz0KHpjst
kKWWAhTMPHghsCc2Kwv4ThEoRiJAsSHJZu2l3aVq49/CYorOqfzLB+OhmYN1ocWW
WzKYfp73AgMBAAECggEAGdr2RhRpVccFdCH8PHZ/jfl5q+ES7AcRY46lRGQQi2Pm
s35xQcrbODigIlgvlkC7jMkwVDBc6f+XUexfrKVKOtyHOILfw1HeEb+SAfbZFW7b
e1Ov1EwWbggG3SDDchAarP2oBVI0L7buVClzGhf0HBYGY7gc4LrURgb++WIG8erf
qfNrwuaXo7PESlfhHW8xwWWuwxgZiieU9XHCP4MnGzlCItEbUFIh0uC5Sdct4eSm
8g3iNONMC5G4nSW0GxYb7+Tm4XJN/M+ytAzxtIg3xsxvoQHZS4DCtTHxOGlfGsAP
jk3Zg46VBgXowVCgML1p9Ytyz2G1jqOqA4OxwyBidQKBgQDKEVBj+ZB1SNCotoCn
iSulJbpcmmMxwWjBJYPCcv44+Ksj91DYoD6prXJ+02SdrHsv9bXPTs39vMUBUW6S
VR1ZNbGI/Hh/ek6fatmX6qGAd6W9UhD8PEaOLNOYWifzqWT87QQt8dJjUM+wUczT
KBME2+6CRrw1s4x9uD0IErvXpQKBgQC9xGXHbJYHCuFXB40U8FLfMahV2kmTYcbf
YIsRrbXxKW79PXCNuj71tSK/XFabpZ20HjXXhokDU+sKVRvhxteRF6lZvQKjEtNk
r25cTwPtBxaOVVeJoPekjKeTN6w021GoozDjW9Spcy9yreRJvZz7yDBxgVLMmg6o
dYSdzYz5awKBgADwvbAJbEuvcBEo8EZXVBWrrEdcDJQhs0wa0ZcpE9fOCHXdY8nu
TPxbK0o9z50QPW6GtTbmxfylUUFlUJ9rt/w/TLk3e5QUTKNfSu3zEJdZdzL/W8bg
vO9SdBWkbcUrh6XJsJhKJNGDgcPvTYW6DQSbxWtjyuJxGHlJTzdnZuplAoGAKePn
38ztlWJmefK1xxCCCrkIguMr6Lfl0bubF2z0Q+c0k/xzEyYw7cZthDaa+8LkfDVL
B2ewaSamNOKyw/VD8sh5XtDleyAVwB0lzIS4xiMRbJwUNdJtuEpAV7QrdIORlBtq
GFZWLI27xKH0Sf7sX3xCjVvR7k53u+ItQzRz0T8CgYEAk8jlmlAOieV6OKXJiscy
fey9rNHsjIzHkfyC81xmqzGgvY/KYM+8p3U2v64AXtXm3oSQWMyjhgZJhcILaLG8
KOUjSICfysdHtanRlk1o0WpqZka+Q0CT2IbOStDhSgbyfU8NtcR6lMkZIAkEpCJj
OeGpR5j+rPMHW9Fy5Ckrs8g=
-----END PRIVATE KEY-----
"""

ssl_cert = """\
-----BEGIN CERTIFICATE-----
MIIDtzCCAp+gAwIBAgIUNZh5bzX0uAexkm8iXRSyEIxImVcwDQYJKoZIhvcNAQEL
BQAwajELMAkGA1UEBhMCVVMxDzANBgNVBAgMBk9yZWdvbjERMA8GA1UEBwwIUG9y
dGxhbmQxFTATBgNVBAoMDENvbXBhbnkgTmFtZTEMMAoGA1UECwwDT3JnMRIwEAYD
VQQDDAlsb2NhbGhvc3QwIBcNMjUwMzI3MjA1OTUyWhgPOTk5OTEyMzExMTU5NTla
MGoxCzAJBgNVBAYTAlVTMQ8wDQYDVQQIDAZPcmVnb24xETAPBgNVBAcMCFBvcnRs
YW5kMRUwEwYDVQQKDAxDb21wYW55IE5hbWUxDDAKBgNVBAsMA09yZzESMBAGA1UE
AwwJbG9jYWxob3N0MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAlcnN
8ZmtYfvi+CsvoncCvNLygmMo0LEtq3p1FmwftvYC0KZ7Z+KDeyjMXo4AKxgs7pSX
EAyEQcYTKA8nI4RHpkRpbuwab5/mX9RGDSrT+uJjDhF5SMOsizqkkVIDHnX8bTgW
m1BKc0dumvyZpW/I3+cSm3Sos6yb8F5vMF8Nf1nssSevggnNoZuSmegFzWa8v4+B
/Snh05aeNGcw8FdxB5l28N8X1m7fCB8NEeHBmWSvl7OUs6H/d31ewXGOHhDud1Ro
jc9Ch6Y7LZCllgIUzDx4IbAnNisL+E4RKEYiQLEhyWbtpd2lauPfwmKKzqn8ywfj
oZmDdaHFllsymH6e9wIDAQABo1MwUTAdBgNVHQ4EFgQUcI/qyk6DI5KAQlCYreAZ
S0283aAwHwYDVR0jBBgwFoAUcI/qyk6DI5KAQlCYreAZS0283aAwDwYDVR0TAQH/
BAUwAwEB/zANBgkqhkiG9w0BAQsFAAOCAQEAeDwHHZIHvI92kyRzzdLg3FEuBlH7
Er3trxBGLRyMibVa+iDl46gNkIVoUFfVeUUMAECFhgHnAsZjfDc40kStYgG6dFmE
ppbKfcPl8Yx+fMGgK4SFyYzHvruZNILE1ATvkrwdoDb+mOtzVHVh4QaOL60okIhS
BJBpDkRqDmF5b+KlPTf0dDfa61L3zj99qmgKTpIzxx0lx6De4QnIEKB8ilSdrmw6
1nndctd3zx5Sa809tv2G7UTbP+r3PhuggjkPeAM8KFcwsefHmtpI9qf86RtSO+XI
eKEAkZvJH8+MKPekl45AOkuX9JQ4vus7jkR9PP7FJCgpCVvix4TPjZCUvg==
-----END CERTIFICATE-----
"""
