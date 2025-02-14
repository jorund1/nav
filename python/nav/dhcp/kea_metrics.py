#
# Copyright (C) 2024 Sikt
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
This module contains the KeaDhcpMetricSource class, used for fetching DHCP
metrics from Kea DHCP servers

                            |
             Managed by NAV | Managed externally
                            |
                       HTTP |                       IPC
KeaDhcpMetricSource <---------> Kea Control Agent <=====> Kea DHCP4 server/Kea DHCP6 server
                            |
                            |
"""

from dataclasses import dataclass
from datetime import datetime, tzinfo
from enum import IntEnum
from itertools import chain
import json
import logging
from typing import Optional, Union

from IPy import IP
import requests
from requests import RequestException, JSONDecodeError

from nav.dhcp.generic_metrics import DhcpMetric, DhcpMetricKey, DhcpMetricSource
from nav.errors import GeneralException

_logger = logging.getLogger(__name__)


@dataclass(order=True, frozen=True)
class Subnet:
    id: int
    prefix: IP


class KeaDhcpMetricSource(DhcpMetricSource):
    """
    Communicates with a Kea Control Agent to enable fetching of DHCP
    metrics for each subnet managed by some specific underlying Kea
    DHCP4 or Kea DHCP6 server.

    The sole purpose of this class is to implement the superclass's
    fetch_metrics() method. Public methods are:

    * fetch_metrics(): Fetches DHCP metrics for each subnet managed by
      the Kea DHCP server. Metrics are returned as a list.

    * fetch_metrics_to_graphite(): Inherited from superclass. Fetches
    DHCP metrics as above and sends these to a graphite server.
    """

    def __init__(
        self,
        uri: str,
        dhcp_version: int = 4,
        timeout: int = 10,
        tzinfo: Optional[tzinfo] = None,
    ):
        """
        Instantiate a KeaDhcpMetricSource that fetches DHCP metrics
        from the Kea DHCP server managing IP version `dhcp_version`
        addresses, whose metrics is reachable via the Kea Control
        Agent listening to `port` on `address`.

        :param address:      IP address of the Kea Control Agent
        :param port:         TCP port of the Kea Control Agent
        :param https:        if True, use https. Otherwise, use http
        :param dhcp_version: ip version served by Kea DHCP server
        :param timeout:      how long to wait for a http response from
                             the Kea Control Agent before timing out
        :param tzinfo:       the timezone of the Kea Control Agent.
        """
        super()
        self._rest_uri = (
            uri  # TODO: Potential secrets are sent over HTTP, should enforce TLS!
        )
        self._dhcp_version = dhcp_version
        self._dhcp_config: Optional[dict] = None
        self._timeout = timeout
        self._access_time = datetime.now().timestamp()

        if dhcp_version == 4:
            self._kea_metric_keys = {
                DhcpMetricKey.TOTAL: "total-addresses",
                DhcpMetricKey.ASSIGNED: "assigned-addresses",
            }
        else:
            raise ValueError(f"DHCPv{dhcp_version} is not supported")

    def fetch_metrics(self) -> list[DhcpMetric]:
        """
        Fetches and returns a list containing the most recent DHCP
        metrics for each subnet managed by the Kea DHCP server. For
        each subnet and DhcpMetric-key combination, there is at least
        one corresponding metric in the returned list if no errors
        occur.

        If the Kea Control Agent responds with an empty response to
        one or more of the requests for some metric(s), these metrics
        will be missing in the returned list, but a list is still
        succesfully returned. Other errors while requesting metrics
        will cause a fitting subclass of KeaException to be raised:

        Communication errors (HTTP errors, JSON errors, access control
        errors) causes a KeaException that is reraised from the
        specific communication error to be raised.

        If the Kea Control Agent doesn't support the 'config-get' and
        'statistic-get' commands, then a KeaUnsupported exception is
        raised.

        General errors reported by the Kea Control Agent causes a
        KeaError to be raised.
        """
        self._access_time = datetime.now().timestamp()
        metrics: list[DhcpMetric] = []

        with requests.Session() as session:
            config = self._fetch_config(session)
            subnets = _subnets_of_config(config, self._dhcp_version)

            for subnet in subnets:
                total_addresses = self._fetch_subnet_metric(
                    subnet, DhcpMetricKey.TOTAL, session
                )
                assigned_addresses = self._fetch_subnet_metric(
                    subnet, DhcpMetricKey.ASSIGNED, session
                )
                if total_addresses is not None:
                    metrics.append(total_addresses)
                if assigned_addresses is not None:
                    metrics.append(assigned_addresses)

            newest_subnets = _subnets_of_config(
                self._fetch_config(session), self._dhcp_version
            )
            if sorted(subnets) != sorted(newest_subnets):
                _logger.warning(
                    "Subnet configuration was modified during DHCP metric fetching, "
                    "this may cause metric data being associated with wrong subnet."
                )

        return metrics

    def _fetch_subnet_metric(
        self, subnet: Subnet, metric_key: DhcpMetricKey, session: requests.Session
    ) -> Optional[DhcpMetric]:
        """
        Return the most recent metric recorded by the Kea DHCP server for the
        given subnet with the given metric_key
        """
        kea_metric_name = self._get_kea_metric_name(subnet, metric_key)
        try:
            response = self._send_query(session, "statistic-get", name=kea_metric_name)
        except KeaEmpty:
            # This may occur if the subnet we query have been removed from the
            # DHCP server's configuration at time of request
            response = {}

        kea_metric_samples = response.get("arguments", {}).get(kea_metric_name, [])

        if len(kea_metric_samples) == 0:
            _logger.info(
                "No samples found for metric '%s' in subnet '%s'",
                metric_key,
                subnet.prefix,
            )
            return None

        # The Kea server may be configured to keep track of the N most recent
        # metric samples for some N>=1, but we only care about the most recent
        # one. The Kea 2.6 Management API documentation does not specify any
        # explicit ordering of the returned samples, but ISC's official Kea
        # Management API consumer, Stork, relies on the fact that the first
        # sample in the returned list is the most recent^[0], so for simplicity's
        # sake so will we.
        #
        # [0]: https://gitlab.isc.org/isc-projects/stork/-/blob/4193375c01e3ec0b3d862166e2329d76e686d16d/backend/server/apps/kea/rps.go#L223-227
        value, timestring = kea_metric_samples[0]
        return DhcpMetric(
            subnet.prefix,
            metric_key,
            self._access_time,
            value,
        )

    def _fetch_config(self, session: requests.Session) -> dict:
        """
        Returns the current config of the Kea DHCP server that the Kea
        Control Agent controls.
        """
        if (
            self._dhcp_config is None
            or (dhcp_confighash := self._dhcp_config.get("hash", None)) is None
            or self._fetch_config_hash(session) != dhcp_confighash
        ):
            response = self._send_query(session, "config-get")
            try:
                self._dhcp_config = response["arguments"][f"Dhcp{self._dhcp_version}"]
            except KeyError as err:
                raise KeaException(
                    "Unrecognizable response to a 'config-get' request"
                ) from err
        return self._dhcp_config or {}

    def _fetch_config_hash(self, session: requests.Session) -> Optional[str]:
        """
        Returns the hash of the current config of the Kea DHCP server
        that the Kea Control Agent controls.
        """
        try:
            return (
                self._send_query(session, "config-hash-get")
                .get("arguments", {})
                .get("hash", None)
            )
        except KeaUnsupported as err:
            _logger.debug(str(err))
            return None

    def _send_query(self, session: requests.Session, command: str, **kwargs) -> dict:
        """
        Returns the response from the Kea Control Agent to the query
        with command `command` instructed towards the Kea DHCP server.
        Additional keyword arguments to this function will be passed
        as arguments to the command.

        Communication errors (HTTP errors, JSON errors, access control
        errors, unrecognized json response formats) causes a
        KeaException to be raised. If possible, it is reraised from a
        more descriptive error such as an HTTPError.

        Valid Kea Control Agent responses that indicate a failure on
        the server-end causes a descriptive subclass of KeaException
        to be raised.
        """
        log_summary = {
            "Request status": "Sending request to Kea Control Agent",
            "Location": self._rest_uri,
            "Command": command,
        }
        _logger.debug(log_summary)

        post_data = json.dumps(
            {
                "command": command,
                "arguments": {**kwargs},
                "service": [f"dhcp{self._dhcp_version}"],
            }
        )

        try:
            responses = session.post(
                self._rest_uri,
                data=post_data,
                timeout=self._timeout,
                headers={"Content-Type": "application/json"},
            )
            log_summary["Request status"] = "Received response from Kea Control Agent"
            log_summary["Response status"] = (
                f"HTTP {responses.status_code}: {responses.reason}"
            )
            responses.raise_for_status()
            responses = responses.json()
        except JSONDecodeError as err:
            raise KeaException(
                "Server does not look like a Kea Control Agent; "
                "response was not valid JSON",
                log_summary,
            ) from err
        except RequestException as err:
            raise KeaException(
                "HTTP-related error during request to server", log_summary
            ) from err

        # Any valid response from Kea is a JSON list with one entry corresponding to the
        # response from either the dhcp4 or dhcp6 service we queried
        if not (
            isinstance(responses, list)
            and len(responses) == 1
            and isinstance(responses[0], dict)
            and "result" in responses[0]
        ):
            if (
                isinstance(responses, dict)
                and "result" in responses
                and "text" in responses
            ):
                # If the response is a JSON object it's a specific error message
                # See https://kea.readthedocs.io/en/kea-2.6.0/arm/ctrl-channel.html#control-agent-command-response-format
                log_summary["Response"] = f"{responses['result']}: {responses['text']}"
                raise KeaException(
                    "Likely authentication or authorization error", log_summary
                )
            raise KeaException(
                "Server does not look like a Kea Control Agent; "
                "response JSON structured in an unknown way",
                log_summary,
            )

        response = responses[0]
        status = response["result"]
        description = response.get("text", "(no description)")

        log_summary["Response"] = f"Kea status {status}: {description}"
        _logger.debug(log_summary)

        if status == KeaStatus.SUCCESS:
            return response
        elif status == KeaStatus.UNSUPPORTED:
            raise KeaUnsupported(details=log_summary)
        elif status == KeaStatus.EMPTY:
            raise KeaEmpty(details=log_summary)
        elif status == KeaStatus.ERROR:
            raise KeaError(details=log_summary)
        elif status == KeaStatus.CONFLICT:
            raise KeaConflict(details=log_summary)
        raise KeaException("Kea returned an unkown status response", log_summary)

    def _get_kea_metric_name(self, subnet: Subnet, metric_key: DhcpMetricKey) -> str:
        """
        Returns the argument recognized by Kea to query the metric with the
        given metric_key for the given subnet
        """
        kea_metric_key = self._kea_metric_keys[metric_key]
        return f"subnet[{subnet.id}].{kea_metric_key}"


def _subnets_of_config(config: dict, ip_version: int) -> list[Subnet]:
    """
    Returns a list containing one (subnet-id, subnet-prefix) tuple per
    subnet listed in the Kea DHCP configuration `config`.
    """
    subnets: list[Subnet] = []
    subnetkey = f"subnet{ip_version}"
    for subnet in chain.from_iterable(
        [config.get(subnetkey, [])]
        + [network.get(subnetkey, []) for network in config.get("shared-networks", [])]
    ):
        subnet_id = subnet.get("id", None)
        netprefix = subnet.get("subnet", None)
        if subnet_id is None or netprefix is None:
            _logger.warning("id and/or prefix missing from a subnet's configuration")
            continue
        subnets.append(Subnet(subnet_id, IP(netprefix)))
    return subnets


class KeaException(GeneralException):
    """Error related to interaction with a Kea Control Agent"""

    def __init__(
        self, message: Optional[str] = None, details: Optional[dict[str, str]] = None
    ):
        self.message = message
        self.details = details

    def __str__(self) -> str:
        doc = ""
        message = ""
        details = ""
        if self.__doc__:
            doc = self.__doc__
        if self.message:
            message = f": {self.message}"
        if self.details:
            details = "\nDetails:\n"
            details += "\n".join(
                f"{label}: {info}" for label, info in self.details.items()
            )
        return "".join([doc, message, details])


class KeaError(KeaException):
    """Kea failed during command processing"""


class KeaUnsupported(KeaException):
    """Unsupported command"""


class KeaEmpty(KeaException):
    """Requested resource not found"""


class KeaConflict(KeaException):
    """Kea failed to apply requested changes due to conflicts with its server state"""


class KeaStatus(IntEnum):
    """Status of a response sent from a Kea Control Agent"""

    SUCCESS = 0
    ERROR = 1
    UNSUPPORTED = 2
    EMPTY = 3
    CONFLICT = 4
