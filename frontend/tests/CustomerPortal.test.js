import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";

let server;
let DocumentCard;

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    server: { middlewareMode: true },
    appType: "custom",
  });
  ({ DocumentCard } = await server.ssrLoadModule("/src/CustomerPortal.jsx"));
});

after(async () => {
  await server?.close();
});

function renderCard(overrides = {}) {
  const doc = {
    id: 1,
    category: "Mortgage Application",
    original_filename: "application.pdf",
    size_bytes: 1024,
    created_at: "2026-10-26T00:00:00Z",
    extraction_status: "COMPLETED",
    verification_status: "PENDING",
    analysis_status: "PENDING",
    extracted_text: "Loan amount: INR 3500000",
    extracted_fields: {},
    corrected_fields: {},
    ...overrides,
  };
  return renderToStaticMarkup(
    React.createElement(DocumentCard, {
      doc,
      editable: true,
      busy: false,
      drafts: {},
      setDrafts() {},
      saveFields() {},
      saveText() {},
      downloadFile() {},
      runDocAnalysis() {},
      analysing: false,
    }),
  );
}

test("document card renders with no analysis result", () => {
  const html = renderCard();
  assert.match(html, /Analysis:/);
  assert.doesNotMatch(html, /Saved analysis result/);
});

test("failed document analysis renders its error without rendering a stale result", () => {
  const html = renderCard({
    analysis_status: "FAILED",
    analysis_error: "AI safety checks are unavailable.",
    analysis_result: { analysis: { extracted_facts: ["stale finding"] } },
  });
  assert.match(html, /Analysis failed: AI safety checks are unavailable\./);
  assert.doesNotMatch(html, /Saved analysis result|stale finding/);
});

test("successful document analysis renders the existing result", () => {
  const html = renderCard({
    analysis_status: "ANALYSED",
    analysis_result: {
      analysis: {
        scenario: "document_review",
        document_type_guess: "Mortgage application",
        extracted_facts: ["Loan amount: INR 3500000"],
        discrepancies: [],
        missing_information: [],
        risk_flags: [],
        evidence: [],
        limitations: [],
        confidence: "medium",
      },
    },
  });
  assert.match(html, /Saved analysis result/);
  assert.match(html, /Loan amount: INR 3500000/);
});

test("malformed analysis result data does not crash the document card", () => {
  const html = renderCard({
    analysis_status: "ANALYSED",
    analysis_result: "invalid response",
  });
  assert.match(html, /Analysis:/);
  assert.doesNotMatch(html, /Saved analysis result/);
});
