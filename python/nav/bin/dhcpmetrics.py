#!/usr/bin/env python
import argparse
import logging
from nav.config import getconfig
from nav.dhcp import kea_metrics
from nav.logs import init_generic_logging
from nav.metrics import carbon
from nav.metrics.templates import metric_path_for_subnet_dhcp

CLIENT = {"Kea Management API": kea_metrics.Client}


_logger = logging.getLogger("nav.dhcpmetrics")

LOGFILE = "dhcpmetrics.log"
CONFIGFILE = "dhcpmetrics.conf"


def main():
    """
    Collects current DHCP metrics from each DHCP server configured in
    'CONFDIR/dhcpmetrics.log' and sends them to graphite
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
    Collects current DHCP metrics from each configured DHCP server

    :param config: parsed INI configuration of DHCP servers to collect metrics
    from.

    :param args: parsed sys.argv arguments

    Example INI configuration:
      [https://dhcp-api.example.com:8080/]
      dhcp_version=4
      service=Kea Management API

      [http://192.0.2.2/]
      dhcp_version=4
      timeout=40
      service=Kea Management API
    """
    api_clients = []

    _logger.info('--> Starting metric collection <--')

    for uri, options in config.items():
        timeout = options.get("timeout", 10)
        dhcp_version = int(options.get("dhcp_version", "4"))
        service = options.get("service")
        api_client = CLIENT[service](uri, dhcp_version=dhcp_version, timeout=timeout)
        api_clients.append(api_client)

    metrics = []
    for client in api_clients:
        try:
            for metric in client.fetch_metrics():
                metric_path = metric_path_for_subnet_dhcp(
                    metric.subnet_prefix, metric.name
                )
                print(metric_path)
                datapoint = (metric.timestamp + args.timeoffset, metric.value)
                metrics.append((metric_path, datapoint))
        except kea_metrics.KeaException as err:
            _logger.error(str(err))

    carbon.send_metrics(metrics)

    _logger.info('--> Metric collection done <--')


if __name__ == '__main__':
    main()
