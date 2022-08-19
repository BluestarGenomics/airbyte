#
# Copyright (c) 2022 Airbyte, Inc., all rights reserved.
#


from abc import ABC
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple

import pendulum
import requests
from airbyte_cdk.logger import AirbyteLogger
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http import HttpStream
from airbyte_cdk.sources.streams.http.auth import TokenAuthenticator
from .medrio_odm import MedrioOdmApi
from .streams import ApprovalEvent, DataAudit, FormStatus, Studies, Queries


logger = AirbyteLogger()

"""
TODO: Most comments in this class are instructive and should be deleted after the source is implemented.

This file provides a stubbed example of how to use the Airbyte CDK to develop both a source connector which supports full refresh or and an
incremental syncs from an HTTP API.

The various TODOs are both implementation hints and steps - fulfilling all the TODOs should be sufficient to implement one basic and one incremental
stream from a source. This pattern is the same one used by Airbyte internally to implement connectors.

The approach here is not authoritative, and devs are free to use their own judgement.

There are additional required TODOs in the files within the integration_tests folder and the spec.yaml file.
"""


medrio_to_airbyte_typing = {
    "text": {"type": "string"},
    "partialDate": {"type": ["string"], "format": "date"},
    "date": {"type": ["string"], "format": "date"},
    "boolean": {"type": "boolean"},
    "integer": {"type": "integer"},
    "float": {"type": "number"},
    "time": {"type": ["string"], "format": "time"},
}

# Source
class SourceMedrio(AbstractSource):
    def check_connection(self, logger, config) -> Tuple[bool, any]:
        try:
            self.get_token(config, "v1")
            self.get_token(config, "v2")
            odm_api = MedrioOdmApi(api_key=config["enterprise_api_key"])
            studies = odm_api.get_studies()
            return True, None
        except Exception as e:
            return False, str(e)

    def get_token(self, config, api_version: str) -> TokenAuthenticator:
        auth_urls = {
            "v1": ("https://connectapi.medrio.com/Oauth/token", "openapi"),
            "v2": ("https://connectapi.medrio.com/dataview/oauth/token", "dataviewapi"),
        }
        if api_version in auth_urls:
            request_url, grant_type = auth_urls.get(api_version)
        else:
            raise KeyError(f"api_version {api_version} not one of {list(auth_urls.keys())}")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "username": config["api_user_name"],
            "password": config["api_user_password"],
            "customerApikey": config["enterprise_api_key"],
            "grant_type": grant_type,
        }
        response = requests.post(request_url, headers=headers, data=data)
        if response.json().get("access_token"):
            logger.info(f"{api_version} token retrieved")
            return TokenAuthenticator(response.json()["access_token"])
        else:
            raise RuntimeError(response.json().get("message"))

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        auth_v1 = self.get_token(config, "v1")
        auth_v2 = self.get_token(config, "v2")
        odm_api = MedrioOdmApi(api_key=config["enterprise_api_key"])
        start_date = config["start_date"]
        studies = odm_api.get_studies()
        streams = []
        # for study_name in config["medrio_study_name_array"]:
        #     stream = MedrioOdm(api=copy.deepcopy(odm_api), study_id=studies[study_name])
        #     stream.update_schema(extra_schema={}, stream_name=study_name)
        #     streams.append(stream)
        return streams + [
            Studies(authenticator=auth_v1),
            Queries(authenticator=auth_v2),
            ApprovalEvent(authenticator=auth_v2),
            FormStatus(authenticator=auth_v2),
            DataAudit(authenticator=auth_v2, start_date=start_date),
        ]
