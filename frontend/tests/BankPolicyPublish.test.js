import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";

let server;
let BankPolicyDirectory;

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    server: { middlewareMode: true },
    appType: "custom",
  });
  ({ BankPolicyDirectory } = await server.ssrLoadModule(
    "/src/BankAdminPortal.jsx",
  ));
});

after(async () => {
  await server?.close();
});

test("internal policy directory exposes an explicit customer-safe publication action and current status", () => {
  const html = renderToStaticMarkup(
    React.createElement(BankPolicyDirectory, {
      policies: [
        {
          id: 7,
          title: "Policy",
          policy_version: "1.0",
          category: "Mortgage",
          active: true,
          customer_visible: false,
          customer_summary: "",
          source_filename: "home-loan-policy.pdf",
          has_source_pdf: true,
          created_at: "2026-10-26T00:00:00Z",
          text_status: "TEXT_SAVED",
          indexing_status: "COMPLETED",
          indexed_chunks: 4,
          expected_chunks: 4,
          embedding_status: "COMPLETED",
          customer_availability: "INTERNAL_ONLY",
        },
      ],
      onRefresh() {},
    }),
  );

  assert.match(html, /Internal only/);
  assert.match(html, /Customer Assistant: Unavailable - internal only/);
  assert.match(html, /Generic title: choose an accurate customer-safe title/);
  assert.match(html, /Publish customer-safe version/);
  assert.match(html, /Download source PDF/);
  assert.doesNotMatch(html, /<td>7<\/td>/);
});
