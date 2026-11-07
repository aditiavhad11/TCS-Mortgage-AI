import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";

let server;
let ExtractedFields;
let AnalysisEvidence;
let AnalysisSummary;
let ReviewerReviewWorkspace;

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    server: { middlewareMode: true, hmr: false },
    appType: "custom",
  });
  ({
    ExtractedFields,
    AnalysisEvidence,
    AnalysisSummary,
    default: ReviewerReviewWorkspace,
  } = await server.ssrLoadModule("/src/ReviewerReviewWorkspace.jsx"));
});

after(async () => {
  await server?.close();
});

const render = (element) =>
  renderToStaticMarkup(React.createElement(element.type, element.props));

test("identical applicant name, gender, DOB, and age are each rendered once", () => {
  const html = render({
    type: ExtractedFields,
    props: {
      document: {
        extracted_fields: {
          applicant_name: {
            value: "Divya Rathore",
            evidence: "Applicant Name: Divya Rathore",
            page_number: 1,
          },
          name: {
            value: "Divya Rathore",
            evidence: "Name: Divya Rathore",
            page_number: 2,
          },
          gender: {
            value: "Female",
            evidence: "Gender: Female",
            page_number: 1,
          },
          date_of_birth: {
            value: "28/11/1980",
            evidence: "Date of Birth: 28/11/1980",
            page_number: 1,
          },
          age: { value: "46 years", evidence: "Age: 46 years", page_number: 1 },
        },
      },
    },
  });
  for (const value of ["Divya Rathore", "Female", "28/11/1980", "46 years"]) {
    assert.equal(
      (
        html.match(
          new RegExp(
            `<dd>${value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}</dd>`,
            "g",
          ),
        ) || []
      ).length,
      1,
      `${value} should be displayed once as a field`,
    );
  }
  assert.match(html, /Page 1/);
  assert.match(html, /Page 2/);
});

test("conflicting OCR values remain visible with their evidence references", () => {
  const html = render({
    type: ExtractedFields,
    props: {
      document: {
        extracted_fields: {
          applicant_name: {
            value: "Divya Rathore",
            evidence: "Name: Divya Rathore",
            page_number: 1,
            alternates: [
              {
                value: "Divya R Rathore",
                evidence: "Name: Divya R Rathore",
                page_number: 3,
              },
            ],
          },
        },
      },
    },
  });
  assert.match(html, /Different values were extracted for this field/);
  assert.match(html, /Divya Rathore/);
  assert.match(html, /Divya R Rathore/);
  assert.match(html, /Page 1/);
  assert.match(html, /Page 3/);
});

test("retrieved application excerpts show source metadata and expandable full text", () => {
  const excerpt = "Salary credits shown in the statement. ".repeat(25);
  const html = render({
    type: AnalysisEvidence,
    props: {
      document: {
        id: 14,
        filename: "bank-statement.pdf",
        category: "Bank Statement",
        analysis_status: "ANALYSED",
        analysis_result: {
          provider: "NVIDIA",
          analysis: {
            document_type_guess: "Bank statement",
            confidence: "medium",
            extracted_facts: [],
            discrepancies: [],
            missing_information: [],
            risk_flags: [],
            evidence: [],
            limitations: [],
          },
          retrieved_application_evidence: [
            {
              document_id: 8,
              filename: "salary-source.pdf",
              category: "Bank Statement",
              page_number: 4,
              source_variant: "ORIGINAL_OCR",
              text: excerpt,
            },
          ],
          document_retrieval_status: "RETRIEVED",
        },
      },
    },
  });
  assert.match(html, /Retrieved Application Evidence/);
  assert.match(html, /salary-source\.pdf/);
  assert.match(html, /Page 4/);
  assert.match(html, /Bank Statement/);
  assert.match(html, /not independently verify/);
  assert.match(html, /Show full excerpt/);
  assert.match(
    html,
    new RegExp(excerpt.slice(-40).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
  );
});

test("empty retrieved evidence is reported without fabricated examples", () => {
  const html = render({
    type: AnalysisEvidence,
    props: {
      document: {
        id: 15,
        filename: "empty.pdf",
        analysis_status: "ANALYSED",
        analysis_result: {
          analysis: {
            document_type_guess: "Unknown",
            extracted_facts: [],
            discrepancies: [],
            missing_information: [],
            risk_flags: [],
            evidence: [],
            limitations: [],
          },
          retrieved_application_evidence: [],
          document_retrieval_status:
            "NO_RELEVANT_APPLICATION_DOCUMENT_EVIDENCE",
        },
      },
    },
  });
  assert.match(html, /No relevant application-document evidence was found/);
  assert.doesNotMatch(html, /salary-source\.pdf/);
});

test("AI missing and conflict observations retain their classifications and caution", () => {
  const html = render({
    type: AnalysisSummary,
    props: {
      documents: [
        {
          id: 1,
          filename: "application.pdf",
          category: "Mortgage Application",
          analysis_status: "ANALYSED",
          analysis_result: {
            analysis: {
              extracted_facts: [],
              risk_flags: [],
              recommended_reviewer_checks: [],
              missing_information: [
                {
                  type: "field",
                  field_name: "date_of_birth",
                  summary: "The source does not show a date of birth.",
                },
              ],
              discrepancies: [
                {
                  claim: "Income statements differ",
                  source_a: "INR 500,000",
                  source_b: "INR 700,000",
                },
              ],
            },
          },
        },
      ],
      onReanalyse() {},
      reanalysingDocs: {},
      reanalysisErrors: {},
    },
  });
  assert.match(html, /Missing information/);
  assert.match(html, /Missing field/);
  assert.match(html, /Conflicting evidence/);
  assert.match(html, /not confirmed discrepancies/);
  assert.match(html, /INR 500,000/);
  assert.match(html, /INR 700,000/);
  assert.match(html, /Source reference not linked by the analysis/);
});

test("reviewer workspace renders API document fields without an undefined fields reference", () => {
  const html = renderToStaticMarkup(
    React.createElement(ReviewerReviewWorkspace, {
      initial: {
        id: 9,
        reference: "REVIEW-9",
        status: "IN_REVIEW",
        documents: [
          {
            id: 14,
            filename: "identity.pdf",
            category: "KYC",
            extraction_status: "COMPLETED",
            verification_status: "PENDING",
            analysis_status: "NEEDS_REANALYSIS",
            extracted_fields: {
              applicant_name: {
                value: "Divya Rathore",
                evidence: "Name: Divya Rathore",
                page_number: 1,
              },
            },
            corrected_fields: {},
            field_correction_history: [],
            original_text: "[PAGE 1]\nName: Divya Rathore",
            extracted_text: "[PAGE 1]\nName: Divya Rathore",
          },
        ],
        details: {},
        customer: {},
        history: [],
      },
      token: "test-token",
      onBack() {},
      onRefresh() {},
    }),
  );
  assert.match(html, /Documents and OCR/);
  assert.match(html, /Applicant Name/);
  assert.match(html, /Reviewer correction/);
  assert.match(html, /Reanalyse/);
});

test("reviewer workspace handles a missing or malformed document list", () => {
  const html = renderToStaticMarkup(
    React.createElement(ReviewerReviewWorkspace, {
      initial: {
        id: 10,
        reference: "REVIEW-10",
        status: "IN_REVIEW",
        documents: null,
        details: {},
        customer: {},
        history: [],
      },
      token: "test-token",
      onBack() {},
      onRefresh() {},
    }),
  );
  assert.match(html, /No documents have been uploaded for this application/);
});
