from abc import ABC
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple

import requests
from airbyte_cdk.logger import AirbyteLogger
from airbyte_cdk.models import AirbyteMessage, AirbyteCatalog, ConfiguredAirbyteCatalog
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http.requests_native_auth import TokenAuthenticator
from requests.api import request
from .medrio_odm import MedrioOdmApi, MedrioOdmXml
from .streams import Studies, Queries, MedrioOdm

logger = AirbyteLogger()

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
            logger.info(f"{api_version} token retrieved")
            return TokenAuthenticator(response.json()["access_token"])
        else:
            raise RuntimeError(response.json().get("message"))

    def discover(
        self, logger: AirbyteLogger, config: Mapping[str, Any]
    ) -> AirbyteCatalog:
        return super().discover(logger, config)

    def read(
        self,
        logger: AirbyteLogger,
        config: Mapping[str, Any],
        catalog: ConfiguredAirbyteCatalog,
        state: MutableMapping[str, Any] = None,
    ) -> Iterable[AirbyteMessage]:
        return super().read(logger, config, catalog, state=state)

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        auth_v1 = self.get_token(config, "v1")
        auth_v2 = self.get_token(config, "v2")
        odm_api = MedrioOdmApi(api_key=config["enterprise_api_key"])
        studies = odm_api.get_studies()
        streams = []
        for study_name in config["medrio_study_name_array"]:
            stream = MedrioOdm(api=odm_api, study_id=studies[study_name])
            stream.update_schema(extra_schema={}, stream_name=study_name)
            streams.append(stream)
        return streams + [
            Studies(authenticator=auth_v1),
            Queries(authenticator=auth_v2),
        ]
