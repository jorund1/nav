#
# Copyright (C) 2025 Sikt
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
"""
Common classes and functions used by DHCP API clients and various other parts of
NAV that wants to make use of DHCP stats.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Optional, Union

import IPy

from nav.metrics.graphs import (
    aliased_series,
    diffed_series,
    json_graph_url,
    nonempty_series,
    summed_series,
)
from nav.metrics.names import get_expanded_nodes, safe_name
from nav.metrics.templates import metric_path_for_dhcp


# Type expected by functions in NAV that send stats to a Graphite/Carbon backend. Values
# of this type are interpreted as (path, (timestamp, value)).
GraphiteMetric = tuple[str, tuple[float, int]]


def fetch_graph_urls_for_prefixes(prefixes: list[IPy.IP]):
    if not prefixes:
        return []

    all_paths = fetch_paths_from_graphite()
    grouped_paths = group_paths(all_paths)
    filtered_grouped_paths = drop_groups_not_in_prefixes(grouped_paths, prefixes)

    graph_urls = []
    for paths_of_same_group in filtered_grouped_paths:
        paths_of_same_group = sorted(paths_of_same_group)
        graph_lines = []
        for path in paths_of_same_group:
            assigned_addresses = aliased_series(
                nonempty_series(
                    path.to_graphite_path("assigned"),
                ),
                name=f"Assigned to {path.first_ip} - {path.last_ip}",
                renderer="area",
            )
            graph_lines.append(assigned_addresses)

        assert len(paths_of_same_group) > 0
        path = paths_of_same_group[0]  # Just select an arbitrary path instance in the group
        unassigned_addresses = aliased_series(
            diffed_series(
                summed_series(
                    nonempty_series(
                        path.to_graphite_path("total", wildcard_for_group=True)
                    ),
                ),
                summed_series(
                    nonempty_series(
                        path.to_graphite_path("assigned", wildcard_for_group=True)
                    ),
                ),
            ),
            name="Unassigned",
            renderer="area",
            color="#d9d9d9",
        )
        graph_lines.append(unassigned_addresses)

        total_addresses = aliased_series(
            summed_series(
                nonempty_series(
                    path.to_graphite_path("total", wildcard_for_group=True)
                ),
            ),
            name="Total available",
            color="#ff8000",
        )
        graph_lines.append(total_addresses)

        type_human = path.allocation_type + "s"
        title = f"IP Addresses assigned to {type_human} in {path.group_name!r} on DHCP server {path.server_name!r}"
        graph_urls.append(json_graph_url(*graph_lines, title=title))
    return graph_urls


def fetch_paths_from_graphite():
    wildcard = metric_path_for_dhcp(
        ip_version=safe_name("{4,6}"),
        server_name=safe_name("*"),
        allocation_type=safe_name("{range,pool,subnet}"),
        group_name_source=safe_name("{custom_groups,special_groups}"),
        group_name=safe_name("*"),
        first_ip=safe_name("*"),
        last_ip=safe_name("*"),
        metric_name="total",
    )
    graphite_paths = get_expanded_nodes(wildcard)

    native_paths: list[DhcpPath] = []
    for graphite_path in graphite_paths:
        try:
            native_path = DhcpPath.from_graphite_path(graphite_path)
        except ValueError:
            pass
        else:
            native_paths.append(native_path)
    return native_paths


def group_paths(paths: list["DhcpPath"]) -> list[list["DhcpPath"]]:
    grouped_paths: dict[Any, list[DhcpPath]] = defaultdict(list)
    for path in paths:
        group_total = path.to_graphite_path("total", wildcard_for_group=True)
        group_assigned = path.to_graphite_path("assigned", wildcard_for_group=True)
        grouped_paths[(group_total, group_assigned)].append(path)
    return list(grouped_paths.values())


def drop_groups_not_in_prefixes(grouped_paths: list[list["DhcpPath"]], prefixes: list[IPy.IP]):
    grouped_paths_to_keep = []
    for paths_of_same_group in grouped_paths:
        if any(
            path.intersects(prefixes)
            for path in paths_of_same_group
        ):
            grouped_paths_to_keep.append(paths_of_same_group)
    return grouped_paths_to_keep


@dataclass(frozen=True, order=True)
class DhcpPath:
    """
    Represents a path to a DHCP stat in Graphite sans the stat's metric_name.
    Instantiate me via :meth from_external_info: if path info is sourced from an
     external source such as a DHCP server.
    Instantiate me via :meth from_graphite_path: if path info is sourced from
     NAV's Graphite database.
    Use me to translate (with validity checks) between
     info from external source (DHCP server) --> DhcpPath <--> path from Graphite
    """
    ip_version: int
    server_name: str
    allocation_type: Literal["range", "pool", "subnet"]
    group_name: str
    group_name_source: Literal["special_groups", "custom_groups"]
    first_ip: IPy.IP
    last_ip: IPy.IP

    @classmethod
    def from_graphite_path(cls, graphite_path: str):
        """
        Instantiate me from a path to a DHCP stat (either sans metric_name or
        not) from Graphite.

        The following holds, where <path> is a Path instance:
         Path.from_graphite_path(<path>.to_graphite_path(<arg>)) == <path>
        given that <path>.server_name and <path>.group_name are valid as Graphite path segments
        """
        parts = graphite_path.split(".")
        if not len(parts) >= 9:
            raise ValueError(
                f"Expected graphite_path {graphite_path!r} to have at least 9 dot-separated segments"
            )
        ip_version = parts[2]
        server_name = parts[3]
        allocation_type = parts[4]
        group_name_source = parts[5]
        group_name = parts[6]
        first_ip = parts[7]
        last_ip = parts[8]

        allowed_group_sources = ("special_groups", "custom_groups")
        if group_name_source not in allowed_group_sources:
            raise ValueError(f"group_source_name {group_name_source!r} is not in {allowed_group_sources!r}")

        allowed_allocation_types = ("range", "pool", "subnet")
        if allocation_type not in allowed_allocation_types:
            raise ValueError(f"allocation_type {allocation_type!r} is not in {allowed_allocation_types!r}")

        first_ip = cls._unescape_graphite_address(first_ip)
        last_ip = cls._unescape_graphite_address(last_ip)
        cls._check_ip_pair(first_ip, last_ip)

        if str(first_ip.version()) != ip_version or str(last_ip.version()) != ip_version:
            raise ValueError(f"first_ip {first_ip!r} or last_ip {last_ip!r} not of same version as expected ip_version {ip_version!r}")

        return cls(
            ip_version=first_ip.version(),
            server_name=server_name,
            allocation_type=allocation_type,
            group_name_source=group_name_source,
            group_name=group_name,
            first_ip=first_ip,
            last_ip=last_ip,
        )

    @classmethod
    def from_external_info(
            cls,
            server_name: str,
            allocation_type: Literal["range", "pool", "subnet"],
            group_name: Optional[str],
            first_ip: Union[str, IPy.IP],
            last_ip: Union[str, IPy.IP],
    ):
        """
        Instantiate me when group_name, first_ip, and last_ip are
        possibly unsafe and/or missing.

        if first_ip cannot be parsed to an IP address, raises a ValueError
        if last_ip cannot be parsed to an IP address, raises a ValueError
        if first_ip > last_ip, raises a ValueError
        otherwise, returns the Path instance.
        """
        if group_name is None:
            group_name_source = "special_groups"
            group_name = "standalone"
        else:
            group_name_source = "custom_groups"
            group_name = group_name

        first_ip = IPy.IP(IPy.IP(first_ip)[0])
        last_ip = IPy.IP(IPy.IP(last_ip)[-1])
        cls._check_ip_pair(first_ip, last_ip)

        return cls(
            ip_version=first_ip.version(),
            server_name=server_name,
            allocation_type=allocation_type,
            group_name_source=group_name_source,
            group_name=group_name,
            first_ip=first_ip,
            last_ip=last_ip,
        )

    def to_graphite_path(self, metric_name, wildcard_for_group=False):
        """
        Return me as a path recognized by Graphite.
        """
        if wildcard_for_group and not self._is_standalone():
            first_ip = safe_name("*")
            last_ip = safe_name("*")
        else:
            first_ip = self.first_ip.strNormal()
            last_ip = self.last_ip.strNormal()

        return metric_path_for_dhcp(
            ip_version=self.ip_version,
            server_name=self.server_name,
            allocation_type=self.allocation_type,
            group_name_source=self.group_name_source,
            group_name=self.group_name,
            first_ip=first_ip,
            last_ip=last_ip,
            metric_name=metric_name,
        )

    def intersects(self, prefixes: Iterable[IPy.IP]):
        for prefix in prefixes:
            if (
                self.first_ip in prefix
                or self.last_ip in prefix
                or self.first_ip < prefix < self.last_ip
            ):
                return True
        return False

    @staticmethod
    def _unescape_graphite_address(escaped_address: str) -> IPy.IP:
        parts = escaped_address.split("_")
        if len(parts) == 4:
            return IPy.IP(".".join(parts))
        elif len(parts) == 8:
            return IPy.IP(":".join(parts))
        else:
            raise ValueError

    @staticmethod
    def _check_ip_pair(first_ip: IPy.IP, last_ip: IPy.IP):
        if first_ip.version() != last_ip.version():
            raise ValueError(f"first_ip {first_ip!r} is not of same version as last_ip {last_ip!r}")

        if first_ip > last_ip:
            raise ValueError(f"first_ip {first_ip!r} greater than last_ip {last_ip!r}")

    def _is_standalone(self):
        return self.group_name_source == "special_groups" and self.group_name == "standalone"
