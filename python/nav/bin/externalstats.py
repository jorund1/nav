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
"""
Collects statistics from endpoints not expected to be part of the network
managed by NAV
"""

import argparse
import logging
from functools import partial

from nav.config import getconfig
from nav.externalstats import kea_dhcp
from nav.externalstats.errors import CommunicationError, ConfigurationError
from nav.logs import init_generic_logging
from nav.metrics import carbon

_logger = logging.getLogger("nav.externalstats")
LOGFILE = "externalstats.log"
CONFIGFILE = "externalstats.conf"

ENDPOINT_CLIENTS = {
    "kea-dhcp4": partial(kea_dhcp.Client, dhcp_version=4),
}


def main():
    """Start collecting statistics"""
    init_generic_logging(logfile=LOGFILE)
    config = getconfig(CONFIGFILE)
    parse_args()
    collect_stats(config)


def parse_args():
    """Builds an ArgumentParser and returns parsed program arguments"""
    # Parse arguments mainly to support the --help option
    parser = argparse.ArgumentParser(
        description="Collects statistics from endpoints not expected to be part of the "
        "network managed by NAV",
        epilog="Statistics are collected from each endpoint configured in "
        "'CONFDIR/externalstats.conf', and then sent to the carbon backend configured in "
        "'CONFDIR/graphite.conf'.",
    )
    return parser.parse_args()


def collect_stats(config):
    """
    Collects current stats from each configured endpoint

    :param config: parsed INI configuration of endpoints to collect metrics
    from
    """

    _logger.info("--> Starting stats collection <--")

    all_stats = []

    for client in get_endpoint_clients(config):
        _logger.info(
            "Collecting stats using %s...",
            client,
        )

        try:
            client_stats = client.fetch_stats()
        except ConfigurationError as err:
            _logger.warning(
                "%s is badly configured, skipping endpoint...",
                client,
            )
        except CommunicationError as err:
            _logger.warning(
                "Error while collecting stats using %s: %s, skipping endpoint...",
                client,
                err,
            )
        except Exception as err:
            _logger.warning(
                "Unexpected error while collecting stats using %s, skipping endpoint...",
                client,
                exc_info=err,
            )
        else:
            all_stats.extend(client_stats)
            _logger.info(
                "Successfully collected stats using %s",
                client,
            )

    carbon.send_metrics(all_stats)

    _logger.info("--> Stats collection done <--")


def get_endpoint_clients(config):
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

        yield cls(endpoint_name, **kwargs)



if __name__ == "__main__":
    main()
