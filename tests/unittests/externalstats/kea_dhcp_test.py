import logging
from unittest import mock
from copy import deepcopy
from collections import deque
from nav.externalstats.kea_dhcp import *
from nav.externalstats.kea_dhcp import _KeaStatus
import pytest
import requests
import json
from requests.exceptions import JSONDecodeError
from typing import Callable
from datetime import datetime, timedelta

ENDPOINT_IDENTIFIER = "dhcp-server-foo"

#TODO: Test when variying 'user_context_poolname_key'

class TestRecognizableAPIResponses:
    """
    Tests the various types of responses from the Kea Management API that the
    client should expect and handle appropiately.
    """

    def test_fetch_stats_should_return_correct_stats(
        self, valid_dhcp4, response_queue
    ):
        """
        This test checks that fetch_stats() returns the most recent stats from
        the api for each <pool> and <stat type>.
        """

        config, statistics, expected_stats = valid_dhcp4
        response_queue.autofill("dhcp4", config=config, statistics=statistics)
        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")

        actual_stats = client.fetch_stats()

        def normalize(stats):
            """
            Set stat timestamps to zero, because we do not care to compare the
            time a stat was fetched into NAV in this test.
            """
            return sorted((path, (0, value)) for (path, (time, value)) in stats)

        assert normalize(actual_stats) == normalize(expected_stats)


    def test_fetch_stats_should_only_have_recent_timestamps(
        self, valid_dhcp4, response_queue
    ):
        """
        This test checks that fetch_stats() returns stats that have recent
        enough timestamps - so that periodically fetching stats will form an
        evenly spaced timeseries in graphite.
        """

        config, statistics, expected_stats = valid_dhcp4
        response_queue.autofill("dhcp4", config=config, statistics=statistics)
        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")

        actual_stats = client.fetch_stats()
        assert len(actual_stats) > 0
        for (path, (time, value)) in actual_stats:
            assert time >= (datetime.now() - timedelta(minutes=5)).timestamp()


    def test_fetch_stats_should_handle_empty_config_api_response(
        self, valid_dhcp4, response_queue
    ):
        """
        The client should handle the case where the Kea API responds with an
        empty dictionary as a response to a config request.  We assume in this
        case that the Kea DHCP server we query just doesn't have any pools
        configured.  The correct thing to do in this case is to just return an
        empty list of stats since there are no pools to fetch from.

        TODO: It may be benefitial to have NAV log a message when this lack of
        pool configuration occur.
        """
        config, statistics, _ = valid_dhcp4
        response_queue.autofill("dhcp4", config=None, statistics=statistics)
        response_queue.add(
            "config-get",
            lambda kea_arguments, kea_service: make_api_response({"Dhcp4": {}})
        )
        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")
        assert list(client.fetch_stats()) == []


    def test_fetch_stats_should_handle_empty_statistic_api_response(
        self, valid_dhcp4, response_queue
    ):
        """
        If the Kea DHCP server returns no values for a specific statistic,
        disregard that stat in 'fetch_stats()' when creating a list of stats. In
        the extreme case that all statistic from the API are empty,
        'fetch_stats()' should return an empty list.
        """
        config, statistics, _ = valid_dhcp4
        response_queue.autofill("dhcp4", config=config, statistics=None)
        response_queue.add(
            "statistic-get",
            lambda kea_arguments, kea_service: make_api_response(
                {kea_arguments["name"]: []},
            ),
        )
        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")
        assert list(client.fetch_stats()) == []


    def test_fetch_stats_should_handle_unsupported_statistic_api_response(
        self, valid_dhcp4, response_queue
    ):
        """
        If the Kea DHCP server doesn't support a specific statistic type
        (e.g. because we query an outdated Kea version), just disregard that
        statistic type, and in the extreme case that no statistic type at all is
        supported, return an empty list.

        From the Kea doc:
          If the requested statistic is not found, the response contains an
          empty map, i.e. only { } as an argument, but the status code still indicates
          success (0).
          https://web.archive.org/web/20230927054750/https://kea.readthedocs.io/en/kea-2.2.0/arm/stats.html#the-statistic-get-command

        TODO: It may be benefitial to have NAV log a message when this lack of
        statistic support occur.
        """

        config, statistics, _ = valid_dhcp4
        response_queue.autofill("dhcp4", config=config, statistics=None)
        response_queue.add(
            "statistic-get",
            lambda kea_arguments, kea_service: make_api_response({})
        )
        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")
        assert list(client.fetch_stats()) == []


    @pytest.mark.parametrize("http_status", chain(range(400,430), range(500,530)))
    def test_fetch_stats_should_raise_an_exception_on_http_error_response(
        self, valid_dhcp4, response_queue, http_status
    ):
        """
        If the server responds with an HTTP error, the client should raise an
        error.
        """

        config, statistics, _ = valid_dhcp4
        response_queue.autofill(
            "dhcp4",
            config=config,
            statistics=statistics,
            attrs={"status_code": http_status},
        )

        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")

        with pytest.raises(CommunicationError):
            client.fetch_stats()


    @pytest.mark.parametrize(
        "kea_status", [status for status in _KeaStatus if status != _KeaStatus.SUCCESS]
    )
    def test_fetch_stats_should_raise_an_exception_on_error_status_in_config_api_response(
        self, valid_dhcp4, response_queue, kea_status
    ):
        """
        If the server reports an API-specific error regarding serving its
        configuration, the client should raise an error.
        """
        config, statistics, _ = valid_dhcp4
        response_queue.autofill("dhcp4", config=None, statistics=statistics)
        response_queue.add(
            "config-get",
            lambda kea_arguments, kea_service: make_api_response(config, status=kea_status)
        )
        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")
        with pytest.raises(CommunicationError):
            client.fetch_stats()


    @pytest.mark.parametrize(
        "status", [status for status in _KeaStatus if status not in (_KeaStatus.SUCCESS, _KeaStatus.EMPTY)]
    )
    def test_fetch_stats_should_raise_an_exception_on_error_status_in_statistic_api_response(
        self, valid_dhcp4, response_queue, status
    ):
        """
        If the server reports an API-specific error regarding serving
        statistics, the client should raise an error.
        """
        config, statistics, _ = valid_dhcp4
        response_queue.autofill("dhcp4", config=config, statistics=None)
        response_queue.add(
            "statistic-get",
            lambda kea_arguments, kea_service: make_api_response(statistics, status=status),
        )
        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")
        with pytest.raises(CommunicationError):
            client.fetch_stats()


    @pytest.mark.parametrize(
        "status",
        [
            status
            for status in _KeaStatus
            if status not in (_KeaStatus.SUCCESS, _KeaStatus.UNSUPPORTED)
        ],
    )
    def test_fetch_stats_should_raise_an_exception_on_error_status_in_config_hash_api_response(
        self, valid_dhcp4, response_queue, status
    ):
        """
        If the server reports an API-specific error regarding serving its
        configuration's hash, other than that functionality being unsupported,
        the client should raise an error.
        """
        foohash = "b5bb9d8014a0f9b1d61e21e796d78dccdf1352f23cd32812f4850b878ae4944c"
        config, statistics, _ = valid_dhcp4
        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")
        config["Dhcp4"]["hash"] = foohash
        response_queue.autofill("dhcp4", config=config, statistics=statistics)
        response_queue.add(
            "config-hash-get", make_api_response({"hash": foohash}, status=status)
        )
        with pytest.raises(CommunicationError):
            client.fetch_stats()


@pytest.mark.parametrize("invalid_response", ["{}", "foo", "\x00", "[]", "1"])
class TestUnrecognizableAPIResponses:
    """
    Checks that the client fails loudly if the Kea Management API responds in an
    unrecognizable way.
    """

    def test_fetch_stats_should_raise_an_exception_on_unrecognizable_config_api_response(
        self, valid_dhcp4, response_queue, invalid_response
    ):
        config, statistics, _ = valid_dhcp4
        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")

        response_queue.autofill("dhcp4", config=None, statistics=statistics)
        response_queue.add("config-get", invalid_response)
        with pytest.raises(KeaUnexpected):
            client.fetch_stats()

    def test_fetch_stats_should_raise_an_exception_on_unrecognizable_statistic_api_response(
        self, valid_dhcp4, response_queue, invalid_response
    ):
        config, statistics, _ = valid_dhcp4
        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")

        response_queue.autofill("dhcp4", config=config, statistics=None)
        response_queue.add("statistic-get", invalid_response)
        with pytest.raises(KeaUnexpected):
            client.fetch_stats()

    def test_fetch_stats_should_raise_an_exception_on_unrecognizable_config_hash_api_response(
        self, valid_dhcp4, response_queue, invalid_response
    ):
        config, statistics, _ = valid_dhcp4
        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")
        config["Dhcp4"]["hash"] = "foo"
        response_queue.autofill("dhcp4", config=config, statistics=statistics)
        response_queue.add("config-hash-get", invalid_response)
        with pytest.raises(KeaUnexpected):
            client.fetch_stats()


class TestConfigCaching:
    """
    Checks that the '_fetch_kea_config()' method doesn't request the DHCP
    configuration from the Kea Management API more often than necessary.
    """

    def test_fetch_kea_config_should_not_refetch_config_if_its_hash_is_unchanged(
            self, response_queue
    ):
        response_queue.add(
            "config-get",
            lambda kea_arguments, kea_service: make_api_response({"Dhcp4": {"hash": "1"}}),
        )
        response_queue.add(
            "config-hash-get",
            lambda kea_arguments, kea_service: make_api_response({"hash": "1"}),
        )

        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")
        client._fetch_kea_config()
        client._fetch_kea_config()

        assert len(response_queue.requests["config-get"]) == 1


    def test_fetch_kea_config_should_refetch_config_if_its_hash_is_changed(
            self, response_queue
    ):
        response_queue.add(
            "config-get",
            lambda kea_arguments, kea_service: make_api_response({"Dhcp4": {}, "hash": "1"}),
        )
        response_queue.add(
            "config-hash-get",
            lambda kea_arguments, kea_service: make_api_response({"hash": "2"}),
        )

        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")
        client._fetch_kea_config()
        client._fetch_kea_config()

        assert len(response_queue.requests["config-get"]) == 2


    def test_fetch_kea_config_should_refetch_config_if_its_hash_is_missing(
            self, response_queue
    ):
        response_queue.add(
            "config-get",
            lambda kea_arguments, kea_service: make_api_response({"Dhcp4": {}}),
        )
        response_queue.add(
            "config-hash-get",
            lambda kea_arguments, kea_service: make_api_response({"hash": "1"}),
        )

        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")
        client._fetch_kea_config()
        client._fetch_kea_config()

        assert len(response_queue.requests["config-get"]) == 2


    def test_fetch_kea_config_should_refetch_config_if_config_hash_is_unsupported(
            self, response_queue
    ):
        response_queue.add(
            "config-get",
            lambda kea_arguments, kea_service: make_api_response({"Dhcp4": {}, "hash": "1"}),
        )

        client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")
        client._fetch_kea_config()
        client._fetch_kea_config()

        assert len(response_queue.requests["config-get"]) == 2


def test_fetch_stats_should_check_and_warn_if_server_config_changed_during_call(
        valid_dhcp4, response_queue, caplog
):
    config, statistics, _ = valid_dhcp4
    client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")
    response_queue.autofill("dhcp4", config=None, statistics=statistics)
    response_queue.add("config-get", make_api_response(config))
    updated_config = deepcopy(config)
    updated_config["Dhcp4"]["subnet4"][0]["pools"][0]["pool"] = "42.0.1.1-42.0.1.5"
    response_queue.add(
        "config-get",
        lambda kea_arguments, kea_service: make_api_response(updated_config),
    )

    with caplog.at_level(logging.WARNING):
        client.fetch_stats()

    assert "configuration was modified while stats were being fetched" in caplog.text


def test_fetch_stats_should_warn_if_using_http(
    valid_dhcp4, response_queue, caplog
):
    """
    A warning should be logged when the scheme is HTTP since config responses
    from the Kea API may contain sensitive data such as passwords in plaintext.
    """
    config, statistics, _ = valid_dhcp4
    client = Client(ENDPOINT_IDENTIFIER, "http://example.org/")
    response_queue.autofill("dhcp4", config=config, statistics=statistics)

    with caplog.at_level(logging.WARNING):
        client.fetch_stats()

    assert "Using HTTP to request potentially sensitive data such as API passwords" in caplog.text


def test_fetch_stats_should_warn_if_using_http_basic_auth_with_http(
    valid_dhcp4, response_queue, caplog
):
    """
    An extra warning when the scheme is HTTP should be logged when HTTP Basic
    Authentication is being used since this entails passwords being sent in
    plaintext from client to server.
    """
    config, statistics, _ = valid_dhcp4
    client = Client(ENDPOINT_IDENTIFIER, "http://example.org/", http_basic_username="nav", http_basic_password="nav")
    response_queue.autofill("dhcp4", config=config, statistics=statistics)

    with caplog.at_level(logging.WARNING):
        client.fetch_stats()

    assert "Using HTTP Basic Authentication without HTTPS" in caplog.text


def test_fetch_stats_should_error_if_using_client_certificate_with_http(
    valid_dhcp4, response_queue
):
    """
    Client authentication is part of the TLS spec so it doesn't make sense to
    continue if it is configured and the specified scheme is HTTP as we would
    have to either ignore the wish to use HTTP or the wish to use TLS
    certificates or both.
    """
    config, statistics, _ = valid_dhcp4
    client = Client(ENDPOINT_IDENTIFIER, "http://example.org/", client_cert_path="/bar/baz.pem")
    response_queue.autofill("dhcp4", config=config, statistics=statistics)

    with pytest.raises(ConfigurationError):
        client.fetch_stats()


def test_fetch_stats_should_use_http_basic_auth_when_this_is_configured(
        valid_dhcp4, response_queue, monkeypatch
):
    """
    Checks that the requests.Session object used during a call to
    Client.fetch_stats() has HTTP Basic Authentication parameters configured
    throughout the call if HTTP Basic Authentication was configured during
    client init.
    """
    config, statistics, _ = valid_dhcp4
    client = Client(
        ENDPOINT_IDENTIFIER,
        "http://example.org/",
        http_basic_username="bar",
        http_basic_password="baz",
    )
    response_queue.autofill("dhcp4", config=config, statistics=statistics)

    post = Session.post
    check_was_called = False
    def check_auth(self, *args, **kwargs):
        nonlocal check_was_called
        check_was_called = True
        assert self.auth == ("bar", "baz")
        return post(self, *args, **kwargs)

    monkeypatch.setattr(requests.Session, 'post', check_auth)
    client.fetch_stats()

    assert check_was_called


def test_fetch_stats_should_use_client_certificates_when_this_is_configured(
        valid_dhcp4, response_queue, monkeypatch
):
    """
    Checks that the requests.Session object used during a call to
    Client.fetch_stats() has certificate parameters configured throughout the
    call if client TLS certificates was configured during client init.
    """
    config, statistics, _ = valid_dhcp4
    client = Client(
        ENDPOINT_IDENTIFIER,
        "https://example.org/",
        client_cert_path="/bar/baz.pem",
    )
    response_queue.autofill("dhcp4", config=config, statistics=statistics)

    post = Session.post
    check_was_called = False
    def check_cert(self, *args, **kwargs):
        nonlocal check_was_called
        check_was_called = True
        assert self.cert == "/bar/baz.pem"
        return post(self, *args, **kwargs)

    monkeypatch.setattr(requests.Session, 'post', check_cert)
    client.fetch_stats()

    assert check_was_called


@pytest.fixture
def valid_dhcp4():
    config = {
        "Dhcp4": {
            "control-socket": {
                "socket-name": "/run/kea/control_socket_4",
                "socket-type": "unix",
            },
            "hooks-libraries": [],
            "lease-database": {
                "name": "/var/lib/kea/kea-leases4.csv",
                "type": "memfile",
            },
            "shared-networks": [
                {
                    "name": "shared-network-1",
                    "subnet4": [
                        {
                            "id": 3,
                            "pools": [
                                {
                                    "option-data": [],
                                    "pool": "42.0.3.1-42.0.3.10",
                                    "pool-id": 1,
                                    "user-context": {
                                        "name": "oslo-student",
                                    },
                                },
                            ],
                            "subnet": "42.0.3.0/24",
                        },
                        {
                            "id": 4,
                            "option-data": [],
                            "pools": [
                                {
                                    "option-data": [],
                                    "pool": "42.0.4.1-42.0.4.5",
                                    "pool-id": 1,
                                    "user-context": {
                                        "name": "oslo-staff",
                                    },
                                },
                            ],
                            "subnet": "42.0.4.1/24",
                        },
                    ],
                    "valid-lifetime": 4000,
                },
                {
                    "name": "shared-network-2",
                    "subnet4": [
                        {
                            "id": 5,
                            "option-data": [],
                            "pools": [
                                {
                                    "option-data": [],
                                    "pool": "42.0.5.1-42.0.5.5",
                                    "pool-id": 1,
                                },
                            ],
                            "subnet": "42.0.5.0/24",
                        },
                    ],
                    "valid-lifetime": 4000,
                },
            ],
            "subnet4": [
                {
                    "id": 1,
                    "option-data": [],
                    "pools": [
                        {
                            "option-data": [],
                            "pool": "42.0.1.1-42.0.1.10",
                            "pool-id": 1,
                            "user-context": {
                                "name": "bergen-staff",
                            },
                        },
                    ],
                    "subnet": "42.0.1.0/24",
                },
                {
                    "id": 2,
                    "option-data": [],
                    "pools": [
                        {
                            "option-data": [],
                            "pool": "42.0.2.1-42.0.2.10",
                            "pool-id": 1,
                            "user-context": {
                                "name": "bergen-student",
                            },
                        },
                        {
                            "option-data": [],
                            "pool": "42.0.2.32/28",
                            "pool-id": 3,
                            "user-context": {
                                "name": "bergen-student",
                            },
                        },
                        {
                            "option-data": [],
                            "pool": "42.0.2.128/25",
                            "pool-id": 2,
                            "user-context": {
                                "name": "bergen-student",
                            },
                        },
                    ],
                    "subnet": "42.0.2.0/24",
                },
            ],
            "valid-lifetime": 4000,
        },
    }

    statistics = {
        "subnet[1].pool[1].assigned-addresses": [
            [2, "2025-05-30 05:49:49.467993"],
            [0, "2025-05-29 05:49:49.467993"],
            [0, "2025-05-28 05:49:49.467993"],
        ],
        "subnet[1].pool[1].declined-addresses": [
            [1, "2025-05-30 05:49:49.467995"],
            [0, "2025-05-29 05:49:49.467995"],
            [0, "2025-05-28 05:49:49.467995"],
        ],
        "subnet[1].pool[1].total-addresses": [
            [10, "2025-05-30 05:49:49.467930"],
            [8, "2025-05-29 05:49:49.467930"],
        ],
        "subnet[2].pool[1].assigned-addresses": [
            [0, "2025-05-30 05:49:49.468017"],
            [1, "2025-05-29 05:49:49.468017"],
        ],
        "subnet[2].pool[1].declined-addresses": [[1, "2025-05-30 05:49:49.468019"]],
        "subnet[2].pool[1].total-addresses": [[10, "2025-05-30 05:49:49.467941"]],
        "subnet[2].pool[2].assigned-addresses": [[1, "2025-05-30 05:49:49.468033"]],
        "subnet[2].pool[2].declined-addresses": [[0, "2025-05-30 05:49:49.468035"]],
        "subnet[2].pool[2].total-addresses": [[128, "2025-05-30 05:49:49.467949"]],
        "subnet[2].pool[3].assigned-addresses": [
            [0, "2025-05-30 05:49:49.468025"],
            [2, "2025-05-29 05:49:49.468025"],
        ],
        "subnet[2].pool[3].declined-addresses": [
            [0, "2025-05-30 05:49:49.468027"],
            [3, "2025-05-29 05:49:49.468027"],
        ],
        "subnet[2].pool[3].total-addresses": [
            [16, "2025-05-30 05:49:49.467945"],
            [16, "2025-05-29 05:49:49.467945"],
            [16, "2025-05-28 05:49:49.467945"],
        ],
        "subnet[3].pool[1].assigned-addresses": [[0, "2025-05-30 05:49:49.468051"]],
        "subnet[3].pool[1].declined-addresses": [[0, "2025-05-30 05:49:49.468053"]],
        "subnet[3].pool[1].total-addresses": [[10, "2025-05-30 05:49:49.467959"]],
        "subnet[4].pool[1].assigned-addresses": [[0, "2025-05-30 05:49:49.468067"]],
        "subnet[4].pool[1].declined-addresses": [[0, "2025-05-30 05:49:49.468070"]],
        "subnet[4].pool[1].total-addresses": [[5, "2025-05-30 05:49:49.467968"]],
        "subnet[5].pool[1].assigned-addresses": [[0, "2025-05-30 05:49:49.468085"]],
        "subnet[5].pool[1].declined-addresses": [[0, "2025-05-30 05:49:49.468087"]],
        "subnet[5].pool[1].total-addresses": [[5, "2025-05-30 05:49:49.467976"]],
    }



    # Each list in the 'statistics' response from the api (see above dict) is a
    # timeseries for a specific stat type for a specific pool.  The first
    # stat in each list is assumed to be the most recent, and this is the
    # stat we expect to get for each stat type and pool after processing
    # the api response.
    expected_stats = [
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.bergen-staff.42_0_1_1.42_0_1_10.assigned", ("2025-05-30 05:49:49.467993", 2)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.bergen-staff.42_0_1_1.42_0_1_10.declined", ("2025-05-30 05:49:49.467993", 1)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.bergen-staff.42_0_1_1.42_0_1_10.total", ("2025-05-30 05:49:49.467993", 10)),

        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.bergen-student.42_0_2_1.42_0_2_10.assigned", ("2025-05-30 05:49:49.467993", 0)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.bergen-student.42_0_2_1.42_0_2_10.declined", ("2025-05-30 05:49:49.467993", 1)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.bergen-student.42_0_2_1.42_0_2_10.total", ("2025-05-30 05:49:49.467993", 10)),

        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.bergen-student.42_0_2_128.42_0_2_255.assigned", ("2025-05-30 05:49:49.467993", 1)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.bergen-student.42_0_2_128.42_0_2_255.declined", ("2025-05-30 05:49:49.467993", 0)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.bergen-student.42_0_2_128.42_0_2_255.total", ("2025-05-30 05:49:49.467993", 128)),

        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.bergen-student.42_0_2_32.42_0_2_47.assigned", ("2025-05-30 05:49:49.467993", 0)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.bergen-student.42_0_2_32.42_0_2_47.declined", ("2025-05-30 05:49:49.467993", 0)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.bergen-student.42_0_2_32.42_0_2_47.total", ("2025-05-30 05:49:49.467993", 16)),

        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.oslo-student.42_0_3_1.42_0_3_10.assigned", ("2025-05-30 05:49:49.467993", 0)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.oslo-student.42_0_3_1.42_0_3_10.declined", ("2025-05-30 05:49:49.467993", 0)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.oslo-student.42_0_3_1.42_0_3_10.total", ("2025-05-30 05:49:49.467993", 10)),

        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.oslo-staff.42_0_4_1.42_0_4_5.assigned", ("2025-05-30 05:49:49.467993", 0)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.oslo-staff.42_0_4_1.42_0_4_5.declined", ("2025-05-30 05:49:49.467993", 0)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.oslo-staff.42_0_4_1.42_0_4_5.total", ("2025-05-30 05:49:49.467993", 5)),

        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.pool-42_0_5_1-42_0_5_5.42_0_5_1.42_0_5_5.assigned", ("2025-05-30 05:49:49.467993", 0)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.pool-42_0_5_1-42_0_5_5.42_0_5_1.42_0_5_5.declined", ("2025-05-30 05:49:49.467993", 0)),
        (f"nav.dhcp.pool.{ENDPOINT_IDENTIFIER}.pool-42_0_5_1-42_0_5_5.42_0_5_1.42_0_5_5.total", ("2025-05-30 05:49:49.467993", 5)),
    ]

    return config, statistics, expected_stats


def make_api_response(val: dict, status:_KeaStatus=_KeaStatus.SUCCESS):
    """
    Make a Kea API conformant response body whose response value (called
    response 'arguments' in the specification) is given by the dictionary `val`.
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
def response_queue(monkeypatch):
    """
    Any test that include this fixture, will automatically mock
    requests.Session.post() and requests.post(). The fixture returns a
    namespace with three functions:

    response_queue.add(command, text_or_func, attrs=None) --- appends the given
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
    response to be an HTTP 404 error.

    response_queue.clear() --- Empty the fifo queues of all commands. This
    removes all previously configured command responses.

    response_queue.autofill(service, config, statistics) --- fill the queue for
    the "config-get" and "statistic-get" commands to mimic the response texts
    actually sent by a Kea Control Agent for a Kea DHCP server named `service`
    ("dhcp4" for ipv4 DHCP "dhcp6" for ipv6 DHCP) with config `config` and
    statistics `statistics`.

    The returned namespace contains a dictionary in addition to the three above
    functions:

    response_queue.responses --- dictionary mapping Kea API command names
    to a list of ordered pairs (<request-arguments>, <request-service>),
    one pair per request for that API command recorded so far.
    """
    command_requests: dict[str, list[tuple[dict, list]]] = {}
    command_responses: dict[
        str, deque[tuple[str | Callable[[dict, list], str], dict]]
    ] = {}
    unknown_command_response = """[
  {{
    "result": 2,
    "text": "'{0}' command not supported."
  }}
]"""

    def post_function_mock(url, *args, data="{}", **kwargs):
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
            raise

        kea_arguments = data.get("arguments", {})
        kea_service = data.get("service", [])

        command_requests.setdefault(command, [])
        command_requests[command].append((kea_arguments, kea_service))

        response_text = unknown_command_response.format(command)
        attrs = {}
        fifo = command_responses.get(command, deque())
        if fifo:
            text_or_func, attrs = fifo[0]
            if callable(text_or_func):
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

    def post_method_mock(self, url, *args, **kwargs):
        """This function will replace requests.Session.post()"""
        return post_function_mock(url, *args, **kwargs)

    def add_command_response(command_name, text_or_func, attrs=None):
        attrs = attrs or {}
        command_responses.setdefault(command_name, deque())
        command_responses[command_name].append((text_or_func, attrs))

    def clear_command_responses():
        command_responses.clear()

    def autofill_command_responses(
        expected_service, config=None, statistics=None, attrs=None
    ):
        attrs = attrs or {}

        if config is not None:
            def config_response(arguments, service):
                assert service == [
                    expected_service
                ], f"API Client for service '{expected_service}' should not send requests to service '{service}'"
                return make_api_response(config)

            add_command_response("config-get", config_response, attrs)

        if statistics is not None:
            def statistic_response(arguments, service):
                assert service == [
                    expected_service
                ], f"API Client for service '{expected_service}' should not send requests to service '{service}'"
                return make_api_response({arguments["name"]: statistics[arguments["name"]]})

            add_command_response("statistic-get", statistic_response, attrs)

    class ResponseQueue:
        add = add_command_response
        clear = clear_command_responses
        autofill = autofill_command_responses
        requests = command_requests

    monkeypatch.setattr(requests, 'post', post_function_mock)
    monkeypatch.setattr(requests.Session, 'post', post_method_mock)

    return ResponseQueue
