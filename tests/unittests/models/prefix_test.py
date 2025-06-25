from unittest.mock import patch

from IPy import IP
import pytest

from nav.models.manage import Prefix


class TestGetGraphiteDhcpPools:
    def test(self, prefix):
        pool_paths = {
            "results": [
                "nav.dhcp.4.pool.server_1.pool_1.1_1_252_0.1_1_252_12",  # Inside
                "nav.dhcp.4.pool.server_1.pool_1.1_1_252_64.1_1_252_127",  # Inside
                "nav.dhcp.4.pool.server_1.pool_2.1_1_253_1.1_1_253_8",  # Inside
                "nav.dhcp.4.pool.server_1.pool_2.1_1_254_0.1_1_254_15",  # Sibling inside
                "nav.dhcp.4.pool.server_1.pool_2.1_1_100_0.1_1_101_0",  # Sibling inside
                "nav.dhcp.4.pool.server_1.pool_3.1_1_100_0.1_1_101_0",  # Outside
                "nav.dhcp.4.pool.server_2.pool_1.1_1_100_0.1_1_101_0",  # Outside
                "nav.dhcp.4.pool.server_2.pool_2.1_1_254_0.1_1_254_15",  # Outside
                "nav.dhcp.4.pool.server_2.pool_3.1_1_253_1.1_1_253_8",  # Inside
                "nav.dhcp.4.pool.server_3.pool_1.1_1_250_1.1_1_255_1",  # Partially Inside
                "nav.dhcp.4.pool.server_4.pool_1.1_1_253_1.1_1_255_1",  # Partially Inside
                "nav.dhcp.4.pool.server_5.pool_1.1_1_250_1.1_1_253_1",  # Partially Inside
            ]
        }

        expected_result = {
            ("server_1", "pool_1"): [
                (IP("1.1.252.0"), IP("1.1.252.12")),
                (IP("1.1.252.64"), IP("1.1.252.127")),
            ],
            ("server_1", "pool_2"): [
                (IP("1.1.253.1"), IP("1.1.253.8")),
                (IP("1.1.254.0"), IP("1.1.254.15")),
                (IP("1.1.100.0"), IP("1.1.101.0")),
            ],
            # ("server_1", "pool_3") is outside
            # ("server_2", "pool_1") is outside
            # ("server_2", "pool_2") is outside
            ("server_2", "pool_3"): [(IP("1.1.253.1"), IP("1.1.253.8"))],
            ("server_3", "pool_1"): [(IP("1.1.250.1"), IP("1.1.255.1"))],
            ("server_4", "pool_1"): [(IP("1.1.253.1"), IP("1.1.255.1"))],
            ("server_5", "pool_1"): [(IP("1.1.250.1"), IP("1.1.253.1"))],
        }

        with patch("nav.models.manage.raw_metric_query", return_value=pool_paths):
            assert prefix.get_graphite_dhcp_pools() == expected_result


@pytest.fixture
def prefix():
    prefix = Prefix(net_address="1.1.252.0/23")
    yield prefix
