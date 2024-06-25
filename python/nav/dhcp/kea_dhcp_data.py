"""
Functions for querying the Kea Control Agent for statistics from Kea DHCP
servers.

     RESTful-queries                      IPC
nav <---------------> Kea Control Agent <=====> Kea DHCP4 server / Kea DHCP6 server
        (json)

No additional hook libraries are assumed to be included with the Kea Control
Agent that is queried, meaning this module will be able to gather DHCP
statistics from any Kea Control Agent.

* Stork (https://gitlab.isc.org/isc-projects/stork) is used as a guiding
implementation for interacting with the Kea Control Agent.
* See also the Kea Control Agent documentation. This script assumes Kea versions
>= 2.2.0 are used.  (https://kea.readthedocs.io/en/kea-2.2.0/arm/agent.html).
"""
from dataclasses import dataclass, asdict
from enum import IntEnum
import logging
import requests
import json
from requests.exceptions import JSONDecodeError, HTTPError
from typing import Union, Optional
from IPy import IP

logger = logging.getLogger(__name__)


class KeaStatus(IntEnum):
    """Status of a REST response."""
    # Successful operation.
    SUCCESS = 0
    # General failure.
    ERROR = 1
    # Command is not supported.
    UNSUPPORTED = 2
    # Successful operation, but failed to produce any results.
    EMPTY = 3
    # Unsuccessful operation due to a conflict between the command arguments and the server state.
    CONFLICT = 4


@dataclass
class KeaResponse:
    """
    Class representing a REST response on a REST query sent to a Kea Control
    Agent.
    """
    result: int
    text: str
    arguments: dict[str: Union[str, int]]
    service: str

    @property
    def success(self):
        return self.result == KeaStatus.SUCCESS


@dataclass
class KeaQuery:
    """Class representing a REST query to be sent to a Kea Control Agent."""
    command: str
    arguments: dict[str: Union[str, int]]
    service: list[str] # The server(s) at which the command is targeted. Usually ["dhcp4", "dhcp6"] or ["dhcp4"] or ["dhcp6"].


@dataclass
class KeaDhcpSubnet:
    """Class representing information about a subnet managed by a Kea DHCP server."""
    id: int # either specified in the server config or assigned automatically by the dhcp server
    prefix: IP # e.g. 192.0.2.1/24
    pools: list[tuple[IP]] # e.g. [(192.0.2.10, 192.0.2.20), (192.0.2.64, 192.0.2.128)]

    @classmethod
    def from_json(cls, subnet_json: dict):
        """
        Initialize and return a Subnet instance based on json

        :param json: python dictionary that is structured the same way as the
        json object representing a subnet in the Kea DHCP config file.
        Example:
            {
                "id": 0
                "subnet": "192.0.2.0/24",
                "pools": [
                    {
                        "pool": "192.0.2.1 - 192.0.2.100"
                    },
                    {
                        "pool": "192.0.2.128/26"
                    }
                ]
            }
        """
        if "id" not in subnet_json:
            raise ValueError("Expected subnetjson['id'] to exist")
        id = subnet_json["id"]

        if "subnet" not in subnet_json:
            raise ValueError("Expected subnetjson['subnet'] to exist")
        prefix = IP(subnet_json["subnet"]),

        pools = []
        for obj in subnet_json.get("pools", []):
            pool = obj["pool"]
            if "-" in pool: # TODO: Error checking?
                # pool == "x.x.x.x - y.y.y.y"
                start, end = (IP(ip) for ip in pool.split("-"))
            else:
                # pool == "x.x.x.x/nn"
                pool = IP(pool)
                start, end = pool[0], pool[-1]
            pools.append((start, end))

        return cls(
            id=id,
            prefix=prefix,
            pools=pools,
        )

@dataclass
class KeaDhcpData:
    """
    Class representing information found in the configuration of a Kea DHCP
    server. Most importantly, this class contains:
    * A list of the shared networks managed by the DHCP server
      * A shared network furthermore contain a list of subnets
        assigned to that network
    * The IP version of the DCHP server
    """
    _config_hash: Optional[str] # Used to check if there's a new config on the Kea DHCP server
    ip_version: int
    subnets: list[KeaDhcpSubnet]

    rest_address: str
    rest_port: int
    rest_https: bool

    @property
    def rest_location(self):
        scheme = "https" if self.rest_https else "http"
        return f"{scheme}://{self.rest_address}:{self.rest_port}/"

    @classmethod
    def from_json(
            cls,
            config_json: dict,
            config_hash: Optional[str] = None,
            rest_address: str,
            rest_post: int,
            rest_https: bool = True
    ):
        """
        Initialize and return a KeaDhcpData instance based on json

        :param json: a dictionary that is structured the same way as a
        Kea DHCP configuration.
        Example:
        {
            "Dhcp4": {
                "subnet4": [{
                "id": 1,
                "subnet": "192.0.2.0/24",
                "pools": [
                    {
                        "pool": "192.0.2.1 - 192.0.2.200",
                    },
                ],
                }]
            }
        }

        :param hash: hash of the Kea DHCP config file as returned by a
        `config-hash-get` query on the kea-ctrl-agent REST server.
        """
        if len(config_json) > 1:
            raise ValueError("Did not expect len(configjson) > 1")

        ip_version, json = config_json.popitem()
        if ip_version == "Dhcp4":
            ip_version = 4
        elif ip_version == "Dhcp6":
            ip_version == 6
        else:
            raise ValueError(f"Unsupported DHCP IP version '{ip_version}'")

        subnets = []
        for obj in json.get(f"subnet{ip_version}", []):
            subnet = KeaDhcpSubnet.from_json(obj)
            subnets.append(subnet)

        return cls(
            _config_hash=config_hash,
            ip_version=ip_version,
            subnets=subnets,
            rest_address=rest_address,
            rest_post=rest_post,
            rest_https=rest_https,
        )


def send_query(query: KeaQuery, address: str, port: int, https: bool = True, session: requests.Session = None) -> list[KeaResponse]:
    """
    Internal function.
    Send `query` to a Kea Control Agent listening to `port`
    on IP address `address`, using either http or https

    :param session: optional session to be used when sending the query. Assumed
    to not be closed. Session is not closed after the query, so that the session
    can be used for persistent connections among differend send_query calls.
    """
    scheme = "https" if https else "http"
    location = f"{scheme}://{address}:{port}/"
    logger.debug("send_query: sending request to %s with query %r", location, query)
    try:
        if session is None:
            r = requests.post(location, data=json.dumps(asdict(query)), headers={"Content-Type": "application/json"})
        else:
            r = session.post(location, data=json.dumps(asdict(query)), headers={"Content-Type": "application/json"})
    except HTTPError as err:
        logger.error("send_query: request to %s yielded an error: %d %s", err.url, err.status_code, err.reason)
        raise err

    try:
        response_json = r.json()
    except JSONDecodeError as err:
        logger.error("send_query: expected json from %s, got %s", address, r.text)
        raise err

    if isinstance(response_json, dict):
        logger.error("send_query: expected a json list of objects from %s, got %r", address, response_json)
        raise ValueError(f"bad response from {address}: {response_json!r}")

    responses = []
    for obj in response_json:
        response = KeaResponse(
            obj.get("result", KeaStatus.ERROR),
            obj.get("text", ""),
            obj.get("arguments", {}),
            obj.get("service", ""),
        )
        responses.append(response)
    return responses


def get_dhcp_server(address: str, port: int, https: bool = True, ip_version: int = 4) -> KeaDhcpConfig:
    """ Fetch the config of a Kea DHCP server that manages addresses of IP
    version `ip_version` from a Kea Control Agent listening to `port` on
    `address`.

    :param address: the IP address or DNS addressable hostname of the Kea
    Control Agent.
    :param port: the port that the Kea Control Agent listens to.
    :param https: whether or not to use https. If not using https, http is used.
    :param ip_version: the IP version of the Kea DHCP server
    """
    query = KeaQuery(
        command="config-get",
        service=[f"dhcp{ip_version}"],
        arguments={},
    )
    responses = send_query(query, address, port, https)
    if len(responses) != 1:
        raise Exception(f"Received invalid amount of responses from '{address}'") # TODO: Change Exception

    response = responses[0]
    if not response.success:
        raise Exception("Did not receive config file from DHCP server")

    return KeaDhcpConfig.from_json(responses[0].arguments)

def get_dhcp_statistics(address: str, port: int, https: bool = True, ip_version: int = 4) -> KeaDhcpSubnet:
    query = KeaQuery(
        command="statistic-get",
        service=[f"dhcp{ip_version}"],
        arguments={
            "name": f"subnet[1].assigned-addresses",
        },
    )

    with requests.Session() as s:
        responses = send_query(query, address, port, https, session=s)
        if len(responses) != 1:
            raise Exception(f"Received invalid amount of responses from '{address}'") # TODO: Change Exception

        response = responses[0]
        if not response.success:
            raise Exception("Did not receive statistics from DHCP server")
    return response