from collections import deque
from nav.externalstats.kea_dhcp import *
from nav.externalstats.kea_dhcp import _KeaStatus, _Metric
import pytest
import requests
from IPy import IP
import json
from requests.exceptions import JSONDecodeError
from typing import Union, Callable
from dataclasses import replace
from datetime import datetime, timedelta

#TODO: Test _create_session

class TestRecognizableAPIResponses:
    """
    Tests the various types of responses from the Kea Management API that the
    client should expect and handle appropiately.
    """

    def test_fetch_stats_should_return_correct_stats(
        self, valid_dhcp4, responsequeue
    ):
        """
        This test checks that fetch_stats() returns the most recent stats
        for each subnet and type from the api response
        """

        config, statistics, expected_stats = valid_dhcp4
        responsequeue.autofill("dhcp4", config=config, statistics=statistics)
        client = Client("http://example.org/")

        actual_stats = client.fetch_stats()

        def clean(stats):
            """
            Set stat timestamps to zero, because we do not care to compare the
            time a stat was fetched into NAV in this test.
            """
            return [replace(stat, timestamp=0) for stat in stats]

        assert set(clean(actual_stats)) == set(clean(expected_stats))

    def test_fetch_stats_should_only_have_recent_timestamps(
        self, valid_dhcp4, responsequeue
    ):
        """
        This test checks that fetch_stats() only returns stats that have
        recent timestamps - so that periodically fetching stats will form an
        evenly spaced timeseries (Kea doesn't seem to change timestamps unless
        stat data is changed, which results in very sporadic timeseries)
        """

        config, statistics, expected_stats = valid_dhcp4
        responsequeue.autofill("dhcp4", config=config, statistics=statistics)
        client = Client("http://example.org/")

        actual_stats = client.fetch_stats()
        assert len(actual_stats) > 0
        for stat in actual_stats:
            assert (
                stat.timestamp >= (datetime.now() - timedelta(minutes=5)).timestamp()
            )

    def test_fetch_stats_should_handle_empty_config_in_api_configuration_response(
        self, valid_dhcp4, responsequeue
    ):
        """
        We assume in this case that the Kea DHCP server we query just doesn't have
        any subnets configured

        The correct thing for fetch_stats() to do in this case is to just
        return an empty list of stats since there are no subnets to fetch
        from.

        TODO: Here, it may be wished for that NAV prints a log info stating
        that the Kea server isn't configured with any subnets.
        """
        config, statistics, _ = valid_dhcp4
        responsequeue.autofill("dhcp4", config=None, statistics=statistics)
        responsequeue.add("config-get", lambda *a, **ka: kearesponse({"Dhcp4": {}}))
        client = Client("http://example.org/")
        assert list(client.fetch_stats()) == []

    def test_fetch_stats_should_handle_empty_statistic_in_api_statistics_response(
        self, valid_dhcp4, responsequeue
    ):
        """
        If the Kea DHCP server returns no values for a specific statistic,
        disregard that stat when creating a list of stats. In the extreme
        case that all statistics are empty, return an empty list.
        """
        config, statistics, _ = valid_dhcp4
        responsequeue.autofill("dhcp4", config=config, statistics=None)
        responsequeue.add(
            "statistic-get",
            lambda requestarguments, *a, **ka: kearesponse(
                {requestarguments["name"]: []}
            ),
        )
        client = Client("http://example.org/")
        assert list(client.fetch_stats()) == []

    def test_fetch_stats_should_handle_unsupported_statistic_in_statistics_response(
        self, valid_dhcp4, responsequeue
    ):
        """
        If the Kea DHCP server doesn't support a specific stat (e.g. because we query an
        outdated version), just disregard that meric, and in the extreme case that no stat
        is supported, return an empty list.

        TODO: Here, it may be wished for that NAV prints a log warning stating
        that the Kea server doesn't support some queried-for statistic.

        From the Kea doc:
        > If the requested statistic is not found, the response contains an
        > empty map, i.e. only { } as an argument, but the status code still indicates
        > success (0).
        > https://web.archive.org/web/20230927054750/https://kea.readthedocs.io/en/kea-2.2.0/arm/stats.html#the-statistic-get-command
        """

        config, statistics, _ = valid_dhcp4
        responsequeue.autofill("dhcp4", config=config, statistics=None)
        responsequeue.add("statistic-get", lambda *a, **ka: kearesponse({}))
        client = Client("http://example.org/")
        assert list(client.fetch_stats()) == []

    def test_fetch_stats_should_raise_an_exception_on_http_error_response(
        self, valid_dhcp4, responsequeue
    ):
        """
        We shouldn't even attempt to find valid responses if the server won't
        respond correctly
        """

        config, statistics, _ = valid_dhcp4
        responsequeue.autofill(
            "dhcp4",
            config=config,
            statistics=statistics,
            attrs={"status_code": 403},
        )

        client = Client("http://example.org/")

        with pytest.raises(KeaException):
            client.fetch_stats()

    @pytest.mark.parametrize(
        "status", [status for status in _KeaStatus if status != _KeaStatus.SUCCESS]
    )
    def test_fetch_stats_should_raise_an_exception_on_error_status_in_config_response_from_api(
        self, valid_dhcp4, responsequeue, status
    ):
        """
        We shouldn't even attempt to continue if the server reports
        an error regarding serving its configuration
        """
        config, statistics, _ = valid_dhcp4
        responsequeue.autofill("dhcp4", config=None, statistics=statistics)
        responsequeue.add("config-get", kearesponse(config, status=status))
        client = Client("http://example.org/")
        with pytest.raises(KeaException):
            client.fetch_stats()

    @pytest.mark.parametrize(
        "status", [status for status in _KeaStatus if status != _KeaStatus.SUCCESS]
    )
    def test_fetch_stats_should_raise_an_exception_on_error_status_in_statistic_response_from_api(
        self, valid_dhcp4, responsequeue, status
    ):
        """
        We shouldn't even attempt to continue if the server reports
        an error regarding serving statistics
        """
        config, statistics, _ = valid_dhcp4
        responsequeue.autofill("dhcp4", config=config, statistics=None)
        responsequeue.add("statistic-get", kearesponse(statistics, status=status))
        client = Client("http://example.org/")
        with pytest.raises(KeaException):
            client.fetch_stats()

    @pytest.mark.parametrize(
        "status",
        [
            status
            for status in _KeaStatus
            if status not in (_KeaStatus.SUCCESS, _KeaStatus.UNSUPPORTED)
        ],
    )
    def test_fetch_stats_should_raise_an_exception_on_error_status_in_config_hash_response_from_api(
        self, valid_dhcp4, responsequeue, status
    ):
        """
        We shouldn't even attempt to continue if the server reports
        an error regarding serving configuration hash other than it
        being unsupported
        """
        foohash = "b5bb9d8014a0f9b1d61e21e796d78dccdf1352f23cd32812f4850b878ae4944c"
        config, statistics, _ = valid_dhcp4
        client = Client("http://example.org/")
        config["Dhcp4"]["hash"] = foohash
        responsequeue.autofill("dhcp4", config=config, statistics=statistics)
        responsequeue.add(
            "config-hash-get", kearesponse({"hash": foohash}, status=status)
        )
        with pytest.raises(KeaException):
            client.fetch_stats()


class TestUnrecognizableAPIResponses:
    """
    If Kea responds in an unrecognizable way, we should always fail loudly,
    because chances are either the host we're sending requests to is not a Kea
    Control Agent, or there's a part of the API that we've not covered
    correctly.
    """

    invalid_response = "{}"

    def test_fetch_stats_should_raise_an_exception_on_unrecognizable_config_response_from_api(
        self, valid_dhcp4, responsequeue
    ):
        config, statistics, _ = valid_dhcp4
        client = Client("http://example.org/")

        responsequeue.autofill("dhcp4", config=None, statistics=statistics)
        responsequeue.add("config-get", self.invalid_response)
        with pytest.raises(KeaException):
            client.fetch_stats()

    def test_fetch_stats_should_raise_an_exception_on_unrecognizable_statistic_response_from_api(
        self, valid_dhcp4, responsequeue
    ):
        config, statistics, _ = valid_dhcp4
        client = Client("http://example.org/")

        responsequeue.autofill("dhcp4", config=config, statistics=None)
        responsequeue.add("statistic-get", self.invalid_response)
        with pytest.raises(KeaException):
            client.fetch_stats()

    def test_fetch_stats_should_raise_an_exception_on_unrecognizable_config_hash_response_from_api(
        self, valid_dhcp4, responsequeue
    ):
        config, statistics, _ = valid_dhcp4
        client = Client("http://example.org/")
        config["Dhcp4"]["hash"] = "foo"
        responsequeue.autofill("dhcp4", config=config, statistics=statistics)
        responsequeue.add("config-hash-get", self.invalid_response)
        with pytest.raises(KeaException):
            client.fetch_stats()


@pytest.fixture
def valid_dhcp4():
    config = {
        "Dhcp4": {
            "valid-lifetime": 4000,
            "renew-timer": 1000,
            "rebind-timer": 2000,
            "preferred-lifetime": 3000,
            "interfaces-config": {"interfaces": ["eth0"]},
            "lease-database": {
                "type": "memfile",
                "persist": True,
                "name": "/var/lib/kea/dhcp6.leases",
            },
            "subnet4": [
                {
                    "id": 1,
                    "subnet": "192.0.1.0/24",
                    "pools": [{"pool": "192.0.1.1-192.0.1.10"}],
                },
                {
                    "id": 2,
                    "subnet": "192.0.2.0/24",
                    "pools": [
                        {"pool": "192.0.2.1-192.0.2.10"},
                        {"pool": "192.0.2.128/25"},
                    ],
                },
            ],
            "shared-networks": [
                {
                    "name": "shared-network-1",
                    "subnet4": [
                        {
                            "id": 3,
                            "subnet": "192.0.3.0/24",
                            "pools": [
                                {"pool": "192.0.3.1-192.0.3.10"},
                            ],
                        },
                        {
                            "id": 4,
                            "subnet": "192.0.4.1/24",
                            "pools": [
                                {"pool": "192.0.4.1-192.0.4.5"},
                            ],
                        },
                    ],
                },
                {
                    "name": "shared-network-2",
                    "subnet4": [
                        {
                            "id": 5,
                            "subnet": "192.0.5.0/24",
                            "pools": [
                                {"pool": "192.0.5.1-192.0.5.5"},
                            ],
                        }
                    ],
                },
            ],
        }
    }
    statistics = {
        "subnet[1].assigned-addresses": [
            [1, "2024-07-22 09:06:58.140438"],
            [0, "2024-07-05 20:44:54.230608"],
            [1, "2024-07-05 09:15:05.626594"],
        ],
        "subnet[1].declined-addresses": [[0, "2024-07-03 16:13:59.401071"]],
        "subnet[1].total-addresses": [[239, "2024-07-03 16:13:59.401058"]],
        "subnet[2].assigned-addresses": [
            [0, "2024-07-22 09:06:58.140439"],
            [1, "2024-07-05 20:44:54.230609"],
            [2, "2024-07-05 09:15:05.626595"],
        ],
        "subnet[2].declined-addresses": [[1, "2024-07-03 16:13:59.401072"]],
        "subnet[2].total-addresses": [[240, "2024-07-03 16:13:59.401059"]],
        "subnet[3].assigned-addresses": [
            [4, "2024-07-22 09:06:58.140439"],
            [5, "2024-07-05 20:44:54.230609"],
        ],
        "subnet[3].declined-addresses": [[0, "2024-07-03 16:13:59.401072"]],
        "subnet[3].total-addresses": [[241, "2024-07-03 16:13:59.401059"]],
        "subnet[4].assigned-addresses": [
            [1, "2024-07-22 09:06:58.140439"],
            [1, "2024-07-05 20:44:54.230609"],
        ],
        "subnet[4].declined-addresses": [[1, "2024-07-03 16:13:59.401072"]],
        "subnet[4].total-addresses": [[242, "2024-07-03 16:13:59.401059"]],
        "subnet[5].assigned-addresses": [
            [1, "2024-07-22 09:06:58.140439"],
            [1, "2024-07-05 20:44:54.230609"],
        ],
        "subnet[5].declined-addresses": [[1, "2024-07-03 16:13:59.401072"]],
        "subnet[5].total-addresses": [[243, "2024-07-03 16:13:59.401059"]],
    }

    # Each list in the 'statistics' response from the api (see above dict) is a
    # timeseries for a specific stat type for a specific subnet.  The first
    # stat in each list is assumed to be the most recent, and this is the
    # stat we expect to get for each stat type and subnet after processing
    # the api response.
    expected_stats = [
        _Metric(
            datetime.fromisoformat("2024-07-22T09:06:58.140438+00:00").timestamp(),
            IP("192.0.1.0/24"),
            "assigned",
            1,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-03T16:13:59.401058+00:00").timestamp(),
            IP("192.0.1.0/24"),
            "total",
            239,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-03T16:13:59.401058+00:00").timestamp(),
            IP("192.0.1.0/24"),
            "declined",
            0,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-22T09:06:58.140439+00:00").timestamp(),
            IP("192.0.2.0/24"),
            "assigned",
            0,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-03T16:13:59.401059+00:00").timestamp(),
            IP("192.0.2.0/24"),
            "total",
            240,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-03T16:13:59.401059+00:00").timestamp(),
            IP("192.0.2.0/24"),
            "declined",
            1,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-22T09:06:58.140439+00:00").timestamp(),
            IP("192.0.3.0/24"),
            "assigned",
            4,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-03T16:13:59.401059+00:00").timestamp(),
            IP("192.0.3.0/24"),
            "total",
            241,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-03T16:13:59.401059+00:00").timestamp(),
            IP("192.0.3.0/24"),
            "declined",
            0,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-22T09:06:58.140439+00:00").timestamp(),
            IP("192.0.4.0/24"),
            "assigned",
            1,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-03T16:13:59.401059+00:00").timestamp(),
            IP("192.0.4.0/24"),
            "total",
            242,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-03T16:13:59.401059+00:00").timestamp(),
            IP("192.0.4.0/24"),
            "declined",
            1,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-22T09:06:58.140439+00:00").timestamp(),
            IP("192.0.5.0/24"),
            "assigned",
            1,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-03T16:13:59.401059+00:00").timestamp(),
            IP("192.0.5.0/24"),
            "total",
            243,
        ),
        _Metric(
            datetime.fromisoformat("2024-07-03T16:13:59.401059+00:00").timestamp(),
            IP("192.0.5.0/24"),
            "declined",
            1,
        ),
    ]

    return config, statistics, expected_stats


def kearesponse(val, status=_KeaStatus.SUCCESS):
    """
    Make a Kea API conformant response body whose response value (called
    response arguments in the specification) is given by the dictionary `val`
    """
    return f'''
[
    {{
        "result": {status},
        "arguments": {json.dumps(val)}
    }}
]
    '''


@pytest.fixture
def responsequeue(monkeypatch):
    """
    Any test that include this fixture, will automatically mock
    requests.Session.post() and requests.post(). The fixture returns a
    namespace with three functions:

    responsequeue.add(command, text_or_func, attrs=None) --- appends the given
    text_or_func, which is either a string or a function f(dict, list) ->
    string, to the given command string's associated fifo queue to use in
    generating responses for Kea API requests for command. On any calls to
    requests.post() or requests.Session().post() in the code under test, the Kea
    API command is extracted from the request body and the text of the next
    element in that command's fifo becomes the text-value of the mocked
    requests.post() requests.Response return value. Text strings are popped from
    the fifo after use, while functions are not. If the fifo was empty, an API
    conformant "command not supported" response is returned instead. The attrs
    keyword (see again the function signature at the top of this paragraph) can
    optionally be set to a dictionary of attributes to set on the
    requests.Response response. Setting attrs={"status": 404} will cause the
    response to be a HTTP 404 error.

    responsequeue.clear() --- Empty the fifo queues of all commands. This
    removes all previously configured command responses.

    responsequeue.autofill(service, config, statistics) --- fill the queue for
    the "config-get" and "statistic-get" commands to mimic the response texts
    actually sent by a Kea Control Agent for a Kea DHCP server named `service`
    ("dhcp4" for ipv4 DHCP "dhcp6" for ipv6 DHCP) with config `config` and
    statistics `statistics`.
    """
    command_responses: dict[
        str, deque[tuple[Union[str, Callable[[dict, list], str]], dict]]
    ] = {}
    unknown_command_response = """[
  {{
    "result": 2,
    "text": "'{0}' command not supported."
  }}
]"""

    def new_post_function(url, *args, data="{}", **kwargs):
        """This function will replace requests.post()"""
        if isinstance(data, dict):
            data = json.dumps(data)
        elif isinstance(data, bytes):
            data = data.decode("utf8")
        if not isinstance(data, str):
            pytest.fail(
                f"data argument to the mocked requests.post() is of unknown type {type(data)}"
            )

        try:
            data = json.loads(data)
            command = data["command"]
        except (JSONDecodeError, KeyError):
            pytest.fail(
                "All post requests that NAV sends to the Kea Control Agent"
                "should be a JSON with a 'command' key. Instead, NAV sent "
                f"\n\n{data!r}\n\n to the test's Kea Control Agent mock"
            )

        response_text = unknown_command_response.format(command)
        attrs = {}
        fifo = command_responses.get(command, deque())
        if fifo:
            text_or_func, attrs = fifo[0]
            if callable(text_or_func):
                kea_arguments = data.get("arguments", {})
                kea_service = data.get("service", [])
                response_text = text_or_func(kea_arguments, kea_service)
            else:
                response_text = str(text_or_func)
                fifo.popleft()

        response = requests.Response()
        response._content = response_text.encode("utf8")
        response.encoding = "utf8"
        response.status_code = 200
        response.reason = "OK"
        response.headers = kwargs.get("headers", {})
        response.cookies = kwargs.get("cookies", {})
        response.url = url
        response.close = lambda: None

        for attr, value in attrs.items():
            setattr(response, attr, value)

        return response

    def new_post_method(self, url, *args, **kwargs):
        """This function will replace requests.Session.post()"""
        return new_post_function(url, *args, **kwargs)

    def add_command_response(command_name, text, attrs=None):
        attrs = attrs or {}
        command_responses.setdefault(command_name, deque())
        command_responses[command_name].append((text, attrs))

    def clear_command_responses():
        command_responses.clear()

    def autofill_command_responses(
        expected_service, config=None, statistics=None, attrs=None
    ):
        attrs = attrs or {}

        if config is not None:

            def config_get_response(arguments, service):
                assert service == [
                    expected_service
                ], f"API Client for service [{expected_service}] should not send requests to {service}"
                return kearesponse(config)

            add_command_response("config-get", config_get_response, attrs)

        if statistics is not None:

            def statistic_get_response(arguments, service):
                assert service == [
                    expected_service
                ], f"API Client for service [{expected_service}] should not send requests to {service}"
                return kearesponse({arguments["name"]: statistics[arguments["name"]]})

            add_command_response("statistic-get", statistic_get_response, attrs)

    class ResponseQueue:
        add = add_command_response
        clear = clear_command_responses
        autofill = autofill_command_responses

    monkeypatch.setattr(requests, 'post', new_post_function)
    monkeypatch.setattr(requests.Session, 'post', new_post_method)

    return ResponseQueue
