#!/usr/bin/env python
import logging
from nav.config import getconfig
from nav.dhcp.kea_metrics import Client, KeaException
from nav.logs import init_generic_logging
from nav.metrics import carbon
from nav.metrics.templates import metric_path_for_subnet_dhcp


_logger = logging.getLogger("nav.dhcpmetrics")

LOGFILE = "keadhcp.log"
CONFIGFILE = "keadhcp.conf"


def main():
    init_generic_logging(logfile=LOGFILE)
    config = getconfig(CONFIGFILE)
    collect_metrics(config)


def collect_metrics(config):
    api_clients = []

    _logger.info('--> Starting metric collection <--')

    for uri, options in config.items():
        timeout = options.get("timeout", 10)
        dhcp_version = int(options.get("dhcp_version", "4"))
        api_client = Client(uri, dhcp_version=dhcp_version, timeout=timeout)
        api_clients.append(api_client)

    # TODO: use parallel threads
    graphite_metrics = []
    for client in api_clients:
        try:
            for metric in client.fetch_metrics():
                metric_path = metric_path_for_subnet_dhcp(
                    metric.subnet_prefix, metric.name
                )
                datapoint = (metric.timestamp, metric.value)
                graphite_metrics.append((metric_path, datapoint))
        except KeaException as err:
            _logger.error(str(err))

    carbon.send_metrics(graphite_metrics)

    _logger.info('--> Metric collection done <--')
