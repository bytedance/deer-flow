// Requires authenticated browser approval and read_workflow_artifact enabled.
await agent({stepId:'write',agentRef:'lead_agent',task:'Write a concise report to /mnt/user-data/outputs/report.md and return its path.'});
const file = await captureArtifact({stepId:'report-file',sourceStepId:'write',path:'/mnt/user-data/outputs/report.md'});
await humanCheckpoint({stepId:'confirm-report',sourceStepId:'report-file',artifactVersion:file.artifactVersion});
const review = await agent({stepId:'review',agentRef:'lead_agent',task:'Read the approved report version using read_workflow_artifact, then summarize it.',artifacts:[file.artifactVersion]});
return {artifactVersion:file.artifactVersion,sha256:file.sha256,review:review.output};
