// OCR field names are the existing backend document field keys. Keep this
// mapping explicit so values with different meanings are never conflated.
export const OCR_TARGETS = {
  applicant_name: ["details.applicant.full_name"], gender: ["details.applicant.gender"], date_of_birth: ["details.applicant.date_of_birth"], age: ["details.applicant.age"],
  email: ["details.applicant.email"], mobile: ["details.applicant.mobile"], residential_address: ["details.applicant.residential_address"],
  employer_name: ["details.employment.employer_name"], employment_type: ["details.employment.employment_type"], occupation: ["details.employment.occupation"], employment_duration: ["details.employment.business_duration"],
  annual_income: ["annual_income", "details.employment.annual_income"], monthly_income: ["details.employment.monthly_income"], other_income: ["details.employment.other_income"],
  loan_amount: ["requested_loan"], loan_tenure: ["tenure_years"], loan_type: ["product_name"], loan_purpose: ["details.loan.purpose"], down_payment: ["details.loan.down_payment"],
  property_address: ["property_address"], property_type: ["details.property.property_type"], ownership_relationship: ["details.property.ownership_relationship"],
  property_value: ["property_value"], purchase_price: ["property_value"], agreement_value: ["property_value"], valuation_amount: ["details.property.estimated_market_value"], seller_name: ["details.property.seller_builder"], property_identifier: ["details.property.registration_details"], registration_number: ["details.property.registration_details"],
  account_holder: ["details.bank.account_holder_name"], bank_name: ["details.bank.bank_name"], ifsc: ["details.bank.ifsc"], interest_rate: ["interest_rate"],
};

export function evidencePage(doc, evidence) {
  const text = doc.extracted_text || "";
  const index = evidence ? text.indexOf(evidence) : -1;
  const prefix = index >= 0 ? text.slice(0, index) : text;
  const pages = [...prefix.matchAll(/\[PAGE\s+(\d+)\]/gi)];
  return pages.length ? pages[pages.length - 1][1] : null;
}

export function targetValue(target, value) {
  if (target === "details.applicant.date_of_birth") {
    const match = String(value ?? "").match(/^(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{4})$/);
    if (match) return `${match[3]}-${match[2].padStart(2, "0")}-${match[1].padStart(2, "0")}`;
  }
  if (target === "details.employment.employment_type") {
    const normalized = String(value ?? "").trim().toLowerCase();
    const types = { salaried: "Salaried", "self-employed": "Self-employed", selfemployed: "Self-employed", "business owner": "Business owner", professional: "Professional", other: "Other" };
    return types[normalized] || value;
  }
  if (target === "details.property.property_type") {
    const normalized = String(value ?? "").trim().toLowerCase();
    if (/apartment|flat/.test(normalized)) return "Apartment / Flat";
    if (/independent\s+house/.test(normalized)) return "Independent House";
    if (/plot|land/.test(normalized)) return "Plot / Land";
    if (/under.?construction/.test(normalized)) return "Under-construction property";
    if (/other/.test(normalized)) return "Other";
  }
  if (target === "details.loan.purpose") {
    const normalized = String(value ?? "").trim().toLowerCase();
    if (/purchase/.test(normalized)) return "Home Purchase";
    if (/construction/.test(normalized)) return "Home Construction";
    if (/improvement|renovation/.test(normalized)) return "Home Improvement";
    if (/extension/.test(normalized)) return "Home Extension";
    if (/balance\s+transfer/.test(normalized)) return "Balance Transfer";
  }
  if (target !== "tenure_years") return value;
  const match = String(value ?? "").match(/[\d.]+/);
  if (!match) return "";
  const n = Number(match[0]);
  return /month/i.test(String(value)) ? String(Math.round(n / 12)) : String(n);
}

export function collectOcrSources(docs) {
  const sources = {};
  docs.forEach(doc => Object.entries(doc.extracted_fields || {}).forEach(([key, field]) => {
    (OCR_TARGETS[key] || []).forEach(target => {
      const corrected = doc.corrected_fields?.[key]?.value;
      const entries = [{ value: corrected ?? field?.value, original: field?.value, corrected: corrected !== undefined, evidence: field?.evidence || "", page: field?.page_number || evidencePage(doc, field?.evidence) }, ...(corrected === undefined ? field?.alternates || [] : [])];
      entries.forEach(entry => {
        if (entry.value === undefined || entry.value === null || entry.value === "") return;
        const evidence = entry.evidence || field?.evidence || "";
        (sources[target] ||= []).push({ doc, key, value: targetValue(target, entry.value), original: entry.original ?? entry.value ?? field?.value, corrected: Boolean(entry.corrected), evidence, page: entry.page_number || entry.page || evidencePage(doc, evidence) });
      });
    });
  }));
  return sources;
}

export function assignTarget(form, target, value) {
  if (!target.startsWith("details.")) return { ...form, [target]: value };
  const [, section, key] = target.split(".");
  return { ...form, details: { ...form.details, [section]: { ...(form.details?.[section] || {}), [key]: value } } };
}

export function mapOcrIntoForm(form, docs) {
  const sources = collectOcrSources(docs);
  let next = form;
  Object.entries(sources).forEach(([target, rows]) => {
    const current = target.split(".").reduce((obj, part) => obj?.[part], next);
    const unique = [...new Set(rows.map(row => String(row.value)))];
    if (unique.length === 1 && (current === "" || current == null || current === 0)) next = assignTarget(next, target, rows[0].value);
  });
  return { form: next, sources };
}
