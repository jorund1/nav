#!/usr/bin/env python
import logging
from nav.config import getconfig
from nav.dhcp.kea_metrics import Client, KeaException
from nav.logs import init_generic_logging
from nav.metrics import carbon
from nav.metrics.templates import metric_path_for_subnet_dhcp


_logger = logging.getLogger("nav.dhcpmetrics")

LOGFILE = "dhcpmetrics.log"
CONFIGFILE = "dhcpmetrics.conf"


def main():
    init_generic_logging(logfile=LOGFILE)
    args = parse_args()
    config = getconfig(CONFIGFILE)
    collect_metrics(config, args)

def parse_args():
    """Builds an ArgumentParser and returns parsed program arguments"""
    parser = argparse.ArgumentParser(
        description="Collects DHCP metrics from servers specified in dhcpmetrics.conf",
    )
    parser.add_argument(
        "--timeoffset",
        default=0,
        type=float,
        help="How many seconds the timestamps in collected metrics should be offset by",
    )
    return parser.parse_args()


def collect_metrics(config, args):
    api_clients = []

    _logger.info('--> Starting metric collection <--')

    for uri, options in config.items():
        timeout = options.get("timeout", 10)
        dhcp_version = int(options.get("dhcp_version", "4"))
        api_client = Client(uri, dhcp_version=dhcp_version, timeout=timeout)
        api_clients.append(api_client)

    metrics = []
    for client in api_clients:
        try:
            for metric in client.fetch_metrics():
                metric_path = metric_path_for_subnet_dhcp(
                    metric.subnet_prefix, metric.name
                )
                print(metric_path)
                datapoint = (metric.timestamp+args.timeoffset, metric.value)
                metrics.append((metric_path, datapoint))
        except KeaException as err:
            _logger.error(str(err))

    carbon.send_metrics(metrics)

    _logger.info('--> Metric collection done <--')


if __name__ == '__main__':
    main()
