#
# Copyright (C) 2024 Sikt
#
# This file is part of Network Administration Visualized (NAV).
#
# NAV is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 3 as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.  You should have received a copy of the GNU General Public License
# along with NAV. If not, see <http://www.gnu.org/licenses/>.
#


# TODO: rename from DhcpMetricSource to DhcpCollector


"""
This module contains types and interfaces for classes that wish to collect
metrics from a DHCP server and have the metrics imported into NAV's graphite
database in a conformant way.

Each collected metric should be an instance of `DhcpMetric`. `DhcpMetricKey`
specifies what kind of metric it is and is used along with `subnet_prefix` to
construct the graphite data path where that metric's timeseries should be
located.

Some metric types specified in `DhcpMetricKey` are more general than others; an
implementation is free to choose which metric types to support.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterator

from IPy import IP

from nav.metrics import carbon, CONFIG
from nav.metrics.templates import metric_path_for_subnet_dhcp


class DhcpMetricKey(Enum):
    """
    Specifies what kind of value a DHCP metric represents.

    TOTAL:     value is the maximum possible amount of active leases in the
               subnet

    ASSIGNED:  value is the current amount of active leases in the subnet

    DECLINED:  value is the amount of DHCP-maintained addresses in use by an
               entity unknown to the server and thus not available for
               assignment. (Should ideally always be zero)

    For more detailed info on DECLINED, see e.g.
    https://kea.readthedocs.io/en/kea-2.2.0/arm/dhcp6-srv.html#duplicate-addresses-dhcpdecline-support
    """

    TOTAL = "total"
    ASSIGNED = "assigned"
    DECLINED = "declined"

    def __str__(self):
        return self.value  # how key is represented in graphite paths


@dataclass(frozen=True)
class DhcpMetric:
    timestamp: float
    subnet_prefix: IP
    key: DhcpMetricKey
    value: int


class DhcpMetricSource:
    """
    Superclass for all classes that wish to collect metrics from a
    specific line of DHCP servers and import the metrics into NAV's
    graphite server. Subclasses need to implement `fetch_metrics`.
    """

    def fetch_metrics(self) -> list[DhcpMetric]:
        """
        Fetch DhcpMetrics having keys `TOTAL` and `ASSIGNED` for each subnet of the
        DHCP server at current point of time.
        """
        raise NotImplementedError

    def fetch_metrics_to_graphite(self, host=None, port=None):
        """
        Fetch metrics describing total amount of addresses
        (DhcpMetricKey.TOTAL) and amount of addresses that have been
        assigned to a client (DhcpMetricKey.ASSIGNED) for each subnet
        of the DHCP server at current point of time and send the
        metrics to the graphite server at `host` on `port`.
        """
        host = host or CONFIG.get("carbon", "host")
        port = port or CONFIG.getint("carbon", "port")

        graphite_metrics = []
        for metric in self.fetch_metrics():
            metric_path = metric_path_for_subnet_dhcp(
                metric.subnet_prefix, str(metric.key)
            )
            datapoint = (metric.timestamp, metric.value)
            graphite_metrics.append((metric_path, datapoint))
        carbon.send_metrics_to(graphite_metrics, host, port)
