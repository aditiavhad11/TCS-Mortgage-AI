import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";

let server;
let AnalysisSummary;

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    server: { middlewareMode: true },
    appType: "custom",
  });
  ({ AnalysisSummary } = await server.ssrLoadModule(
    "/src/ReviewerReviewWorkspace.jsx",
  ));
});

after(async () => {
  await server?.close();
});

function render(documents, props = {}) {
  return renderToStaticMarkup(
    React.createElement(AnalysisSummary, {
      documents,
      onReanalyse() {},
      reanalysingDocs: {},
      reanalysisErrors: {},
      ...props,
    }),
  );
}

test("stale reviewer documents have a per-document reanalysis action", () => {
  const html = render([
    {
      id: 7,
      filename: "salary.pdf",
      category: "Income",
      analysis_status: "NEEDS_REANALYSIS",
    },
  ]);
  assert.match(html, /Documents requiring reanalysis/);
  assert.match(html, /salary\.pdf/);
  assert.match(html, />Reanalyse<\/button>/);
});

test("reanalysis action is disabled and labeled while the document is processing", () => {
  const html = render(
    [
      {
        id: 7,
        filename: "salary.pdf",
        category: "Income",
        analysis_status: "NEEDS_REANALYSIS",
      },
    ],
    {
      reanalysingDocs: { 7: true },
    },
  );
  assert.match(html, /disabled/);
  assert.match(html, /Reanalysing/);
});

test("failed reanalysis retains the stale status and displays the failure", () => {
  const html = render([
    {
      id: 7,
      filename: "salary.pdf",
      category: "Income",
      analysis_status: "NEEDS_REANALYSIS",
      analysis_error: "AI service timed out.",
    },
  ]);
  assert.match(html, /AI service timed out\./);
  assert.match(html, /Reanalyse/);
});

test("current documents do not show an unnecessary reanalysis action", () => {
  const html = render([
    {
      id: 7,
      filename: "salary.pdf",
      category: "Income",
      analysis_status: "ANALYSED",
    },
  ]);
  assert.doesNotMatch(html, /Reanalyse/);
});
