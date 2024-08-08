from nav.dhcp.kea_metrics import KeaDhcpMetricSource, KeaException
from nav.bootstrap import bootstrap_django
bootstrap_django(__file__)
from time import time
from functools import wraps
from itertools import chain
from nav.models.manage import Netbox, ManagementProfile
from nav.logs import init_generic_logging

import logging


LOGFILE = "navdhcp.log"
_logger = logging.getLogger("nav.navdhcp")

def timed(f): #TODO: make this a nav.utils decorator?
    """Decorator to time execution of functions"""

    @wraps(f)
    def wrapper(*args, **kwargs):
        """Decorator"""
        start = time()
        result = f(*args, **kwargs)
        elapsed = time() - start
        allargs = chain(
            (repr(arg) for arg in args),
            (f"{key}={value!r}" for key, value in kwargs),
        )
        prettyargs = ", ".join(allargs)
        _logger.info(
            "%s(%s) took %f seconds to finish",
            f.__name__,
            prettyargs,
            elapsed,
        )
        return result

    return wrapper


@timed
def main():
    """Main program"""
    init_generic_logging(logfile=LOGFILE, stderr=True)

    boxes = Netbox.objects.filter(
        profiles__protocol=ManagementProfile.PROTOCOL_HTTP_REST,
    )
    for box in boxes:
        for profile in box.profiles.filter(protocol=ManagementProfile.PROTOCOL_HTTP_REST):
            fetch_metrics(box, profile)


@timed
def fetch_metrics(netbox, profile):
    address = netbox.ip
    port = profile.configuration["tcp_port"]
    use_https = profile.configuration["https"]
    source = KeaDhcpMetricSource(address, port, https=use_https, timeout=3)
    try:
        source.fetch_metrics_to_graphite()
    except KeaException as err:
        _logger.warning(err)
    except Exception as err:
        _logger.error(
            "An unexpected error occurred while fetching dhcp metrics from %s:%s\n%s",
            address,
            port,
            err,
        )

if __name__ == '__main__':
    main()
