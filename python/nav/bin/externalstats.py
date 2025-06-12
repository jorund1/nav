#!/usr/bin/env python
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

import argparse
import logging
from functools import partial

from nav.config import getconfig
from nav.externalstats import kea_dhcp
from nav.logs import init_generic_logging
from nav.metrics import carbon

_logger = logging.getLogger("nav.externalstats")
LOGFILE = "externalstats.log"
CONFIGFILE = "externalstats.conf"

ENDPOINT_CLIENTS = {
    "kea-dhcp4": partial(kea_dhcp.Client, dhcp_version=4),
}


def main():
    """
    Collects current metrics from each endpoint configured in
    'CONFDIR/externalstats.log' and sends them to graphite
    """
    init_generic_logging(logfile=LOGFILE)
    config = getconfig(CONFIGFILE)
    parse_args()
    collect_metrics(config)


def parse_args():
    """Builds an ArgumentParser and returns parsed program arguments"""
    # Include this mainly for --help option
    description = (main.__doc__ or "").strip()
    parser = argparse.ArgumentParser(description=description)
    return parser.parse_args()


def collect_metrics(config):
    """
    Collects current metrics from each configured endpoint

    :param config: parsed INI configuration of endpoints to collect metrics
    from
    """

    _logger.info("--> Starting metric collection <--")

    # TODO: Multithread
    stats = []
    for section, options in config.items():
        if not section.startswith("endpoint_"):
            continue
        endpoint_name = section.removeprefix("endpoint_")
        endpoint_type = options.get("type")
        kwargs = {opt: val for opt, val in options.items() if opt != "type"}
        try:
            cls = ENDPOINT_CLIENTS[endpoint_type]
        except KeyError:
            _logger.warning(
                "Invalid endpoint type '%s' defined in config section [%s], skipping...",
                endpoint_type,
                section,
            )
            continue
        _logger.info(
            "Collecting stats from endpoint '%s' of type '%s'",
            endpoint_name,
            endpoint_type
        )
        client = cls(endpoint_name, **kwargs)
        stats.extend(client.fetch_stats())

    carbon.send_metrics(stats)

    _logger.info("--> Metric collection done <--")


if __name__ == "__main__":
    main()
