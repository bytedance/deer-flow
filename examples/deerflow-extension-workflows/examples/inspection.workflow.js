// Return complete report text, not mutable file links, for exact-output review.
const evidence = await agent({stepId:'evidence',agentRef:args.complianceAgent,task:{product:args.product,referenceDate:args.referenceDate}});
await humanCheckpoint({stepId:'confirm-evidence',sourceStepId:'evidence',artifactVersion:evidence.artifactVersion});
const findings = await agent({stepId:'ingredients',agentRef:args.ingredientAgent,task:{formula:args.formula,evidence:evidence.output}});
await humanCheckpoint({stepId:'confirm-findings',sourceStepId:'ingredients',artifactVersion:findings.artifactVersion});
let report, feedback;
for (let attempt=0; attempt<2; attempt++) {
  report = await agent({stepId:`report-${attempt}`,agentRef:args.reportAgent,task:{instruction:'Return the complete report as Markdown in the output, not a file link.',evidence:evidence.output,findings:findings.output,previous:report?.output??null,feedback:feedback??null}});
  const review = await agent({stepId:`review-${attempt}`,agentRef:args.reviewerAgent,task:{report:report.output,instruction:'Return JSON with verdict ready or needs_revision and reasons.'}});
  if(review.output?.verdict==='ready') {
    await humanCheckpoint({stepId:'confirm-final-report',sourceStepId:`report-${attempt}`,artifactVersion:report.artifactVersion});
    return {status:'human_confirmed_report',report:report.output,artifactVersion:report.artifactVersion};
  }
  if(review.output?.verdict!=='needs_revision')throw Error('Unexpected reviewer verdict');
  feedback=review.output;
}
return {status:'revision_required',report:report.output};
