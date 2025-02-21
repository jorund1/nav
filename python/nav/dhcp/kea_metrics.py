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
Fetch DHCP metrics from Kea DHCP servers by using Kea Management API

             |
   NAV side  |  Kea side
             |
        HTTP |                         IPC
Client <---------> Kea Control Agent <=====> Kea DHCP4 server
             |       (API server)
             |
"""

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from itertools import chain
import json
import logging
from typing import Optional, Literal

from IPy import IP
from requests import RequestException, JSONDecodeError, Session

from nav.errors import GeneralException

_logger = logging.getLogger(__name__)


@dataclass(order=True, frozen=True)
class _Subnet:
    id: int
    prefix: IP


@dataclass(order=True, frozen=True)
class _Metric:
    """
    Represents a metric collected from a DHCP server. Three types of metrics
    with different value interpretations supported:

    total:     value is the maximum possible amount of active leases in the
               subnet

    assigned:  value is the current amount of active leases in the subnet

    declined:  value is the amount of DHCP-maintained addresses in use by an
               entity unknown to the server and thus not available for
               assignment. (Should ideally always be zero.)
               For more detailed info on this metric, see e.g.
               https://web.archive.org/web/20240816164358/https://kea.readthedocs.io/en/kea-2.2.0/arm/dhcp6-srv.html#duplicate-addresses-dhcpdecline-support
    """

    timestamp: float
    subnet_prefix: IP
    name: Literal["total", "assigned", "declined"]
    value: int


class Client:
    """
    Kea Management API client that fetches DHCP metrics for each subnet managed
    by some specific underlying Kea DHCP server.
    """

    def __init__(
        self,
        uri: str,
        dhcp_version: int = 4,
        timeout: int = 10,
    ):
        """
        :param uri:          URI for the Kea Control Agent (Management API endpoint).
        :param dhcp_version: IP version served by Kea DHCP server. Currently,
                             only IPv4 DHCP servers are supported.
        :param timeout:      How long to wait for a http response from
                             the Kea Control Agent before timing out.
        """
        if not uri.startswith("https://"):
            _logger.warning("Kea Management API client configured to use plain HTTP")

        self._rest_uri: str = uri
        self._dhcp_version: int = dhcp_version
        self._dhcp_config: Optional[dict] = None
        self._timeout: int = timeout
        self._session: Optional[Session] = None

        if dhcp_version == 4:
            self._api_namings = (
                ("total", "total-addresses"),
                ("assigned", "assigned-addresses"),
                ("declined", "declined-addresses"),
            )
        else:
            raise ValueError(f"DHCPv{dhcp_version} is not supported")

    def fetch_metrics(self) -> list[_Metric]:
        """
        Fetches and returns a list containing the most recent DHCP
        metrics for each subnet + metric-name combination managed by
        the Kea DHCP server.

        If the Kea Control Agent responds with an empty response to
        one or more of the requests for some metric(s), these metrics
        will be missing in the returned list, but a list is still
        succesfully returned. Other errors while requesting metrics
        will cause a fitting subclass of KeaException to be raised.

        Exceptions raised:

        Communication errors (HTTP errors, JSON errors, access control
        errors, unexpected responses) causes a KeaException to be raised.

        If the Kea Control Agent doesn't support the bare-minimum set of
        commands this client needs for fetching metrics, then a KeaUnsupported
        exception is raised.
        """
        self._session = Session()
        start_time = datetime.now().timestamp()

        config = self._fetch_config()
        subnets = self._subnets_of_config(config)

        metrics: list[_Metric] = []
        for subnet in subnets:
            for metric_name, api_naming in self._api_namings:
                value = self._fetch_metric_value(subnet, api_naming)
                if value is not None:
                    metric = _Metric(start_time, subnet.prefix, metric_name, value)
                    metrics.append(metric)

        maybe_updated_config = self._fetch_config()
        maybe_updated_subnets = self._subnets_of_config(maybe_updated_config)
        if sorted(subnets) != sorted(maybe_updated_subnets):
            _logger.warning(
                "Server's subnet configuration was modified during fetching of DHCP "
                "metrics. This may cause metric data being associated with wrong subnet."
            )

        self._session.close()
        self._session = None
        end_time = datetime.now().timestamp()
        _logger.info(
            "Fetched %d metric(s) for %d subnet(s) in %f seconds from %s",
            len(metrics),
            len(subnets),
            end_time - start_time,
            self._rest_uri,
        )
        return metrics

    def _fetch_metric_value(
        self, subnet: _Subnet, api_metric_name: str
    ) -> Optional[int]:
        """
        Return the most recent metric value recorded by the Kea DHCP server for
        the given subnet with the given api_metric_name
        """
        full_name = f"subnet[{subnet.id}].{api_metric_name}"
        try:
            response = self._send_query("statistic-get", name=full_name)
        except KeaEmpty:
            # This may occur if the subnet we query have been removed from the
            # DHCP server's configuration at time of request
            response = {}

        samples = response.get("arguments", {}).get(full_name, [])

        if len(samples) == 0:
            _logger.info(
                "No samples found when querying for '%s' in subnet '%s'",
                api_metric_name,
                subnet.prefix,
            )
            return None

        # The Kea server may be configured to keep track of the N most recent
        # metric values for some N>=1, but we only care about the most recent
        # one. The Kea 2.6 Management API documentation does not specify any
        # explicit ordering of the returned samples, but ISC's official Kea
        # Management API client, Stork, relies on the fact that the first
        # sample in the returned list is the most recent^[0], so for simplicity's
        # sake so will we.
        #
        # [0]: https://gitlab.isc.org/isc-projects/stork/-/blob/4193375c01e3ec0b3d862166e2329d76e686d16d/backend/server/apps/kea/rps.go#L223-227
        value, timestring = samples[0]
        return value

    def _fetch_config(self) -> dict:
        """
        Returns the current config of the Kea DHCP server that the Kea
        Control Agent controls.
        """
        if (
            self._dhcp_config is None
            or (dhcp_confighash := self._dhcp_config.get("hash", None)) is None
            or self._fetch_config_hash() != dhcp_confighash
        ):
            response = self._send_query("config-get")
            try:
                self._dhcp_config = response["arguments"][f"Dhcp{self._dhcp_version}"]
            except KeyError as err:
                raise KeaException(
                    "Unrecognizable response to a 'config-get' request"
                ) from err
        return self._dhcp_config or {}

    def _fetch_config_hash(self) -> Optional[str]:
        """
        Returns the hash of the current config of the Kea DHCP server
        that the Kea Control Agent controls.
        """
        try:
            return (
                self._send_query("config-hash-get")
                .get("arguments", {})
                .get("hash", None)
            )
        except KeaUnsupported as err:
            _logger.debug(str(err))
            return None

    def _send_query(self, command: str, **kwargs) -> dict:
        """
        Returns the Management API response from the Kea Control Agent to the
        query with command `command` instructed towards the Kea DHCP server.
        Additional keyword arguments to this function will be passed as
        arguments to the command.

        Communication errors (HTTP errors, JSON errors, access control errors,
        unrecognized json response formats) causes a KeaException to be
        raised. If possible, it is reraised from a more descriptive error such
        as an HTTPError.

        Valid Kea Control Agent responses that indicate a failure on the
        server-end causes a descriptive subclass of KeaException to be raised.
        """
        log_summary = {
            "Client status": "Waiting for response from Kea Control Agent",
            "Kea Control Agent URI": self._rest_uri,
            "Management API command": command,
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
            responses = self._session.post(
                self._rest_uri,
                data=post_data,
                timeout=self._timeout,
                headers={"Content-Type": "application/json"},
            )
            log_summary["Client status"] = "Received response from Kea Control Agent"
            log_summary["HTTP status"] = (
                f"HTTP {responses.status_code}: {responses.reason}"
            )
            responses.raise_for_status()
            responses = responses.json()
        except JSONDecodeError as err:
            raise KeaException(
                "Server does not look like a Kea Control Agent; ",
                "response was not valid JSON",
                log_summary,
            ) from err
        except RequestException as err:
            raise KeaException(
                "Error with connection to Kea Control Agent", log_summary
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

        if status == _KeaStatus.SUCCESS:
            return response
        elif status == _KeaStatus.UNSUPPORTED:
            raise KeaUnsupported(details=log_summary)
        elif status == _KeaStatus.EMPTY:
            raise KeaEmpty(details=log_summary)
        elif status == _KeaStatus.ERROR:
            raise KeaError(details=log_summary)
        elif status == _KeaStatus.CONFLICT:
            raise KeaConflict(details=log_summary)
        raise KeaException("Kea returned an unkown status response", log_summary)

    def _subnets_of_config(self, config: dict) -> list[_Subnet]:
        """
        Returns a list containing one (subnet-id, subnet-prefix) tuple per
        subnet listed in the Kea DHCP configuration `config`.
        """
        subnets: list[_Subnet] = []
        subnetkey = f"subnet{self._dhcp_version}"
        for subnet in chain.from_iterable(
            [config.get(subnetkey, [])]
            + [
                network.get(subnetkey, [])
                for network in config.get("shared-networks", [])
            ]
        ):
            subnet_id = subnet.get("id", None)
            netprefix = subnet.get("subnet", None)
            if subnet_id is None or netprefix is None:
                _logger.warning(
                    "id and/or prefix missing from a subnet's configuration"
                )
                continue
            subnets.append(_Subnet(subnet_id, IP(netprefix)))
        return subnets


class KeaException(GeneralException):
    """Error related to interaction with a Kea Control Agent"""

    def __init__(
        self, message: Optional[str] = None, details: Optional[dict[str, str]] = None
    ):
        self.message = message
        self.details = details

    def __str__(self) -> str:
        message = ""
        details = ""
        message = f"{self.message}" or self.__doc__ or ""
        if self.details:
            details = "\nError details:\n"
            details += "\n".join(
                f"\t{label} was '{info}'" for label, info in self.details.items()
            )
        return "".join([message, details])


class KeaError(KeaException):
    """Kea failed during command processing"""


class KeaUnsupported(KeaException):
    """Unsupported command"""


class KeaEmpty(KeaException):
    """Requested resource not found"""


class KeaConflict(KeaException):
    """Kea failed to apply requested changes due to conflicts with its server state"""


class _KeaStatus(IntEnum):
    """Status of a response sent from a Kea Control Agent"""

    SUCCESS = 0
    ERROR = 1
    UNSUPPORTED = 2
    EMPTY = 3
    CONFLICT = 4
