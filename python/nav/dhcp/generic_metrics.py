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

from dataclasses import dataclass
from typing import Literal, ClassVar
from IPy import IP

from nav.metrics import carbon, CONFIG
from nav.metrics.templates import metric_path_for_subnet_dhcp

class DhcpMetricSource:
    """
    Superclass for all classes that wish to collect metrics from a
    specific line of DHCP servers and import the metrics into NAV's
    graphite server. Subclasses need to implement `fetch_metrics`.
    """

    def fetch_metrics(self) -> list[Metric]:
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
            # metric_path = metric_path_for_subnet_dhcp(
            #     metric.subnet_prefix, metric.type.value
            # )
            # datapoint = (metric.timestamp, metric.value)
            # graphite_metrics.append((metric_path, datapoint))
        carbon.send_metrics_to(graphite_metrics, host, port)
