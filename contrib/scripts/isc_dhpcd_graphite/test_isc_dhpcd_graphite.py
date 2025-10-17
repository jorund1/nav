import json
import time

import pytest

from .isc_dhpcd_graphite import get_graphite_metrics, Metric
from nav.metrics.templates import metric_path_for_dhcp

@pytest.mark.parametrize(
    "dhcpd_pools_output,expected_metrics",
    [
        (
            """
            {
               "subnets": [
                     { "location":"example1", "range":"10.0.0.1 - 10.0.0.20", "defined":20, "used":11, "touched":0, "free":9 },
                     { "location":"example1", "range":"10.1.0.1 - 10.1.0.20", "defined":20, "used":10, "touched":0, "free":10 },
                     { "location":"example2", "range":"10.2.0.1 - 10.2.0.20", "defined":20, "used":8, "touched":0, "free":12 },
                     { "location":"example2", "range":"10.3.0.1 - 10.3.0.20", "defined":20, "used":9, "touched":0, "free":11 },
                     { "location":"All networks", "range":"10.4.0.1 - 10.4.0.20", "defined":20, "used":5, "touched":0, "free":15 }
               ],
               "shared-networks": [
                     { "location":"example1", "defined":40, "used":21, "touched":0, "free":19 },
                     { "location":"example2", "defined":40, "used":17, "touched":0, "free":23 }
               ],
               "summary": {
                     "location":"All networks",
                     "defined":100,
                     "used":43,
                     "touched":0,
                     "free":57
               }
            }
            """,
            [
                Metric(metric_path_for_dhcp(metric_name="total",    ip_version=4, allocation_type="range", group_name="example1", group_name_source="custom_groups", server_name="server1", first_ip="10.0.0.1", last_ip="10.0.0.20"), 20, 0.0),
                Metric(metric_path_for_dhcp(metric_name="assigned", ip_version=4, allocation_type="range", group_name="example1", group_name_source="custom_groups", server_name="server1", first_ip="10.0.0.1", last_ip="10.0.0.20"), 11, 0.0),
                Metric(metric_path_for_dhcp(metric_name="declined", ip_version=4, allocation_type="range", group_name="example1", group_name_source="custom_groups", server_name="server1", first_ip="10.0.0.1", last_ip="10.0.0.20"), 0, 0.0),
                Metric(metric_path_for_dhcp(metric_name="total",    ip_version=4, allocation_type="range", group_name="example1", group_name_source="custom_groups", server_name="server1", first_ip="10.1.0.1", last_ip="10.1.0.20"), 20, 0.0),
                Metric(metric_path_for_dhcp(metric_name="assigned", ip_version=4, allocation_type="range", group_name="example1", group_name_source="custom_groups", server_name="server1", first_ip="10.1.0.1", last_ip="10.1.0.20"), 10, 0.0),
                Metric(metric_path_for_dhcp(metric_name="declined", ip_version=4, allocation_type="range", group_name="example1", group_name_source="custom_groups", server_name="server1", first_ip="10.1.0.1", last_ip="10.1.0.20"), 0, 0.0),
                Metric(metric_path_for_dhcp(metric_name="total",    ip_version=4, allocation_type="range", group_name="example2", group_name_source="custom_groups", server_name="server1", first_ip="10.2.0.1", last_ip="10.2.0.20"), 20, 0.0),
                Metric(metric_path_for_dhcp(metric_name="assigned", ip_version=4, allocation_type="range", group_name="example2", group_name_source="custom_groups", server_name="server1", first_ip="10.2.0.1", last_ip="10.2.0.20"), 8, 0.0),
                Metric(metric_path_for_dhcp(metric_name="declined", ip_version=4, allocation_type="range", group_name="example2", group_name_source="custom_groups", server_name="server1", first_ip="10.2.0.1", last_ip="10.2.0.20"), 0, 0.0),
                Metric(metric_path_for_dhcp(metric_name="total",    ip_version=4, allocation_type="range", group_name="example2", group_name_source="custom_groups", server_name="server1", first_ip="10.3.0.1", last_ip="10.3.0.20"), 20, 0.0),
                Metric(metric_path_for_dhcp(metric_name="assigned", ip_version=4, allocation_type="range", group_name="example2", group_name_source="custom_groups", server_name="server1", first_ip="10.3.0.1", last_ip="10.3.0.20"), 9, 0.0),
                Metric(metric_path_for_dhcp(metric_name="declined", ip_version=4, allocation_type="range", group_name="example2", group_name_source="custom_groups", server_name="server1", first_ip="10.3.0.1", last_ip="10.3.0.20"), 0, 0.0),
                Metric(metric_path_for_dhcp(metric_name="total",    ip_version=4, allocation_type="range", group_name="standalone", group_name_source="special_groups", server_name="server1", first_ip="10.4.0.1", last_ip="10.4.0.20"), 20, 0.0),
                Metric(metric_path_for_dhcp(metric_name="assigned", ip_version=4, allocation_type="range", group_name="standalone", group_name_source="special_groups", server_name="server1", first_ip="10.4.0.1", last_ip="10.4.0.20"), 5, 0.0),
                Metric(metric_path_for_dhcp(metric_name="declined", ip_version=4, allocation_type="range", group_name="standalone", group_name_source="special_groups", server_name="server1", first_ip="10.4.0.1", last_ip="10.4.0.20"), 0, 0.0),
            ],
        ),
        (
            # We don't care about IPv6, so an empty list of returned metrics is expected here
            """
            {
               "subnets": [
                     { "location":"example1", "range":"2001:0db8:0000:0000:0000:0000:0000:0001 - 2001:0db8:0000:0000:0000:0000:0000:00ff", "defined":255, "used":11, "touched":0, "free":244 }
               ],
               "shared-networks": [
                     { "location":"example1", "defined":255, "used":11, "touched":0, "free":244 }
               ]
            }
            """,
            [],
        ),
    ]
)
class TestGetGraphiteMetrics:
    def test_get_graphite_metrics_should_correctly_parse_dhcpd_json_into_graphite_metrics(
            self,
            dhcpd_pools_output,
            expected_metrics,
    ):
        """
        Importantly, this test makes sure that the DHCP stats paths used by this
        contrib scripts match the DHCP stats paths used by NAV (through calls to
        nav.metrics.templates::metric_path_for_dhcp), since the contrib script
        re-implements nav.metrics.templates::metric_path_for_dhcp
        """

        def normalize(metrics):
            """
            Set stat timestamps to zero, because we do not care to compare the time
            """
            return [(path, value, 0) for (path, value, _timestamp) in metrics]

        dhcpd_json = json.loads(dhcpd_pools_output)
        class cli_args:
            prefix = "nav"
            server_name = "server1"
        actual_metrics = get_graphite_metrics(dhcpd_json, cli_args)
        assert sorted(normalize(actual_metrics)) == sorted(expected_metrics)

    def test_get_graphite_metrics_should_return_graphite_metrics_with_current_timestamp(
            self,
            dhcpd_pools_output,
            expected_metrics,
    ):
        dhcpd_json = json.loads(dhcpd_pools_output)
        current_timestamp = int(time.time())
        class cli_args:
            prefix = "nav"
            server_name = "server1"
        actual_metrics = get_graphite_metrics(dhcpd_json, cli_args)
        for (_path, _value, timestamp) in actual_metrics:
            assert current_timestamp <= timestamp <= current_timestamp + 5
