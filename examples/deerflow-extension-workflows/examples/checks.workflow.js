// Paste this function body into the Script workflows page (no imports required).
const evidence = await agent({
  stepId: 'evidence',
  agentRef: args.researchAgent || 'lead_agent',
  task: {instruction: 'Identify applicable requirements and cite source evidence. Return JSON.', product: args.product}
});
log('Evidence collected; it has not been approved by a human.');
const checks = await parallel([
  () => agent({stepId:'ingredients',agentRef:args.checkAgent || 'lead_agent',task:{instruction:'Check the formula against this evidence. Return JSON.',formula:args.formula,evidence:evidence.output}}),
  () => agent({stepId:'claims',agentRef:args.checkAgent || 'lead_agent',task:{instruction:'Check the proposed claims against this evidence. Return JSON.',claims:args.claims,evidence:evidence.output}})
]);
let review;
for (let attempt = 0; attempt < 2; attempt++) {
  review = await agent({stepId:'review-'+attempt,agentRef:args.reviewAgent || 'lead_agent',task:{instruction:'Review the evidence and findings. Return a JSON object with verdict: needs_revision or ready_for_human_review. Never approve the product.',evidence:evidence.output,findings:checks.map(x=>x.output),previousReview:review?.output || null}});
  if (review.output?.verdict !== 'needs_revision') break;
}
if (review.output?.verdict === 'needs_revision') {
  return {status:'revision_required',evidence:evidence.output,findings:checks.map(x=>x.output),review:review.output,humanApproved:false};
}
return {status:'awaiting_human_review',evidence:evidence.output,findings:checks.map(x=>x.output),review:review.output,humanApproved:false};
