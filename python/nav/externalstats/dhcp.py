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
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.  You should have received a copy of the GNU General Public
# License along with NAV. If not, see <http://www.gnu.org/licenses/>.
#
"""Defines base types used by externalstats"""

from dataclasses import dataclass

from IPy import IP


GraphiteMetric = tuple[str, tuple[int, int]]


@dataclass(order=True, frozen=True, kw_only=True)
class Pool:
    """Base class for DHCP address pools"""
    name: str
    range_start: IP
    range_end: IP
