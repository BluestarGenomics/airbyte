import React, { useState, useRef } from "react";
import { FormattedMessage } from "react-intl";

import { Button } from "components";
import ContentCard from "components/ContentCard";
import ServiceForm from "views/Connector/ServiceForm";
import useRouter from "hooks/useRouter";
import { useSourceDefinitionSpecificationLoad } from "hooks/services/useSourceHook";
import { JobInfo } from "core/resources/Scheduler";
import { JobsLogItem } from "components/JobItem";
import { createFormErrorMessage } from "utils/errorStatusMessage";
import { ConnectionConfiguration } from "core/domain/connection";
import { SourceDefinition } from "core/resources/SourceDefinition";
import { useAnalytics } from "hooks/useAnalytics";
import useDocumentation from "hooks/services/useDocumentation";
import SideView, { SideViewRef } from "components/SideView/SideView";
import { Markdown } from "components/Markdown";

type IProps = {
  onSubmit: (values: {
    name: string;
    serviceType: string;
    sourceDefinitionId?: string;
    connectionConfiguration?: ConnectionConfiguration;
  }) => void;
  afterSelectConnector?: () => void;
  sourceDefinitions: SourceDefinition[];
  hasSuccess?: boolean;
  error?: { message?: string; status?: number } | null;
  jobInfo?: JobInfo;
};

const SourceForm: React.FC<IProps> = ({
  onSubmit,
  sourceDefinitions,
  error,
  hasSuccess,
  jobInfo,
  afterSelectConnector,
}) => {
  const sideViewRef = useRef<SideViewRef>({} as SideViewRef);

  const { location } = useRouter();
  const analyticsService = useAnalytics();

  const [sourceDefinitionId, setSourceDefinitionId] = useState(
    location.state?.sourceDefinitionId || ""
  );

  const {
    sourceDefinitionSpecification,
    sourceDefinitionError,
    isLoading,
  } = useSourceDefinitionSpecificationLoad(sourceDefinitionId);

  const { data: sourceDefinitionDocs } = useDocumentation(
    sourceDefinitionSpecification?.documentationUrl || ""
  );

  const onDropDownSelect = (sourceDefinitionId: string) => {
    setSourceDefinitionId(sourceDefinitionId);
    const connector = sourceDefinitions.find(
      (item) => item.sourceDefinitionId === sourceDefinitionId
    );

    if (afterSelectConnector) {
      afterSelectConnector();
    }

    analyticsService.track("New Source - Action", {
      action: "Select a connector",
      connector_source_definition: connector?.name,
      connector_source_definition_id: sourceDefinitionId,
    });
  };

  const onSubmitForm = async (values: {
    name: string;
    serviceType: string;
  }) => {
    await onSubmit({
      ...values,
      sourceDefinitionId: sourceDefinitionSpecification?.sourceDefinitionId,
    });
  };

  const errorMessage = error ? createFormErrorMessage(error) : null;

  return (
    <>
      <SideView ref={sideViewRef}>
        <Markdown content={sourceDefinitionDocs} />
      </SideView>
      <ContentCard
        title={<FormattedMessage id="onboarding.sourceSetUp" />}
        actions={
          !!sourceDefinitionDocs && (
            <Button secondary onClick={sideViewRef?.current.open}>
              <FormattedMessage id="form.setupGuide" />
            </Button>
          )
        }
      >
        <ServiceForm
          onServiceSelect={onDropDownSelect}
          onSubmit={onSubmitForm}
          formType="source"
          availableServices={sourceDefinitions}
          selectedConnector={sourceDefinitionSpecification}
          hasSuccess={hasSuccess}
          fetchingConnectorError={sourceDefinitionError}
          errorMessage={errorMessage}
          isLoading={isLoading}
          formValues={
            sourceDefinitionId
              ? { serviceType: sourceDefinitionId, name: "" }
              : undefined
          }
          allowChangeConnector
        />
        <JobsLogItem jobInfo={jobInfo} />
      </ContentCard>
    </>
  );
};

export default SourceForm;
