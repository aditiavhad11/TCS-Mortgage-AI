import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";
import {
  policyQuestionPayload,
  initialPolicySelection,
} from "../src/utils/policyAssistant.js";

let server;
let PolicySelector;

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    server: { middlewareMode: true },
    appType: "custom",
  });
  ({ PolicySelector } = await server.ssrLoadModule(
    "/src/CustomerPolicyAssistant.jsx",
  ));
});

after(async () => {
  await server?.close();
});

test("policy discovery renders customer safe metadata and selected state without exposing identifiers", () => {
  const html = renderToStaticMarkup(
    React.createElement(PolicySelector, {
      policies: [
        {
          id: 7812,
          title: "Home Loan Documents",
          category: "Documents",
          description: "Provide recent salary slips and bank statements.",
          version: "3.2",
          status: "Active",
          bank_name: "Suryodaya Housing Finance Ltd",
          source_filename: "home-loan-policy.pdf",
        },
      ],
      selectedPolicyId: "7812",
    }),
  );
  assert.match(html, /Home Loan Documents/);
  assert.match(html, /Provide recent salary slips and bank statements\./);
  assert.match(html, /Documents \| v3\.2 \| Active/);
  assert.match(html, /Suryodaya Housing Finance Ltd/);
  assert.match(html, /PDF: home-loan-policy\.pdf/);
  assert.match(html, /aria-pressed="true"/);
  assert.doesNotMatch(html, />7812</);
  assert.match(html, /All available policies/);
});

test("policy discovery shows loading, API failure, and empty states", () => {
  assert.match(
    renderToStaticMarkup(
      React.createElement(PolicySelector, { loading: true }),
    ),
    /Loading available policies/,
  );
  assert.match(
    renderToStaticMarkup(
      React.createElement(PolicySelector, {
        error: "Could not load policies.",
      }),
    ),
    /Could not load policies/,
  );
  assert.match(
    renderToStaticMarkup(React.createElement(PolicySelector, { policies: [] })),
    /No customer-visible policies are currently available/,
  );
});

test("chat request carries the selected policy and application scope without changing other chat fields", () => {
  assert.deepEqual(
    policyQuestionPayload({
      question: "What does this policy say?",
      applicationId: "42",
      policyId: "7812",
      recentQuestions: ["What documents are required?"],
    }),
    {
      question: "What does this policy say?",
      application_id: 42,
      policy_id: 7812,
      recent_questions: ["What documents are required?"],
    },
  );
  assert.deepEqual(policyQuestionPayload({ question: "General question" }), {
    question: "General question",
    recent_questions: [],
  });
});

test("one eligible policy is selected automatically while multiple policies require customer choice", () => {
  assert.equal(initialPolicySelection([{ id: 7812 }]), "7812");
  assert.equal(initialPolicySelection([{ id: 7812 }, { id: 7813 }]), "");
});
