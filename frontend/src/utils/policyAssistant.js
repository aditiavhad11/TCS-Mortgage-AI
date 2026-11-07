export function policyDescription(value) {
  const description = String(value || "").replace(/\s+/g, " ").trim();
  return description;
}

export function initialPolicySelection(policies = []) {
  return policies.length === 1 && Number.isInteger(policies[0]?.id) ? String(policies[0].id) : "";
}

export function policyQuestionPayload({ question, applicationId = "", policyId = "", recentQuestions = [] }) {
  return {
    question,
    ...(applicationId ? { application_id: Number(applicationId) } : {}),
    ...(policyId ? { policy_id: Number(policyId) } : {}),
    recent_questions: recentQuestions,
  };
}
