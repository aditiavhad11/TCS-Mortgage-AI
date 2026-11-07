const SOURCE_KEYS = new Set([
  "source_reference", "source_document", "source_filename", "source_category",
  "filename", "document_name", "document_id", "page_number", "chunk_index",
]);

export function analysisArray(value) {
  return Array.isArray(value) ? value : [];
}

export function fieldLabel(value) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

export function canonicalField(field) {
  const key = String(field || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  const aliases = {
    name: "applicant_name", full_name: "applicant_name", customer_name: "applicant_name",
    sex: "gender", dob: "date_of_birth", birth_date: "date_of_birth",
  };
  return aliases[key] || key;
}

const normalizedValue = value => String(value ?? "").trim().replace(/\s+/g, " ").toLocaleLowerCase();
const recordOrEmpty = value => value && typeof value === "object" && !Array.isArray(value) ? value : {};

function sourceRows(entry, key, correctedEntry) {
  const rows = [];
  const valueOf = value => value && typeof value === "object" && !Array.isArray(value) ? value.value : value;
  const originalValue = valueOf(entry);
  const correctedValue = valueOf(correctedEntry);
  if (correctedEntry !== undefined && normalizedValue(correctedValue) !== normalizedValue(originalValue)) {
    rows.push({ value: correctedValue, kind: "Reviewer correction", evidence: "", page: null, key, editable: true });
    rows.push({ value: originalValue, kind: "Original OCR", evidence: entry?.evidence || "", page: entry?.page_number || null, key, editable: false });
  } else if (correctedEntry !== undefined) {
    rows.push({ value: correctedValue, kind: "Reviewer correction", evidence: "", page: null, key, editable: true });
    rows.push({ value: originalValue, kind: "Original OCR", evidence: entry?.evidence || "", page: entry?.page_number || null, key, editable: false });
  } else {
    rows.push({ value: originalValue, kind: "Original OCR", evidence: entry?.evidence || "", page: entry?.page_number || null, key, editable: true });
  }
  if (Array.isArray(entry?.alternates)) {
    entry.alternates.forEach(alternate => rows.push({ value: valueOf(alternate), kind: "Original OCR", evidence: alternate?.evidence || "", page: alternate?.page_number || null, key, editable: true }));
  }
  return rows.filter(row => row.value !== undefined && row.value !== null && String(row.value).trim() !== "");
}

/** Group aliases and repeated OCR values without discarding their evidence or disagreements. */
export function uniqueOcrFieldRows(extracted = {}, corrected = {}) {
  extracted = recordOrEmpty(extracted);
  corrected = recordOrEmpty(corrected);
  const candidates = [];
  [...new Set([...Object.keys(extracted || {}), ...Object.keys(corrected || {})])].forEach(key => {
    const entry = extracted?.[key];
    sourceRows(entry, key, corrected?.[key]).forEach(source => candidates.push({ canonical: canonicalField(key), source }));
  });
  const groups = new Map();
  for (const { canonical, source } of candidates) {
    const identity = `${canonical}\u001f${normalizedValue(source.value)}`;
    let row = groups.get(identity);
    if (!row) {
      row = { id: identity, canonical, label: fieldLabel(canonical), value: source.value, keys: [], sources: [] };
      groups.set(identity, row);
    }
    if (!row.keys.includes(source.key)) row.keys.push(source.key);
    if (!row.sources.some(item => item.kind === source.kind && item.evidence === source.evidence && item.page === source.page && item.key === source.key)) {
      row.sources.push({ kind: source.kind, evidence: source.evidence, page: source.page, key: source.key, editable: source.editable });
    }
  }
  const rows = [...groups.values()];
  const valuesByField = new Map();
  rows.forEach(row => valuesByField.set(row.canonical, (valuesByField.get(row.canonical) || 0) + 1));
  rows.forEach(row => {
    row.conflict = valuesByField.get(row.canonical) > 1;
    row.conflictMessage = row.sources.some(source => source.kind === "Reviewer correction")
      ? "Reviewer-corrected and original OCR values differ. Review the source before relying on the correction."
      : "Different values were extracted for this field. Compare each source before correcting.";
  });
  return rows;
}

function substantive(value) {
  if (Array.isArray(value)) return value.map(substantive);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.keys(value).sort().filter(key => !SOURCE_KEYS.has(key.toLowerCase())).map(key => [key, substantive(value[key])]));
}

export function analysisTitle(item) {
  if (typeof item === "string") return item.trim() || "Analysis observation";
  if (!item || typeof item !== "object" || Array.isArray(item)) return "Analysis observation";
  const explicit = item.title || item.name || item.label || item.claim || item.code || item.field_name || item.field;
  if (explicit) return String(explicit);
  const explanation = item.description || item.finding || item.message || item.summary;
  if (explanation) return String(explanation).split(/(?<=[.!?])\s+/)[0].slice(0, 100);
  return "Analysis observation";
}

export function analysisSnippet(item) {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object" || Array.isArray(item)) return "";
  return item.description || item.finding || item.message || item.summary || "";
}

export function analysisKey(item) {
  const material = substantive(item);
  if (typeof material === "string") return material.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  return JSON.stringify(material).toLowerCase();
}

function quotePage(text, quote) {
  if (!text || !quote) return null;
  const compact = value => String(value).replace(/\s+/g, " ").trim();
  const normalizedText = compact(text);
  const normalizedQuote = compact(quote);
  const offset = normalizedText.toLocaleLowerCase().indexOf(normalizedQuote.toLocaleLowerCase());
  if (offset < 0) return null;
  const before = normalizedText.slice(0, offset);
  const markers = [...before.matchAll(/\[PAGE\s+(\d+)\]/gi)];
  return markers.length ? Number(markers.at(-1)[1]) : null;
}

/** Link findings only to explicit response provenance or a quote verified in this document's OCR. */
export function analysisSource(item, document) {
  const reference = item && typeof item === "object" && !Array.isArray(item)
    ? item.source_reference || item.source_document || {} : {};
  if (reference.filename || reference.document_name) {
    return { filename: reference.filename || reference.document_name, page: reference.page_number || null };
  }
  const quote = item && typeof item === "object" ? item.exact_quote : "";
  const page = quotePage(document?.original_text || "", quote);
  if (quote && page !== null) return { filename: document.filename || "Source document", page };
  if (quote && document?.original_text && String(document.original_text).includes(quote)) return { filename: document.filename || "Source document", page: null };
  return null;
}

export function analysisPriorityGroups(documents = []) {
  const groups = { conflicts: [], missing: [], findings: [], checks: [] };
  const seen = new Map();
  for (const document of documents) {
    if (document.analysis_status !== "ANALYSED") continue;
    const analysis = document.analysis_result?.analysis;
    if (!analysis || typeof analysis !== "object") continue;
    const candidates = [
      ...analysisArray(analysis.discrepancies).map(item => ({ group: "conflicts", item, priority: 0 })),
      ...analysisArray(analysis.missing_information).map(item => ({ group: "missing", item, priority: 1 })),
      ...analysisArray(analysis.risk_flags).map(item => ({ group: "findings", item, priority: 0 })),
      ...analysisArray(analysis.extracted_facts).map(item => ({ group: "findings", item, priority: 1 })),
      ...analysisArray(analysis.recommended_reviewer_checks).map(item => ({ group: "checks", item, priority: 2 })),
    ];
    for (const { group, item, priority } of candidates) {
      const key = `${group}:${analysisKey(item) || document.id}`;
      const source = analysisSource(item, document);
      const existing = seen.get(key);
      if (existing) {
        if (source && !existing.sources.some(value => value.filename === source.filename && value.page === source.page)) existing.sources.push(source);
        existing.priority = Math.min(existing.priority, priority);
        const rank = { conflicts: 0, missing: 1, findings: 2, checks: 3 };
        if (rank[group] < rank[existing.group]) {
          groups[existing.group] = groups[existing.group].filter(value => value !== existing);
          existing.group = group;
          groups[group].push(existing);
        }
        continue;
      }
      const entry = { key, group, item, category: document.category, priority, sources: source ? [source] : [] };
      seen.set(key, entry);
      groups[group].push(entry);
    }
  }
  groups.findings.sort((left, right) => left.priority - right.priority);
  return groups;
}

export function retrievedEvidenceSummary(evidence = []) {
  const items = Array.isArray(evidence) ? evidence : [];
  const sources = new Set(items.map(item => item?.document_id ?? item?.filename).filter(value => value != null));
  return { excerptCount: items.length, sourceCount: sources.size };
}
