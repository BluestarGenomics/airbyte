from abc import ABC
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple
from urllib.parse import urlparse, parse_qs

import logging
import requests
from airbyte_cdk.logger import AirbyteLogger
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http import HttpStream
from airbyte_cdk.sources.streams.http.requests_native_auth import TokenAuthenticator
from requests.api import request
from source_medrio_dataviews.streams import Studies, Queries, ClinicalData

logger = AirbyteLogger()

# Source
class SourceMedrioDataviews(AbstractSource):
    def check_connection(self, logger, config) -> Tuple[bool, any]:
        try:
            self.get_token(config, "v1")
            self.get_token(config, "v2")
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
            raise KeyError(
                f"api_version {api_version} not one of {list(auth_urls.keys())}"
            )
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "username": config["api_user_name"],
            "password": config["api_user_password"],
            "customerApikey": config["enterprise_api_key"],
            "grant_type": grant_type,
        }
        response = requests.post(request_url, headers=headers, data=data)
        if response.json().get("access_token"):
            return TokenAuthenticator(response.json()["access_token"])
        else:
            raise RuntimeError(response.json().get("message"))

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        auth_v1 = self.get_token(config, "v1")
        auth_v2 = self.get_token(config, "v2")
        return [
            Studies(authenticator=auth_v1),
            Queries(authenticator=auth_v2),
            ClinicalData(authenticator=auth_v2),
        ]
