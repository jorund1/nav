from nav.config import getconfig
from nav.metrics import carbon, CONFIG
from nav.metrics.templates import metric_path_for_subnet_dhcp
from nav.dhcp.kea_metrics import Client


configfile = ('keadhcp.conf',)

def main():
    config = getconfig(configfile)
    api_clients = []
    for uri, opts in config.items():
        timeout = opts.get("timeout", 10)
        dhcp_version = opts.get("dhcp_version", 4)
        client = Client(uri, dhcp_version=dhcp_version, timeout=timeout)
        api_clients.append(client)
    #TODO: use parallel threads
    graphite_metrics = []
    for client in api_clients:
        for metric in client.fetch_metrics():
            metric_path = metric_path_for_subnet_dhcp(
                metric.subnet_prefix, metric.name
            )
            datapoint = (metric.timestamp, metric.value)
            graphite_metrics.append((metric_path, datapoint))

    host = CONFIG.get("carbon", "host")
    port = CONFIG.getint("carbon", "port")
    carbon.send_metrics_to(graphite_metrics, host, port)
