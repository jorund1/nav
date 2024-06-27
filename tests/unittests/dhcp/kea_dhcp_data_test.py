from collections import deque
from nav.dhcp.kea_dhcp_data import *
import pytest
import requests
from IPy import IP
import json
from requests.exceptions import JSONDecodeError

@pytest.fixture
def dhcp4_config():
    return '''
    {
        "Dhcp4": {
            "subnet4": [{
            "4o6-interface": "eth1",
            "4o6-interface-id": "ethx",
            "4o6-subnet": "2001:db8:1:1::/64",
            "allocator": "iterative",
            "authoritative": false,
            "boot-file-name": "/tmp/boot",
            "client-class": "foobar",
            "ddns-generated-prefix": "myhost",
            "ddns-override-client-update": true,
            "ddns-override-no-update": true,
            "ddns-qualifying-suffix": "example.org",
            "ddns-replace-client-name": "never",
            "ddns-send-updates": true,
            "ddns-update-on-renew": true,
            "ddns-use-conflict-resolution": true,
            "hostname-char-replacement": "x",
            "hostname-char-set": "[^A-Za-z0-9.-]",
            "id": 1,
            "interface": "eth0",
            "match-client-id": true,
            "next-server": "0.0.0.0",
            "store-extended-info": true,
            "option-data": [
                {
                    "always-send": true,
                    "code": 3,
                    "csv-format": true,
                    "data": "192.0.3.1",
                    "name": "routers",
                    "space": "dhcp4"
                }
            ],
            "pools": [
                {
                    "client-class": "phones_server1",
                    "option-data": [],
                    "pool": "192.1.0.1 - 192.1.0.200",
                    "pool-id": 7,
                    "require-client-classes": [ "late" ]
                },
                {
                    "client-class": "phones_server2",
                    "option-data": [],
                    "pool": "192.3.0.1 - 192.3.0.200",
                    "require-client-classes": []
                }
            ],
            "rebind-timer": 40,
            "relay": {
                "ip-addresses": [
                    "192.168.56.1"
                ]
            },
            "renew-timer": 30,
            "reservations-global": true,
            "reservations-in-subnet": true,
            "reservations-out-of-pool": true,
            "calculate-tee-times": true,
            "t1-percent": 0.5,
            "t2-percent": 0.75,
            "cache-threshold": 0.25,
            "cache-max-age": 1000,
            "reservations": [
                {
                    "circuit-id": "01:11:22:33:44:55:66",
                    "ip-address": "192.0.2.204",
                    "hostname": "foo.example.org",
                    "option-data": [
                        {
                            "name": "vivso-suboptions",
                            "data": "4491"
                        }
                    ]
                }
            ],
            "require-client-classes": [ "late" ],
            "server-hostname": "myhost.example.org",
            "subnet": "192.0.0.0/8",
            "valid-lifetime": 6000,
            "min-valid-lifetime": 4000,
            "max-valid-lifetime": 8000
            }]
        }
    }
    '''

@pytest.fixture(autouse=True)
def enqueue_post_response(monkeypatch):
    """
    Any test that include this fixture, gets access to a function that
    can be used to append text strings to a fifo queue of post
    responses that in fifo order will be returned as proper Response
    objects by calls to requests.post and requests.Session().post.

    This is how we mock what would otherwise be post requests to a
    server.
    """
    fifo = deque() # stores the textual content of the responses we want to return on any call to requests.post

    def new_post_function(url, *args, **kwargs):
        response = requests.Response()
        response._content = fifo.popleft().encode("utf8")
        response.encoding = "utf8"
        response.status_code = 400
        response.reason = "OK"
        response.headers = kwargs.get("headers", {})
        response.cookies = kwargs.get("cookies", {})
        response.url = url
        response.close = lambda: True
        return response

    def new_post_method(self, url, *args, **kwargs):
        return new_post_function(url, *args, **kwargs)

    monkeypatch.setattr(requests, 'post', new_post_function)
    monkeypatch.setattr(requests.Session, 'post', new_post_method) # Not sure this works?

    return fifo.append

@pytest.fixture
def success_response():
    return '''[
    {"result": 0, "text": "b", "arguments": {"arg1": "val1"}, "service": "d"},
    {"result": 0, "arguments": {"arg1": "val1"}, "service": "d"},
    {"result": 0, "service": "d"},
    {"result": 0}
    ]'''

@pytest.fixture
def error_response():
    return '''[
    {"result": 1, "text": "b", "arguments": {"arg1": "val1"}, "service": "d"},
    {"result": 2, "text": "b", "arguments": {"arg1": "val1"}, "service": "d"},
    {"result": 3, "text": "b", "arguments": {"arg1": "val1"}, "service": "d"},
    {"result": 4, "text": "b", "arguments": {"arg1": "val1"}, "service": "d"},
    {"text": "b", "arguments": {"arg1": "val1"}, "service": "d"}
    ]'''

@pytest.fixture
def invalid_json_response():
    return '''[
    {"result": 1, "text": "b", "arguments": {"arg1": "val1"}, "service": "d"},
    {"result": 2, "text": "b", "arguments": {"arg1": "val1"}, "service": "d"},
    {"result": 3, "text": "b", "arguments": {"arg1": "val1"}, "service": "d"},
    {"result": 4, "text": "b", "arguments": {"arg1": "val1"}, "service": "d"},
    {"text": "b", "arguments": {"arg1": "val1"}, "service": "d"
    ]'''

@pytest.fixture
def large_response():
    return '''

    '''

def send_dummy_query():
    return send_query(
        query=KeaQuery("command", [], {}),
        address="192.0.2.2",
        port=80,
    )

def test_success_responses_does_succeed(success_response, enqueue_post_response):
    enqueue_post_response(success_response)
    responses = send_dummy_query()
    assert len(responses) == 4
    for response in responses:
        assert response.success
        assert isinstance(response.text, str)
        assert isinstance(response.arguments, dict)
        assert isinstance(response.service, str)

def test_error_responses_does_not_succeed(error_response, enqueue_post_response):
    enqueue_post_response(error_response)
    responses = send_dummy_query()
    assert len(responses) == 5
    for response in responses:
        assert not response.success
        assert isinstance(response.text, str)
        assert isinstance(response.arguments, dict)
        assert isinstance(response.service, str)

def test_invalid_json_responses_raises_jsonerror(invalid_json_response, enqueue_post_response):
    enqueue_post_response(invalid_json_response)
    with pytest.raises(JSONDecodeError):
        responses = send_dummy_query()

def test_correct_subnet_from_json(dhcp4_config):
    j = json.loads(dhcp4_config)
    subnet = KeaDhcpSubnet.from_json(j["Dhcp4"]["subnet4"][0])
    assert subnet.id == 1
    assert subnet.prefix == IP("192.0.0.0/8")
    assert len(subnet.pools) == 2
    assert subnet.pools[0] == (IP("192.1.0.1"), IP("192.1.0.200"))
    assert subnet.pools[1] == (IP("192.3.0.1"), IP("192.3.0.200"))

# def test_correct_config_from_json(dhcp4_config):
#     j = json.loads(dhcp4_config)
#     config = KeaDhcpConfig.from_json(j)
#     assert len(config.subnets) == 1
#     subnet = config.subnets[0]
#     assert subnet.id == 1
#     assert subnet.prefix == IP("192.0.0.0/8")
#     assert len(subnet.pools) == 2
#     assert subnet.pools[0] == (IP("192.1.0.1"), IP("192.1.0.200"))
#     assert subnet.pools[1] == (IP("192.3.0.1"), IP("192.3.0.200"))
#     assert config.ip_version == 4

# @pytest.fixture
# def dhcp4_config_response(dhcp4_config):
#     return f'''
#     {{
#         "result": 0,
#         "arguments": {{
#             {dhcp4_config}
#         }}
#     }}
#     '''

# def test_get_dhcp_config(dhcp4_config_response):
#     enqueue_post_response(dhcp4_config_response)
#     response = send_dummy_query()
#     config = KeaDhcpConfig.from_json(config_json)
#     assert len(config.subnets) == 1
#     subnet = config.subnets[0]
#     assert subnet.id == 1
#     assert subnet.prefix == IP("192.0.0.0/8")
#     assert len(subnet.pools) == 2
#     assert subnet.pools[0] == (IP("192.1.0.1"), IP("192.1.0.200"))
#     assert subnet.pools[1] == (IP("192.3.0.1"), IP("192.3.0.200"))
#     assert config.ip_version == 4

# @pytest.fixture
# @enqueue_post_response
# def dhcp4_config_response_result_is_1():
#     return f'''
#     {{
#         "result": 1,
#         "arguments": {{
#             {DHCP4_CONFIG}
#         }}
#     }}
#     '''

# def test_get_dhcp_config_result_is_1(dhcp4_config_result_is_1):
#     with pytest.raises(Exception): # TODO: Change
#         get_dhcp_server("example-org", ip_version=4)
