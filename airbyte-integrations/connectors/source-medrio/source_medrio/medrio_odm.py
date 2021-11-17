import lxml.etree as etree
import requests
import untangle
import urllib.parse as up

from airbyte_cdk.logger import AirbyteLogger
from pathlib import Path
from retry import retry
from typing import Union

logger = AirbyteLogger()


class MedrioApi:
    def __init__(self, api_key) -> None:
        self.api_key = api_key
        self.base_url = f"https://na13.api.medrio.com/v1/MedrioServiceV1.svc/Customers/{self.api_key}/Studies/"
        self.job_id = None
        self.file_url = None

    def post_job_request(self, content_type, study_id):
        if self.job_id is not None:
            logger.info(f"Job ID = {self.job_id}. Will not request a new one.")
            return
        assert content_type in ["ConfigOnly", "AllData"]
        payload = f"""<ExportODM xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
        <ContentType>{content_type}</ContentType>
        </ExportODM>"""
        headers = {"Content-Type": "application/xml"}
        r = requests.post(
            url=up.urljoin(self.base_url, study_id, "Jobs", "ExportODM"),
            data=payload,
            headers=headers,
        )
        xml = untangle.parse(r.text)
        logger.debug(self.pretty_print(r))
        message = xml.MedrioResponse.Message.cdata
        if message == "Success":
            response_code = xml.MedrioResponse.Code.cdata
            logger.info("Request: %s", response_code)
            job_status = xml.MedrioResponse.Records.Job.Status.cdata
            logger.info("Status: %s", job_status)
            job_id = xml.MedrioResponse.Records.Job.JobID.cdata
            logger.info("JobID: %s", job_id)
            self.job_id = job_id
        else:
            logger.info("Request failed: %s", message)

    @retry(FileNotFoundError, tries=18, delay=5, backoff=2, max_delay=300)
    def get_job_file_url(self):
        if self.job_id is None:
            raise NameError(
                "job_id not found, please make sure http_request was successful"
            )
        logger.info("Requesting JobID: %s", self.job_id)
        r = requests.get(up.urljoin(self.base_url, self.job_id))
        xml = untangle.parse(r.text)
        status = xml.MedrioResponse.Records.Job.Status.cdata
        if status == "Successful":
            logger.info("File has successfully been generated")
            self.file_url = xml.MedrioResponse.Records.Job.File.cdata
        elif status in ("Error", "Purged"):
            logger.error(self.pretty_print(r))
            raise RuntimeError(f"JobID {self.job_id} failed. Status={status}")
        elif status == "Processing":
            raise FileNotFoundError(f"JobID {self.job_id} not ready. Status={status}")
        else:
            logger.warning(self.pretty_print(r))
            raise FileNotFoundError(f"JobID {self.job_id} not ready. Status={status}")

    @staticmethod
    def pretty_print(response):
        import xml.dom.minidom as minidom  # beautify XML

        return minidom.parseString(response.text).toprettyxml()


class MedrioOdmXml:
    def __init__(self, xml_path: Union[Path, str]):
        self.xml_path = Path(xml_path)
        xml = etree.parse(str(self.xml_path.absolute()))
        self.root = xml.getroot()
        # self.clinical_records = self.parse_clinical()

    def parse_clinical(self):
        subject_data = self.root.findall(
            ".//*{http://www.cdisc.org/ns/odm/v1.3}SubjectData"
        )
        records = []
        for subj in subject_data:
            records.extend(self._json_subject_data(subj))
        return records

    def _json_subject_data(self, subject_data: etree._Element):
        ns = "{http://www.cdisc.org/ns/odm/v1.3}"
        tags = {
            tag: f"{ns}{tag}"
            for tag in ("StudyEventData", "FormData", "AuditRecord", "ItemGroupData")
        }
        records = []
        for ev, elem in etree.iterwalk(
            subject_data, events=("end", "start"), tag=tags.values()
        ):
            if ev == "start" and elem.tag == tags["StudyEventData"]:
                event = {k: v for k, v in elem.attrib.items()}
                event.update({self.rm_ns(k): v for k, v in subject_data.items()})
            if ev == "start" and elem.tag == tags["FormData"]:
                form = {k: v for k, v in event.items()}
                for k, v in elem.attrib.items():
                    form.update({self.rm_ns(k): v})
            if ev == "start" and elem.tag == tags["AuditRecord"]:
                form["DateTimeStamp"] = elem.find(f"{ns}DateTimeStamp").text
            if ev == "start" and elem.tag == tags["ItemGroupData"]:
                item_group = {k: v for k, v in form.items()}
                item_group.update({k: v for k, v in elem.attrib.items()})
                item_group.update(
                    {ch.get("ItemOID"): ch.text for ch in elem.getchildren()}
                )
                records.append(item_group)
        return records

    def parse_config(self):
        forms = {}
        form_data = self.root.findall(".//{http://www.cdisc.org/ns/odm/v1.3}FormDef")
        item_groups = self._item_groups()
        for form in form_data:
            form_igs = [
                ig.get("ItemGroupOID")
                for ig in form.findall(
                    ".//{http://www.cdisc.org/ns/odm/v1.3}ItemGroupRef"
                )
            ]
            form_igs = {k: item_groups[k] for k in form_igs if k in item_groups}
            items = list(chain(*(list(v["Items"].values()) for v in form_igs.values())))
            forms[form.get("OID")] = {"Name": form.get("Name"), "Items": items}
        return forms

    def _item_groups(self):
        items = {
            item.get("OID"): item.attrib
            for item in self.root.findall(
                ".//{http://www.cdisc.org/ns/odm/v1.3}ItemDef"
            )
        }
        item_groups = {}
        for item_group in self.root.findall(
            ".//{http://www.cdisc.org/ns/odm/v1.3}ItemGroupDef"
        ):
            item_refs = {
                x.get("ItemOID"): items.get(x.get("ItemOID"))
                for x in item_group.getchildren()
            }
            item_groups[item_group.get("OID")] = {
                "Name": item_group.get("Name"),
                "Items": item_refs,
            }
        return item_groups

    @staticmethod
    def pprint(elem: etree._Element):
        print(etree.tostring(elem, pretty_print=True).decode("utf-8"))

    @staticmethod
    def rm_ns(elem: etree._Element):
        return etree.QName(elem).localname
