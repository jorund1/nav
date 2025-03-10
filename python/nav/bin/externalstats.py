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
from dataclasses import replace

from nav.config import getconfig
from nav.externalstats import kea_dhcp
from nav.logs import init_generic_logging
from nav.metrics import carbon

_logger = logging.getLogger("nav.externalstats")
LOGFILE = "externalstats.log"
CONFIGFILE = "externalstats.conf"

FETCHERS = {
    "kea-dhcp4": partial(kea_dhcp.Client, dhcp_version=4),
}

def main():
    """
    Collects current metrics from each endpoint configured in
    'CONFDIR/externalstats.log' and sends them to graphite
    """
    args = parse_args()
    init_generic_logging(logfile=LOGFILE)
    config = getconfig(CONFIGFILE)
    collect_metrics(config, args)


def parse_args():
    """Builds an ArgumentParser and returns parsed program arguments"""
    parser = argparse.ArgumentParser(description=main.__doc__.strip())
    parser.add_argument(
        "--timeoffset",
        default=0,
        type=float,
        help="Time in seconds the timestamps of collected metrics should be offset from current time",
    )
    return parser.parse_args()


def collect_metrics(config, args):
    """
    Collects current metrics from each configured endpoint

    :param config: parsed INI configuration of endpoints to collect metrics
    from

    :param args: parsed sys.argv arguments
    """

    _logger.info("--> Starting metric collection <--")

    fetchers = []
    for name, options in config.items():
        if not name.startswith("endpoint_"):
            continue
        type = options.get("type")
        kwargs = {opt: val for opt, val in options.items() if opt != "type"}
        cls = FETCHERS[type]
        fetchers.append(cls(**kwargs))

    metrics = []
    for fetcher in fetchers:
        metrics.extend(
            replace(m, timestamp=m.timestamp+args.timeoffset) for m in fetcher.fetch_metrics()
        )


    carbon.send_metrics(metrics)

    _logger.info("--> Metric collection done <--")


if __name__ == "__main__":
    main()
