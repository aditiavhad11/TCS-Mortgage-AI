import test from "node:test";
import assert from "node:assert/strict";
import { analysisPriorityGroups, analysisSource, retrievedEvidenceSummary, uniqueOcrFieldRows } from "./reviewerAnalysis.js";

test("identical OCR aliases render as one field while retaining every page reference", () => {
  const rows = uniqueOcrFieldRows({
    applicant_name: { value: "Divya Rathore", evidence: "Applicant Name: Divya Rathore", page_number: 1 },
    name: { value: "Divya Rathore", evidence: "Name: Divya Rathore", page_number: 2 },
    gender: { value: "Female", evidence: "Gender: Female", page_number: 1 },
  });
  assert.equal(rows.filter(row => row.canonical === "applicant_name").length, 1);
  assert.deepEqual(rows.find(row => row.canonical === "applicant_name").sources.map(source => source.page), [1, 2]);
  assert.equal(rows.length, 2);
});

test("different OCR values remain separate and are marked as a field conflict", () => {
  const rows = uniqueOcrFieldRows({
    applicant_name: { value: "Divya Rathore", evidence: "Name: Divya Rathore", page_number: 1, alternates: [{ value: "Divya R. Rathore", evidence: "Name: Divya R. Rathore", page_number: 2 }] },
  });
  const names = rows.filter(row => row.canonical === "applicant_name");
  assert.equal(names.length, 2);
  assert.ok(names.every(row => row.conflict));
  assert.deepEqual(names.map(row => row.value), ["Divya Rathore", "Divya R. Rathore"]);
  assert.deepEqual(names.map(row => row.sources[0].page), [1, 2]);
});

test("reviewer corrections do not erase the original OCR value or citation", () => {
  const rows = uniqueOcrFieldRows(
    { date_of_birth: { value: "28/11/1980", evidence: "DOB: 28/11/1980", page_number: 1 } },
    { date_of_birth: { value: "29/11/1980", source: "REVIEWER_CORRECTION" } },
  );
  assert.equal(rows.length, 2);
  assert.ok(rows.every(row => row.conflict));
  assert.ok(rows.some(row => row.value === "28/11/1980" && row.sources.some(source => source.kind === "Original OCR" && source.page === 1)));
  assert.ok(rows.some(row => row.value === "29/11/1980" && row.sources.some(source => source.kind === "Reviewer correction")));
});

test("same finding duplicates collapse, but findings with different values stay separate", () => {
  const doc = (id, filename, facts) => ({ id, filename, analysis_status: "ANALYSED", analysis_result: { analysis: { extracted_facts: facts } } });
  const groups = analysisPriorityGroups([
    doc(1, "a.pdf", [{ claim: "Income", exact_quote: "Annual income: 500000" }, { claim: "Income", exact_quote: "Annual income: 500000" }]),
    doc(2, "b.pdf", [{ claim: "Income", exact_quote: "Annual income: 700000" }]),
  ]);
  assert.equal(groups.findings.length, 2);
  assert.equal(groups.findings[0].sources.length, 0, "A filename alone must not be attached as finding provenance.");
});

test("finding source is linked only from explicit citation or a quote verified in OCR", () => {
  const document = { filename: "id.pdf", original_text: "[PAGE 3]\nApplicant: Divya Rathore" };
  assert.deepEqual(analysisSource({ exact_quote: "Applicant: Divya Rathore" }, document), { filename: "id.pdf", page: 3 });
  assert.equal(analysisSource({ claim: "Applicant name" }, document), null);
  assert.deepEqual(analysisSource({ source_reference: { filename: "kyc.pdf", page_number: 2 } }, document), { filename: "kyc.pdf", page: 2 });
});

test("retrieved evidence excerpt and document counts use only available source metadata", () => {
  assert.deepEqual(retrievedEvidenceSummary([
    { document_id: 4, filename: "policy-a.pdf" }, { document_id: 4, filename: "policy-a.pdf" }, { filename: "policy-b.pdf" },
  ]), { excerptCount: 3, sourceCount: 2 });
  assert.deepEqual(retrievedEvidenceSummary([]), { excerptCount: 0, sourceCount: 0 });
});
