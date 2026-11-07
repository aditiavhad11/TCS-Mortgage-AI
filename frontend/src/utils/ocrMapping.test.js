import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { mapOcrIntoForm } from "./ocrMapping.js";

const blankForm = () => ({ details: { applicant: { full_name: "", email: "", mobile: "" } } });

test("new mortgage applicants are not initialized from authenticated profile details", async () => {
  const source = await readFile(new URL("../CustomerPortal.jsx", import.meta.url), "utf8");
  const startApplication = source.slice(source.indexOf("async function startApplication()"), source.indexOf("async function openApplication("));

  assert.doesNotMatch(startApplication, /user\.(?:full_name|email|mobile)/);
  assert.match(startApplication, /const initial = blankApplication\(\)/);
});

test("OCR populates applicant fields while preserving source disagreements", () => {
  const docs = [
    { id: 1, category: "Mortgage Application", extracted_text: "Applicant: Divya Rathore", extracted_fields: {
      applicant_name: { value: "Divya Rathore", evidence: "Applicant: Divya Rathore" },
      email: { value: "divya@example.com", evidence: "divya@example.com" },
      mobile: { value: "9876543210", evidence: "9876543210" },
    } },
    { id: 2, category: "KYC", extracted_text: "Name: Divya R Rathore", extracted_fields: {
      applicant_name: { value: "Divya R Rathore", evidence: "Name: Divya R Rathore" },
    } },
  ];

  const mapped = mapOcrIntoForm(blankForm(), docs);
  assert.equal(mapped.form.details.applicant.full_name, "");
  assert.equal(mapped.form.details.applicant.email, "divya@example.com");
  assert.equal(mapped.form.details.applicant.mobile, "9876543210");
  assert.deepEqual(mapped.sources["details.applicant.full_name"].map(row => row.value), ["Divya Rathore", "Divya R Rathore"]);
  assert.match(mapped.sources["details.applicant.full_name"][0].evidence, /Divya Rathore/);
});

test("customer-entered applicant values survive document remapping and reload mapping", () => {
  const docs = [{ id: 3, extracted_text: "Name: OCR Name", extracted_fields: {
    applicant_name: { value: "OCR Name", evidence: "Name: OCR Name" },
    email: { value: "ocr@example.com", evidence: "ocr@example.com" },
    mobile: { value: "1111111111", evidence: "1111111111" },
  } }];
  const edited = { details: { applicant: { full_name: "Corrected Name", email: "customer@example.com", mobile: "2222222222" } } };

  const afterAnalysis = mapOcrIntoForm(edited, docs).form;
  const afterReload = mapOcrIntoForm(afterAnalysis, docs).form;
  assert.deepEqual(afterAnalysis.details.applicant, edited.details.applicant);
  assert.deepEqual(afterReload.details.applicant, edited.details.applicant);
});
