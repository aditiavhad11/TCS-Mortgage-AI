import { Fragment, useEffect, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  FileText,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import ScenarioPanel from "./ScenarioPanel";
import { notifyError, notifySuccess } from "./ToastProvider";
import { money } from "./utils/format";
import {
  analysisArray,
  analysisKey,
  analysisPriorityGroups,
  analysisSnippet,
  analysisSource,
  analysisTitle,
  fieldLabel,
  retrievedEvidenceSummary,
  uniqueOcrFieldRows,
} from "./utils/reviewerAnalysis";
import "./reviewer-corrections.css";

const API = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1"
).replace(/\/$/, "");
const TERMINAL = new Set(["COMPLETED", "CLOSED"]);

async function request(path, token, options = {}) {
  const headers = new Headers(options.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API}${path}`, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("json")
    ? await response.json()
    : await response.text();
  if (!response.ok)
    throw Error(body?.detail || `Request failed (${response.status})`);
  return body;
}

function historyLabel(value) {
  const labels = {
    START_REVIEW: "Review started",
    REQUEST_DOCUMENTS: "Additional information requested",
    RECOMMEND_APPROVE: "Recommended approval",
    RECOMMEND_DECLINE: "Recommended rejection",
    ESCALATE: "Escalated for further review",
    COMPLETE: "Review completed",
    ADD_NOTE: "Reviewer note saved",
    DOCUMENT_VERIFIED: "Document verified",
    DOCUMENT_NEEDS_REVIEW: "Document flagged for review",
    DOCUMENT_REJECTED: "Document rejected",
    FINDING_RECORDED: "Reviewer finding recorded",
    CHECKLIST_SAVED: "Review checklist saved",
    KYC_VERIFIED: "KYC verified",
    KYC_REJECTED: "KYC rejected",
    KYC_NEEDS_REVIEW: "KYC flagged for review",
  };
  return labels[value] || fieldLabel(value);
}

function dateTime(value) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not recorded" : date.toLocaleString();
}

function displayAnalysisValue(value) {
  if (value == null) return "Not provided";
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  )
    return String(value);
  if (Array.isArray(value)) return value.map(displayAnalysisValue).join("; ");
  return Object.entries(value)
    .map(([key, item]) => `${fieldLabel(key)}: ${displayAnalysisValue(item)}`)
    .join(" · ");
}

function conciseFindingTitle(item, document) {
  const title = analysisTitle(item).trim();
  if (typeof item === "string")
    return title.length <= 88 ? title : `${title.slice(0, 85).trimEnd()}…`;
  if (title.length <= 88) return title;
  const explanation = analysisSnippet(item).trim();
  if (explanation) return `${explanation.slice(0, 85).trimEnd()}…`;
  const entry = item && typeof item === "object" ? item : {};
  return entry.field_name || entry.field
    ? fieldLabel(entry.field_name || entry.field)
    : `${fieldLabel(document.category || "Document")} observation`;
}

function conciseFindingExplanation(item) {
  const snippet = analysisSnippet(item).trim();
  return snippet.length <= 140 ? snippet : "";
}

function missingItemLabel(item) {
  if (!item || typeof item !== "object" || Array.isArray(item))
    return "Missing information identified by analysis";
  const kind = String(
    item.missing_type || item.item_type || item.kind || item.type || "",
  ).toLowerCase();
  if (/document/.test(kind) || item.document_name) return "Missing document";
  if (/field/.test(kind) || item.field_name || item.field)
    return "Missing field";
  if (/unspecified|not_specified|source/.test(kind))
    return "Not specified in source";
  return "Missing information identified by analysis";
}

function findingComparison(item) {
  if (!item || typeof item !== "object" || Array.isArray(item)) return null;
  const pairs = [
    ["source_a", "source_b"],
    ["value_a", "value_b"],
    ["document_a", "document_b"],
    ["source_1", "source_2"],
  ];
  const pair = pairs.find(
    ([left, right]) => item[left] != null && item[right] != null,
  );
  return pair
    ? pair.map((key) => ({
        label: fieldLabel(key),
        value: displayAnalysisValue(item[key]),
      }))
    : null;
}

function analysisGroup(document, analysis) {
  const category =
    `${document.category || ""} ${document.category_label || ""} ${analysis?.scenario || ""} ${analysis?.document_type_guess || ""}`.toLowerCase();
  if (/property|valuation|title|ltv/.test(category))
    return "Property Valuation";
  if (/income|tax|salary|itr|bank statement/.test(category))
    return "Income & Tax Validation";
  if (/terms|disclosure|agreement|mortgage/.test(category))
    return "Mortgage Terms & Conditions";
  return "Extracted Facts";
}

function AnalysisFindingList({ items, document }) {
  if (!items.length) return null;
  return (
    <ul className="review-analysis-compact-list">
      {items.map((item, index) => {
        const entry =
          item && typeof item === "object" && !Array.isArray(item) ? item : {};
        const values = Object.entries(entry).filter(
          ([key]) =>
            ![
              "title",
              "name",
              "label",
              "claim",
              "code",
              "field_name",
              "field",
              "description",
              "finding",
              "message",
              "summary",
              "severity",
              "status",
              "source_reference",
              "source_document",
              "page_number",
              "follow_up",
              "recommended_action",
              "exact_quote",
            ].includes(key),
        );
        const source = entry.source_reference || entry.source_document;
        const snippet = analysisSnippet(item);
        return (
          <li key={`${document.id}-${index}`}>
            <details className="review-analysis-finding">
              <summary>
                <span>{analysisTitle(item)}</span>
                {entry.severity && (
                  <span
                    className={`review-badge review-severity-${String(entry.severity).toLowerCase()}`}
                  >
                    {fieldLabel(String(entry.severity))}
                  </span>
                )}
                {entry.status && (
                  <span className="review-badge">
                    {fieldLabel(String(entry.status))}
                  </span>
                )}
                {source && (
                  <small>
                    {source.filename ||
                      source.document_name ||
                      document.filename}
                    {source.page_number ? ` · p. ${source.page_number}` : ""}
                  </small>
                )}
              </summary>
              {snippet && <p>{snippet}</p>}
              {values.length > 0 && (
                <dl className="review-analysis-values">
                  {values.map(([key, value]) => (
                    <div key={key}>
                      <dt>{fieldLabel(key)}</dt>
                      <dd>{displayAnalysisValue(value)}</dd>
                    </div>
                  ))}
                </dl>
              )}
              {entry.exact_quote && (
                <blockquote>{entry.exact_quote}</blockquote>
              )}
              {entry.follow_up && (
                <p>
                  <b>Reviewer follow-up from analysis:</b>{" "}
                  {displayAnalysisValue(entry.follow_up)}
                </p>
              )}
              {entry.recommended_action && (
                <p>
                  <b>Suggested check from analysis:</b>{" "}
                  {displayAnalysisValue(entry.recommended_action)}
                </p>
              )}
            </details>
          </li>
        );
      })}
    </ul>
  );
}

export function ExtractedFields({
  document,
  rows: providedRows,
  terminal = false,
  fieldDrafts = {},
  onDraftChange = () => {},
}) {
  const rows = Array.isArray(providedRows)
    ? providedRows
    : uniqueOcrFieldRows(document.extracted_fields, document.corrected_fields);
  if (!rows.length)
    return (
      <p>
        No structured fields were extracted. Review the original OCR text below.
      </p>
    );
  return (
    <dl className="review-extracted-fields">
      {rows.map((row) => (
        <div
          className={row.conflict ? "review-field-conflict" : ""}
          key={row.id}
        >
          <dt>
            {row.label}
            {row.sources.some(
              (source) => source.kind === "Reviewer correction",
            ) && <span className="review-correction-badge">Corrected</span>}
          </dt>
          <dd>{String(row.value)}</dd>
          {row.conflict && (
            <dd className="review-field-conflict-note">
              {row.conflictMessage}
            </dd>
          )}
          {row.sources.map((source, index) => (
            <Fragment
              key={`${source.key}-${source.kind}-${source.page || "page"}-${index}`}
            >
              {source.kind === "Original OCR" && source.evidence && (
                <dd className="review-evidence-quote">
                  {source.evidence}
                  {source.key !== row.canonical
                    ? ` · field label: ${fieldLabel(source.key)}`
                    : ""}
                </dd>
              )}
              {source.page && (
                <dd className="review-page-reference">
                  {source.kind} · Page {source.page}
                </dd>
              )}
            </Fragment>
          ))}
          {!terminal && row.sources.some((source) => source.editable) && (
            <dd className="review-correction-input">
              <label>
                Reviewer correction
                <input
                  aria-label={`Reviewer correction ${row.label}`}
                  type={typeof row.value === "number" ? "number" : "text"}
                  value={fieldDrafts[row.id] ?? String(row.value)}
                  onChange={(event) => onDraftChange(row, event.target.value)}
                />
              </label>
            </dd>
          )}
        </div>
      ))}
    </dl>
  );
}

function DecisionDialog({ kind, onCancel, onConfirm, busy }) {
  const labels = {
    recommend_approve: "Recommend approval",
    recommend_decline: "Recommend rejection",
    complete: "Complete review",
    discard: "Leave review workspace",
  };
  const text = {
    recommend_approve:
      "This records a reviewer recommendation only. It does not approve or disburse the loan.",
    recommend_decline:
      "This records a recommendation with your rationale. It does not make the bank's final lending decision.",
    complete:
      "This closes the reviewer assessment. The bank's final lending decision remains separate.",
    discard:
      "Unsaved notes, document requirements, or field corrections will be discarded.",
  };
  return (
    <div
      className="review-dialog-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      }}
    >
      <section
        className="review-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-dialog-title"
      >
        <h2 id="review-dialog-title">Confirm {labels[kind]?.toLowerCase()}</h2>
        <p>{text[kind]}</p>
        <div className="review-action-buttons">
          <button type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className="review-confirm-button"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Saving…" : kind === "discard" ? "Leave" : "Confirm"}
          </button>
        </div>
      </section>
    </div>
  );
}

export default function ReviewerReviewWorkspace({
  initial,
  token,
  onBack,
  onRefresh,
}) {
  const [application, setApplication] = useState(initial);
  const [activeTab, setActiveTab] = useState("documents");
  const [findings, setFindings] = useState([]);
  const [checklists, setChecklists] = useState([]);
  const [phase, setPhase] = useState("Document and income review");
  const [checklist, setChecklist] = useState([
    {
      label: "Identity and KYC evidence reviewed",
      status: "PENDING",
      note: "",
    },
    { label: "Income evidence reviewed", status: "PENDING", note: "" },
    {
      label: "Property and terms evidence reviewed",
      status: "PENDING",
      note: "",
    },
  ]);
  const [checklistDirty, setChecklistDirty] = useState(false);
  const [note, setNote] = useState("");
  const [requirements, setRequirements] = useState("");
  const [kycNote, setKycNote] = useState("");
  const [documentNotes, setDocumentNotes] = useState({});
  const [fieldDrafts, setFieldDrafts] = useState({});
  const [correctionReasons, setCorrectionReasons] = useState({});
  const [dialog, setDialog] = useState("");
  const [pendingAction, setPendingAction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [reanalysingDocs, setReanalysingDocs] = useState({});
  const [reanalysisErrors, setReanalysisErrors] = useState({});

  async function refreshWorkspace() {
    const [detail, savedFindings, savedChecklists] = await Promise.all([
      request(`/reviewer/applications/${initial.id}`, token),
      request(`/reviewer/applications/${initial.id}/findings`, token),
      request(`/reviewer/applications/${initial.id}/checklists`, token),
    ]);
    setApplication(detail);
    setFindings(savedFindings);
    setChecklists(savedChecklists);
  }

  useEffect(() => {
    let live = true;
    Promise.all([
      request(`/reviewer/applications/${initial.id}/findings`, token),
      request(`/reviewer/applications/${initial.id}/checklists`, token),
    ])
      .then(([savedFindings, savedChecklists]) => {
        if (live) {
          setFindings(savedFindings);
          setChecklists(savedChecklists);
          if (savedChecklists.length) {
            setPhase(savedChecklists[0].phase);
            setChecklist(savedChecklists[0].checklist);
            setChecklistDirty(false);
          }
        }
      })
      .catch(() => {
        if (live) notifyError();
      });
    return () => {
      live = false;
    };
  }, [initial.id, token]);

  useEffect(() => {
    const hasFieldDrafts = Object.values(fieldDrafts).some((fields) =>
      Object.values(fields).some((value) => String(value).trim()),
    );
    const unsaved = Boolean(
      note.trim() ||
      requirements.trim() ||
      kycNote.trim() ||
      Object.values(documentNotes).some((value) => value.trim()) ||
      Object.values(correctionReasons).some((value) => value.trim()) ||
      hasFieldDrafts ||
      checklistDirty,
    );
    if (!unsaved) return undefined;
    const warn = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [
    note,
    requirements,
    kycNote,
    documentNotes,
    fieldDrafts,
    correctionReasons,
    checklistDirty,
  ]);

  function back() {
    const hasFieldDrafts = Object.values(fieldDrafts).some((fields) =>
      Object.values(fields).some((value) => String(value).trim()),
    );
    const unsaved = Boolean(
      note.trim() ||
      requirements.trim() ||
      kycNote.trim() ||
      Object.values(documentNotes).some((value) => value.trim()) ||
      Object.values(correctionReasons).some((value) => value.trim()) ||
      hasFieldDrafts ||
      checklistDirty,
    );
    if (unsaved) {
      setDialog("discard");
      return;
    }
    onBack();
  }

  async function performAction(action) {
    if (TERMINAL.has(application.status) && action !== "add_note") {
      setError("This review is completed and cannot be changed.");
      return;
    }
    const rationale = note.trim();
    if (
      [
        "request_documents",
        "escalate",
        "recommend_approve",
        "recommend_decline",
        "add_note",
        "complete",
      ].includes(action) &&
      !rationale
    ) {
      setError(
        action === "recommend_decline"
          ? "A rationale is required for a rejection recommendation."
          : "Enter a reviewer note or rationale before continuing.",
      );
      return;
    }
    let actionNote = rationale;
    if (action === "request_documents") {
      if (!requirements.trim()) {
        setError(
          "List the documents or information required before sending this request.",
        );
        return;
      }
      actionNote = `Additional information requested: ${requirements.trim()}\n\nReviewer rationale: ${rationale}`;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await request(
        `/reviewer/applications/${application.id}/actions`,
        token,
        { method: "POST", body: JSON.stringify({ action, note: actionNote }) },
      );
      setNote("");
      setRequirements("");
      setPendingAction("");
      setDialog("");
      notifySuccess(`Review status updated to ${fieldLabel(result.status)}.`);
      await refreshWorkspace();
      await onRefresh();
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }

  async function submitAction(action) {
    if (
      ["recommend_approve", "recommend_decline", "complete"].includes(action)
    ) {
      if (!note.trim()) {
        setError(
          action === "recommend_decline"
            ? "A rationale is required for a rejection recommendation."
            : "Enter a reviewer rationale before submitting.",
        );
        return;
      }
      setPendingAction(action);
      setDialog("decision");
      return;
    }
    await performAction(action);
  }

  async function verifyDocument(document, status) {
    const reason = (documentNotes[document.id] || "").trim();
    if (status !== "VERIFIED" && !reason) {
      setError("Add a reason before rejecting or flagging this document.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await request(
        `/reviewer/applications/${application.id}/documents/${document.id}/verification`,
        token,
        { method: "PATCH", body: JSON.stringify({ status, note: reason }) },
      );
      setDocumentNotes({ ...documentNotes, [document.id]: "" });
      notifySuccess(`Document marked ${fieldLabel(status).toLowerCase()}.`);
      await refreshWorkspace();
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }

  async function saveFieldCorrections(document) {
    const rows = uniqueOcrFieldRows(
      document.extracted_fields || {},
      document.corrected_fields || {},
    );
    const drafts = fieldDrafts[document.id] || {};
    const changes = rows.filter(
      (row) =>
        row.sources.some((source) => source.editable) &&
        drafts[row.id] !== undefined &&
        String(drafts[row.id]) !== String(row.value),
    );
    const reason = (correctionReasons[document.id] || "").trim();
    if (!changes.length) {
      setError(
        "Change at least one extracted field before saving corrections.",
      );
      return;
    }
    if (!reason) {
      setError("Provide a reason for the reviewer correction.");
      return;
    }
    const correctedFields = Object.fromEntries(
      changes.flatMap((row) =>
        row.keys.map((field) => {
          const original = document.extracted_fields?.[field];
          const originalValue =
            original && typeof original === "object"
              ? original.value
              : original;
          const value = drafts[row.id];
          return [
            field,
            typeof originalValue === "number" && value !== ""
              ? Number(value)
              : value,
          ];
        }),
      ),
    );
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await request(
        `/reviewer/applications/${application.id}/documents/${document.id}/fields`,
        token,
        {
          method: "PATCH",
          body: JSON.stringify({ corrected_fields: correctedFields, reason }),
        },
      );
      setFieldDrafts({ ...fieldDrafts, [document.id]: {} });
      setCorrectionReasons({ ...correctionReasons, [document.id]: "" });
      notifySuccess(
        "Reviewer corrections saved. Original OCR values remain preserved in the evidence history.",
      );
      await refreshWorkspace();
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }

  async function reanalyseDocument(document) {
    if (reanalysingDocs[document.id]) return;
    setReanalysingDocs((previous) => ({ ...previous, [document.id]: true }));
    setReanalysisErrors((previous) => ({ ...previous, [document.id]: "" }));
    setError("");
    setMessage("");
    let analysisSaved = false;
    try {
      await request(
        `/reviewer/applications/${application.id}/documents/${document.id}/reanalyze`,
        token,
        { method: "POST" },
      );
      analysisSaved = true;
      await refreshWorkspace();
      await onRefresh();
      notifySuccess(`Reanalysis completed and saved for ${document.filename}.`);
    } catch (e) {
      const detail =
        e instanceof Error
          ? e.message
          : "Reanalysis failed. The document remains marked for reanalysis.";
      if (analysisSaved) {
        setError(
          "Reanalysis completed and was saved, but the Reviewer Panel could not refresh. Reload the application to view the updated findings.",
        );
      } else {
        setReanalysisErrors((previous) => ({
          ...previous,
          [document.id]: detail,
        }));
        setError(detail);
      }
    } finally {
      setReanalysingDocs((previous) => ({ ...previous, [document.id]: false }));
    }
  }

  async function verifyKyc(status) {
    const reason = kycNote.trim();
    if (status !== "VERIFIED" && !reason) {
      setError("Add a reason for the KYC outcome.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await request(`/reviewer/applications/${application.id}/kyc`, token, {
        method: "POST",
        body: JSON.stringify({ status, note: reason }),
      });
      setKycNote("");
      notifySuccess(`KYC status marked ${fieldLabel(status).toLowerCase()}.`);
      await refreshWorkspace();
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }

  async function saveFinding(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await request(
        `/reviewer/applications/${application.id}/findings`,
        token,
        {
          method: "POST",
          body: JSON.stringify({
            category: data.get("category"),
            severity: data.get("severity"),
            title: data.get("title"),
            description: data.get("description"),
            document_id: data.get("document_id")
              ? Number(data.get("document_id"))
              : null,
            field_name: data.get("field_name") || "",
            source_evidence: data.get("source_evidence") || "",
          }),
        },
      );
      form.reset();
      await refreshWorkspace();
      notifySuccess("Review finding saved to the audit history.");
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }

  async function saveChecklist() {
    if (
      !phase.trim() ||
      !checklist.length ||
      checklist.some((item) => !item.label.trim())
    ) {
      setError("Provide a review phase and a label for every checklist item.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await request(
        `/reviewer/applications/${application.id}/checklist`,
        token,
        {
          method: "POST",
          body: JSON.stringify({ phase: phase.trim(), checklist, note: "" }),
        },
      );
      setChecklistDirty(false);
      await refreshWorkspace();
      notifySuccess("Review checklist saved to the audit history.");
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }

  const applicant = application.details?.applicant || {};
  const employment = application.details?.employment || {};
  const property = application.details?.property || {};
  const terminal = TERMINAL.has(application.status);
  const hasRecommendation = [
    "RECOMMEND_APPROVE",
    "RECOMMEND_DECLINE",
    "ESCALATED",
  ].includes(application.status);
  const kyc = application.kyc || {};
  const documentAnalyses = Array.isArray(application.documents)
    ? application.documents.filter(
        (document) =>
          document && typeof document === "object" && !Array.isArray(document),
      )
    : [];
  const tabs = [
    { id: "documents", label: "Documents & OCR" },
    { id: "ai", label: "AI Findings" },
    { id: "verification", label: "Verification & Scenario Checks" },
    { id: "decision", label: "Reviewer Decision & History" },
  ];

  return (
    <div className="review-workspace">
      <button className="review-back" onClick={back}>
        <ArrowLeft size={16} /> Back to queue
      </button>
      {error && (
        <div className="review-error" role="alert">
          {error}
          <button onClick={() => setError("")}>Dismiss</button>
        </div>
      )}
      {message && (
        <div className="review-success" role="status">
          {message}
          <button onClick={() => setMessage("")}>Dismiss</button>
        </div>
      )}
      <header className="review-workspace-heading">
        <div className="review-heading-copy">
          <p className="review-kicker">
            <span>APPLICATION</span>
            <b>{application.reference || "Reference unavailable"}</b>
          </p>
          <div className="review-heading-title-row">
            <h1>
              {applicant.full_name ||
                application.customer?.full_name ||
                "Borrower"}
            </h1>
            <span
              className="review-badge"
              aria-label={`Current review status: ${fieldLabel(application.status)}`}
            >
              {fieldLabel(application.status)}
            </span>
          </div>
          <p className="review-heading-metadata">
            <span>{application.product_name || "Mortgage application"}</span>
            <span>{application.lender_name || "Bank"}</span>
            <span>Submitted {dateTime(application.submitted_at)}</span>
          </p>
        </div>
      </header>
      <section
        className="review-card review-application-overview"
        aria-label="Application overview"
      >
        <div className="review-overview-facts">
          <div>
            <small>Requested loan</small>
            <b>{money(application.requested_loan)}</b>
          </div>
          <div>
            <small>Declared property value</small>
            <b>{money(application.property_value)}</b>
          </div>
          <div>
            <small>Declared annual income</small>
            <b>{money(application.annual_income)}</b>
          </div>
          <div>
            <small>Monthly debt</small>
            <b>{money(application.monthly_debt)}</b>
          </div>
          <div>
            <small>Interest rate / tenure</small>
            <b>
              {application.interest_rate}% · {application.tenure_years} years
            </b>
          </div>
          <div>
            <small>Assigned</small>
            <b>{dateTime(application.assigned_at)}</b>
          </div>
        </div>
        <details className="review-borrower-details">
          <summary>Borrower and property details</summary>
          <div className="review-detail-list">
            <span>Property address</span>
            <b>
              {application.property_address ||
                property.address ||
                "Address not provided"}
            </b>
            {applicant.date_of_birth && (
              <>
                <span>Date of birth</span>
                <b>{applicant.date_of_birth}</b>
              </>
            )}
            {applicant.residential_address && (
              <>
                <span>Residential address</span>
                <b>{applicant.residential_address}</b>
              </>
            )}
            {employment.employment_type && (
              <>
                <span>Employment type</span>
                <b>{fieldLabel(employment.employment_type)}</b>
              </>
            )}
            {employment.occupation && (
              <>
                <span>Occupation</span>
                <b>{employment.occupation}</b>
              </>
            )}
            {employment.employer_name && (
              <>
                <span>Employer</span>
                <b>{employment.employer_name}</b>
              </>
            )}
            <span>Borrower notes</span>
            <b>{application.customer_notes || "No notes supplied."}</b>
          </div>
        </details>
        <p className="review-disclaimer">
          AI observations and scenario checks support human review; they are not
          an automated credit decision.
        </p>
      </section>
      <nav
        className="review-workspace-tabs"
        role="tablist"
        aria-label="Application review sections"
      >
        {tabs.map((tab) => (
          <button
            key={tab.id}
            id={`review-tab-${tab.id}`}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`review-panel-${tab.id}`}
            tabIndex={activeTab === tab.id ? 0 : -1}
            className={activeTab === tab.id ? "is-active" : ""}
            onClick={() => setActiveTab(tab.id)}
            onKeyDown={(event) => {
              if (
                !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
              )
                return;
              event.preventDefault();
              const index = tabs.findIndex((item) => item.id === activeTab);
              const next =
                event.key === "Home"
                  ? 0
                  : event.key === "End"
                    ? tabs.length - 1
                    : (index +
                        (event.key === "ArrowRight" ? 1 : -1) +
                        tabs.length) %
                      tabs.length;
              setActiveTab(tabs[next].id);
              window.requestAnimationFrame(() =>
                window.document
                  .getElementById(`review-tab-${tabs[next].id}`)
                  ?.focus(),
              );
            }}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      <section
        id="review-panel-documents"
        role="tabpanel"
        aria-labelledby="review-tab-documents"
        hidden={activeTab !== "documents"}
        className="review-tab-panel"
      >
        <section className="review-card">
          <h2>
            <FileText size={18} /> Documents and OCR
          </h2>
          {!documentAnalyses.length ? (
            <p className="review-empty">
              No documents have been uploaded for this application.
            </p>
          ) : (
            documentAnalyses.map((document) => {
              const fields = uniqueOcrFieldRows(
                document.extracted_fields,
                document.corrected_fields,
              );
              return (
                <details className="review-document" key={document.id}>
                  <summary>
                    <span>
                      {document.filename}
                      <small>
                        {document.category_label || document.category} · OCR{" "}
                        {fieldLabel(document.extraction_status || "UNKNOWN")} ·
                        Verification{" "}
                        {fieldLabel(document.verification_status || "PENDING")}
                      </small>
                    </span>
                  </summary>
                  <div className="review-document-body">
                    <p>
                      {document.extraction_message ||
                        "OCR processing message unavailable."}
                    </p>
                    <a
                      className="review-file-link"
                      href={`${API}/reviewer/applications/${application.id}/documents/${document.id}/file`}
                      onClick={async (event) => {
                        event.preventDefault();
                        setBusy(true);
                        setError("");
                        try {
                          const response = await fetch(
                            event.currentTarget.href,
                            { headers: { Authorization: `Bearer ${token}` } },
                          );
                          if (!response.ok)
                            throw Error(`Download failed (${response.status})`);
                          const objectUrl = URL.createObjectURL(
                            await response.blob(),
                          );
                          const link = window.document.createElement("a");
                          link.href = objectUrl;
                          link.download = document.filename;
                          link.click();
                          setTimeout(
                            () => URL.revokeObjectURL(objectUrl),
                            2000,
                          );
                        } catch {
                          notifyError();
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      <Download size={14} /> Open or download original
                    </a>
                    <h4>Extracted fields</h4>
                    <ExtractedFields
                      document={document}
                      rows={fields}
                      terminal={terminal}
                      fieldDrafts={fieldDrafts[document.id] || {}}
                      onDraftChange={(row, value) =>
                        setFieldDrafts({
                          ...fieldDrafts,
                          [document.id]: {
                            ...fieldDrafts[document.id],
                            [row.id]: value,
                          },
                        })
                      }
                    />
                    {Array.isArray(document.field_correction_history) &&
                      document.field_correction_history.length > 0 && (
                        <details>
                          <summary>
                            Correction history (
                            {document.field_correction_history.length})
                          </summary>
                          {document.field_correction_history.map(
                            (entry, index) => (
                              <p className="review-history-entry" key={index}>
                                {entry.field || entry.field_name || "Field"}:{" "}
                                {String(entry.original_value ?? "")} →{" "}
                                {String(entry.corrected_value ?? "")}{" "}
                                {entry.reason && `· ${entry.reason}`}
                              </p>
                            ),
                          )}
                        </details>
                      )}
                    {!terminal &&
                      fields.some((row) =>
                        row.sources.some((source) => source.editable),
                      ) && (
                        <div className="review-correction-form">
                          <label>
                            Reason for correction
                            <textarea
                              value={correctionReasons[document.id] || ""}
                              onChange={(event) =>
                                setCorrectionReasons({
                                  ...correctionReasons,
                                  [document.id]: event.target.value,
                                })
                              }
                              maxLength="1000"
                              placeholder="Explain the source evidence supporting these corrections"
                            />
                          </label>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => saveFieldCorrections(document)}
                          >
                            Save reviewer corrections
                          </button>
                        </div>
                      )}
                    <details>
                      <summary>OCR text evidence</summary>
                      <pre>
                        {document.original_text || "No text was extracted."}
                      </pre>
                      {document.extracted_text !== document.original_text && (
                        <>
                          <h4>
                            Current customer-corrected text (not independently
                            verified)
                          </h4>
                          <pre>
                            {document.extracted_text ||
                              "No corrected text supplied."}
                          </pre>
                        </>
                      )}
                    </details>
                    <div className="review-document-verification">
                      <p>
                        Current verification:{" "}
                        <b>
                          {fieldLabel(
                            document.verification_status || "PENDING",
                          )}
                        </b>
                        {document.verified_at &&
                          ` · ${dateTime(document.verified_at)}`}
                      </p>
                      {document.verification_note && (
                        <p>{document.verification_note}</p>
                      )}
                      {!terminal && (
                        <>
                          <label>
                            Reason when rejecting or flagging
                            <textarea
                              value={documentNotes[document.id] || ""}
                              onChange={(event) =>
                                setDocumentNotes({
                                  ...documentNotes,
                                  [document.id]: event.target.value,
                                })
                              }
                              placeholder="Describe the missing or unreadable evidence"
                            />
                          </label>
                          <div className="review-action-buttons">
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() =>
                                verifyDocument(document, "VERIFIED")
                              }
                            >
                              Mark verified
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() =>
                                verifyDocument(document, "NEEDS_REVIEW")
                              }
                            >
                              Needs review
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() =>
                                verifyDocument(document, "REJECTED")
                              }
                            >
                              Reject document
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                </details>
              );
            })
          )}
        </section>
      </section>
      <section
        id="review-panel-ai"
        role="tabpanel"
        aria-labelledby="review-tab-ai"
        hidden={activeTab !== "ai"}
        className="review-tab-panel"
      >
        <AnalysisSummary
          documents={documentAnalyses}
          onReanalyse={reanalyseDocument}
          reanalysingDocs={reanalysingDocs}
          reanalysisErrors={reanalysisErrors}
        />
        {documentAnalyses.length > 0 && (
          <details className="review-complete-analysis">
            <summary>
              View complete document analysis{" "}
              <small>
                {documentAnalyses.length} document
                {documentAnalyses.length === 1 ? "" : "s"}
              </small>
            </summary>
            <div>
              {documentAnalyses.map((document) => (
                <AnalysisEvidence key={document.id} document={document} />
              ))}
            </div>
          </details>
        )}
      </section>
      <section
        id="review-panel-verification"
        role="tabpanel"
        aria-labelledby="review-tab-verification"
        hidden={activeTab !== "verification"}
        className="review-tab-panel review-verification-panel"
      >
        <details className="review-card review-accordion">
          <summary>
            <span>Identity and KYC</span>
            <span className="review-badge">
              {fieldLabel(kyc.status || "PENDING")}
            </span>
          </summary>
          <p>
            Status{" "}
            <span className="review-badge">
              {fieldLabel(kyc.status || "PENDING")}
            </span>{" "}
            · Verified KYC documents {kyc.kyc_documents_verified ?? 0} of{" "}
            {kyc.kyc_documents ?? 0}
          </p>
          <p className="review-muted">
            {kyc.attestation ||
              "Reviewer-attested only; no external identity-verification service is integrated."}
          </p>
          {kyc.note && <p>{kyc.note}</p>}
          {!terminal && (
            <>
              <label className="review-field-label">
                KYC review note
                <textarea
                  value={kycNote}
                  onChange={(event) => setKycNote(event.target.value)}
                  placeholder="Required for rejection or further review"
                />
              </label>
              <div className="review-action-buttons">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => verifyKyc("VERIFIED")}
                >
                  Mark KYC verified
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => verifyKyc("NEEDS_REVIEW")}
                >
                  Needs review
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => verifyKyc("REJECTED")}
                >
                  Reject KYC
                </button>
              </div>
            </>
          )}
        </details>
        <details className="review-card review-accordion">
          <summary>
            <span>
              Income, tax, property valuation and mortgage terms checks
            </span>
            <span className="review-muted">Deterministic scenarios</span>
          </summary>
          <ScenarioPanel
            run={(name, body) =>
              request(
                `/reviewer/applications/${application.id}/scenarios/${name}`,
                token,
                { method: "POST", body: JSON.stringify(body) },
              )
            }
          />
        </details>
        <details className="review-card review-accordion">
          <summary>
            <span>Reviewer findings and checklist</span>
            <span className="review-badge">
              {findings.length} findings · {checklists.length} saved checklists
            </span>
          </summary>
          <p>
            Record source-linked human observations. Findings do not determine
            the lending outcome.
          </p>
          {!terminal && (
            <form className="review-finding-form" onSubmit={saveFinding}>
              <label>
                Category
                <select name="category" defaultValue="DOCUMENT">
                  <option>DOCUMENT</option>
                  <option>INCOME</option>
                  <option>PROPERTY</option>
                  <option>KYC</option>
                  <option>POLICY</option>
                  <option>OTHER</option>
                </select>
              </label>
              <label>
                Severity
                <select name="severity" defaultValue="MEDIUM">
                  <option>LOW</option>
                  <option>MEDIUM</option>
                  <option>HIGH</option>
                  <option>CRITICAL</option>
                </select>
              </label>
              <label>
                Title
                <input name="title" required minLength="3" maxLength="200" />
              </label>
              <label>
                Related field
                <input name="field_name" maxLength="160" />
              </label>
              <label className="review-field-wide">
                Description
                <textarea
                  name="description"
                  required
                  minLength="5"
                  maxLength="5000"
                />
              </label>
              <label>
                Source document
                <select name="document_id">
                  <option value="">No specific document</option>
                  {application.documents?.map((document) => (
                    <option value={document.id} key={document.id}>
                      {document.filename}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Evidence and page reference
                <input
                  name="source_evidence"
                  maxLength="5000"
                  placeholder="Quote supporting evidence; include page if known"
                />
              </label>
              <button className="review-confirm-button" disabled={busy}>
                Save finding
              </button>
            </form>
          )}
          {findings.map((finding) => (
            <article className="review-event" key={finding.id}>
              <b>{finding.title}</b>
              <span className="review-badge">
                {finding.severity} · {finding.category}
              </span>
              <p>{finding.description}</p>
              {finding.field_name && <small>Field: {finding.field_name}</small>}
              {finding.source_evidence && (
                <p>Evidence: {finding.source_evidence}</p>
              )}
              <small>{dateTime(finding.created_at)}</small>
            </article>
          ))}
          {!findings.length && (
            <p className="review-muted">
              No reviewer findings have been recorded.
            </p>
          )}
          <h3>Saved phase checklists</h3>
          {checklists.map((item) => (
            <article className="review-event" key={item.id}>
              <b>{item.phase}</b>
              <ul>
                {(item.checklist || []).map((entry, index) => (
                  <li key={index}>
                    {entry.label}: {fieldLabel(entry.status)}
                    {entry.note && ` · ${entry.note}`}
                  </li>
                ))}
              </ul>
              <small>{dateTime(item.created_at)}</small>
            </article>
          ))}
          {!checklists.length && (
            <p className="review-muted">No phase checklist has been saved.</p>
          )}
          {!terminal && (
            <div className="review-checklist-editor">
              <h3>Save a review checklist</h3>
              <label className="review-field-label">
                Review phase
                <input
                  value={phase}
                  maxLength="100"
                  onChange={(event) => {
                    setPhase(event.target.value);
                    setChecklistDirty(true);
                  }}
                />
              </label>
              {checklist.map((item, index) => (
                <div className="review-check-item" key={index}>
                  <input
                    aria-label="Checklist item label"
                    value={item.label}
                    onChange={(event) => {
                      setChecklist(
                        checklist.map((row, rowIndex) =>
                          rowIndex === index
                            ? { ...row, label: event.target.value }
                            : row,
                        ),
                      );
                      setChecklistDirty(true);
                    }}
                  />
                  <select
                    aria-label="Checklist item status"
                    value={item.status}
                    onChange={(event) => {
                      setChecklist(
                        checklist.map((row, rowIndex) =>
                          rowIndex === index
                            ? { ...row, status: event.target.value }
                            : row,
                        ),
                      );
                      setChecklistDirty(true);
                    }}
                  >
                    {["PENDING", "PASS", "FAIL", "NOT_APPLICABLE"].map(
                      (status) => (
                        <option key={status}>{status}</option>
                      ),
                    )}
                  </select>
                  <input
                    aria-label="Checklist item evidence note"
                    value={item.note}
                    placeholder="Evidence or note"
                    onChange={(event) => {
                      setChecklist(
                        checklist.map((row, rowIndex) =>
                          rowIndex === index
                            ? { ...row, note: event.target.value }
                            : row,
                        ),
                      );
                      setChecklistDirty(true);
                    }}
                  />
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setChecklist(
                        checklist.filter((_, rowIndex) => rowIndex !== index),
                      );
                      setChecklistDirty(true);
                    }}
                  >
                    Remove
                  </button>
                </div>
              ))}
              <div className="review-action-buttons">
                <button
                  type="button"
                  disabled={busy || checklist.length >= 100}
                  onClick={() => {
                    setChecklist([
                      ...checklist,
                      { label: "", status: "PENDING", note: "" },
                    ]);
                    setChecklistDirty(true);
                  }}
                >
                  Add checklist item
                </button>
                <button
                  type="button"
                  disabled={busy || !checklist.length}
                  onClick={saveChecklist}
                >
                  Save checklist
                </button>
              </div>
            </div>
          )}
        </details>
        <details className="review-card review-accordion">
          <summary>
            <span>Approved policy evidence</span>
            <span className="review-muted">Bank-approved citations</span>
          </summary>
          <PolicyEvidence token={token} />
        </details>
      </section>
      <section
        id="review-panel-decision"
        role="tabpanel"
        aria-labelledby="review-tab-decision"
        hidden={activeTab !== "decision"}
        className="review-tab-panel"
      >
        <section className="review-card review-actions">
          <h2>Reviewer decision</h2>
          <p>
            Recommendations are human review outcomes, not the bank’s final loan
            decision. Missing or unevaluated evidence is not a pass.
          </p>
          {!terminal && (
            <>
              <label className="review-field-label">
                Reviewer note or decision rationale
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="Explain the evidence reviewed and your conclusion"
                />
              </label>
              {application.status === "ASSIGNED" ||
              application.status === "SUBMITTED" ||
              application.status === "DOCUMENTS_REQUESTED" ||
              application.status === "ADDITIONAL_INFORMATION_REQUIRED" ? (
                <div className="review-start-action">
                  <button
                    type="button"
                    className="review-primary-button"
                    disabled={busy}
                    onClick={() => performAction("start_review")}
                  >
                    {busy ? "Starting review…" : "Start review"}
                  </button>
                </div>
              ) : null}
              <label className="review-field-label">
                Additional documents or information required
                <textarea
                  value={requirements}
                  onChange={(event) => setRequirements(event.target.value)}
                  placeholder="List each missing document or clarification requested"
                />
              </label>
              <div className="review-action-buttons">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => performAction("request_documents")}
                >
                  Request more information
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => performAction("escalate")}
                >
                  <ShieldAlert size={15} /> Escalate
                </button>
                <button
                  type="button"
                  disabled={busy || application.status !== "IN_REVIEW"}
                  onClick={() => submitAction("recommend_approve")}
                >
                  Recommend approval
                </button>
                <button
                  type="button"
                  disabled={busy || application.status !== "IN_REVIEW"}
                  onClick={() => submitAction("recommend_decline")}
                >
                  Recommend rejection
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => performAction("add_note")}
                >
                  Save reviewer note
                </button>
                <button
                  type="button"
                  disabled={busy || !hasRecommendation}
                  onClick={() => submitAction("complete")}
                >
                  <CheckCircle2 size={15} /> Complete review
                </button>
              </div>
            </>
          )}
          {terminal && (
            <p className="review-muted">
              This reviewer assessment has been completed. Historical documents,
              findings and events remain available read-only.
            </p>
          )}
        </section>
        <details className="review-card review-history-accordion">
          <summary>
            Review history ({application.history?.length || 0} events)
          </summary>
          {!application.history?.length ? (
            <p className="review-muted">No review events recorded yet.</p>
          ) : (
            application.history.map((event) => (
              <article className="review-event" key={event.id}>
                <b>{historyLabel(event.event_type)}</b>
                <small>{dateTime(event.created_at)}</small>
                <p>{event.note || "No note supplied."}</p>
              </article>
            ))
          )}
        </details>
      </section>
      {dialog === "decision" && (
        <DecisionDialog
          kind={pendingAction}
          busy={busy}
          onCancel={() => {
            setDialog("");
            setPendingAction("");
          }}
          onConfirm={() => performAction(pendingAction)}
        />
      )}
      {dialog === "discard" && (
        <DecisionDialog
          kind="discard"
          onCancel={() => setDialog("")}
          onConfirm={onBack}
        />
      )}
    </div>
  );
}

export function AnalysisSummary({
  documents,
  onReanalyse,
  reanalysingDocs,
  reanalysisErrors,
}) {
  documents = Array.isArray(documents)
    ? documents.filter(
        (document) =>
          document && typeof document === "object" && !Array.isArray(document),
      )
    : [];
  const [showAllKeyFindings, setShowAllKeyFindings] = useState(false);
  const counts = documents.reduce((all, document) => {
    const status = document.analysis_status || "NOT_ANALYSED";
    all[status] = (all[status] || 0) + 1;
    return all;
  }, {});
  const groups = analysisPriorityGroups(documents);
  const keyFindings = groups.findings.slice(0, 5);
  const additional = groups.findings.length - keyFindings.length;
  const completed = counts.ANALYSED || 0;
  const hasSuccessfulAnalysis = completed > 0;
  const staleDocuments = documents.filter(
    (document) => document.analysis_status === "NEEDS_REANALYSIS",
  );
  const renderItem = (finding, index, prefix = null) => {
    const entry =
      finding.item &&
      typeof finding.item === "object" &&
      !Array.isArray(finding.item)
        ? finding.item
        : {};
    const excluded = new Set([
      "title",
      "name",
      "label",
      "claim",
      "code",
      "field_name",
      "field",
      "description",
      "finding",
      "message",
      "summary",
      "severity",
      "status",
      "source_reference",
      "source_document",
      "page_number",
      "follow_up",
      "recommended_action",
      "why_it_matters",
      "impact",
      "exact_quote",
      "id",
      "source_a",
      "source_b",
      "value_a",
      "value_b",
      "document_a",
      "document_b",
      "source_1",
      "source_2",
    ]);
    const otherDetails = Object.entries(entry).filter(
      ([key]) => !excluded.has(key),
    );
    return (
      <li className="review-ai-item" key={`${finding.key}-${index}`}>
        <details>
          <summary>
            {prefix && <span className="review-ai-item-kind">{prefix}: </span>}
            <b>
              {conciseFindingTitle(finding.item, {
                category: finding.category,
              })}
            </b>
            {finding.item &&
              typeof finding.item === "object" &&
              finding.item.severity && (
                <span
                  className={`review-badge review-severity-${String(finding.item.severity).toLowerCase()}`}
                >
                  {fieldLabel(String(finding.item.severity))}
                </span>
              )}
            {finding.item &&
              typeof finding.item === "object" &&
              finding.item.status && (
                <span className="review-badge">
                  {fieldLabel(String(finding.item.status))}
                </span>
              )}
            <small>
              {finding.sources.length
                ? finding.sources
                    .map(
                      (source) =>
                        source.filename +
                        (source.page ? ` · p. ${source.page}` : ""),
                    )
                    .join("; ")
                : "Source reference not linked by the analysis"}
            </small>
          </summary>
          {conciseFindingExplanation(finding.item) && (
            <p>{conciseFindingExplanation(finding.item)}</p>
          )}
          {finding.item &&
            typeof finding.item === "object" &&
            (finding.item.why_it_matters || finding.item.impact) && (
              <p className="review-ai-why">
                <b>Why it matters:</b>{" "}
                {finding.item.why_it_matters || finding.item.impact}
              </p>
            )}
          {finding.item &&
            typeof finding.item === "object" &&
            (finding.item.follow_up || finding.item.recommended_action) && (
              <p>
                <b>Reviewer check:</b>{" "}
                {finding.item.follow_up || finding.item.recommended_action}
              </p>
            )}
          {!conciseFindingExplanation(finding.item) &&
            analysisSnippet(finding.item) && (
              <p className="review-ai-full-observation">
                {analysisSnippet(finding.item)}
              </p>
            )}
          {findingComparison(finding.item) && (
            <dl className="review-ai-comparison">
              {findingComparison(finding.item).map((value, valueIndex) => (
                <div key={valueIndex}>
                  <dt>{value.label}</dt>
                  <dd>{value.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {otherDetails.length > 0 && (
            <dl className="review-ai-comparison">
              {otherDetails.map(([key, value]) => (
                <div key={key}>
                  <dt>{fieldLabel(key)}</dt>
                  <dd>{displayAnalysisValue(value)}</dd>
                </div>
              ))}
            </dl>
          )}
          {finding.item &&
            typeof finding.item === "object" &&
            finding.item.id != null && (
              <small className="review-ai-finding-id">
                Finding ID: {String(finding.item.id)}
              </small>
            )}
        </details>
      </li>
    );
  };
  return (
    <section className="review-card review-ai-overview">
      <div className="review-ai-overview-head">
        <div>
          <h2>AI Findings</h2>
          <p>
            Assistive observations only; verify source evidence before recording
            a human decision.
          </p>
        </div>
      </div>
      <section className="review-ai-summary-section">
        <h3>Overall status</h3>
        <p>
          {completed} of {documents.length} document
          {documents.length === 1 ? "" : "s"} analyzed
          {(counts.FAILED || 0) > 0 ? `; ${counts.FAILED} failed` : ""}
          {(counts.NEEDS_REANALYSIS || 0) > 0
            ? `; ${counts.NEEDS_REANALYSIS} need reanalysis`
            : ""}
          {Object.entries(counts).some(
            ([status]) =>
              !["ANALYSED", "FAILED", "NEEDS_REANALYSIS"].includes(status),
          )
            ? `; ${Object.entries(counts)
                .filter(
                  ([status]) =>
                    !["ANALYSED", "FAILED", "NEEDS_REANALYSIS"].includes(
                      status,
                    ),
                )
                .reduce(
                  (total, [, count]) => total + count,
                  0,
                )} pending or other status`
            : ""}
          .
        </p>
      </section>
      {staleDocuments.length > 0 && (
        <section className="review-ai-summary-section review-reanalysis-section">
          <h3>
            Documents requiring reanalysis{" "}
            <small>{staleDocuments.length}</small>
          </h3>
          <ul className="review-reanalysis-list">
            {staleDocuments.map((document) => (
              <li key={document.id}>
                <span>
                  <b>{document.filename || "Document"}</b>
                  <small>
                    {document.category_label ||
                      document.category ||
                      "Uncategorized"}
                  </small>
                </span>
                <button
                  type="button"
                  className="review-primary-button"
                  disabled={Boolean(reanalysingDocs[document.id])}
                  onClick={() => onReanalyse(document)}
                >
                  <RefreshCw size={14} />
                  {reanalysingDocs[document.id] ? "Reanalysing…" : "Reanalyse"}
                </button>
                {(reanalysisErrors[document.id] || document.analysis_error) && (
                  <small className="review-reanalysis-error" role="alert">
                    {reanalysisErrors[document.id] ||
                      `Latest reanalysis failed: ${document.analysis_error}`}
                  </small>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {keyFindings.length > 0 && (
        <section className="review-ai-summary-section">
          <h3>
            Key findings <small>{groups.findings.length}</small>
          </h3>
          <ul className="review-ai-list">
            {(showAllKeyFindings ? groups.findings : keyFindings).map(
              (finding, index) => renderItem(finding, index),
            )}
          </ul>
          {additional > 0 && (
            <button
              type="button"
              className="review-evidence-toggle"
              aria-expanded={showAllKeyFindings}
              onClick={() => setShowAllKeyFindings((value) => !value)}
            >
              {showAllKeyFindings
                ? "Show fewer findings"
                : `Show ${additional} more findings`}
            </button>
          )}
        </section>
      )}
      {groups.missing.length > 0 && (
        <section className="review-ai-summary-section">
          <h3>Missing information</h3>
          <p className="review-ai-guidance">
            These are analysis observations. A field absent from OCR does not by
            itself establish that a document is missing.
          </p>
          <ul className="review-ai-list">
            {groups.missing
              .slice(0, 3)
              .map((finding, index) =>
                renderItem(finding, index, missingItemLabel(finding.item)),
              )}
          </ul>
          {groups.missing.length > 3 && (
            <details className="review-additional-findings">
              <summary>
                Show {groups.missing.length - 3} more missing information items
              </summary>
              <ul className="review-ai-list">
                {groups.missing
                  .slice(3)
                  .map((finding, index) => renderItem(finding, index))}
              </ul>
            </details>
          )}
        </section>
      )}
      {groups.conflicts.length > 0 && (
        <section className="review-ai-summary-section">
          <h3>Conflicting evidence</h3>
          <p className="review-ai-guidance">
            AI-identified conflicts are not confirmed discrepancies. Compare the
            cited source records before recording a reviewer conclusion.
          </p>
          <ul className="review-ai-list">
            {groups.conflicts
              .slice(0, 3)
              .map((finding, index) => renderItem(finding, index))}
          </ul>
          {groups.conflicts.length > 3 && (
            <details className="review-additional-findings">
              <summary>
                Show {groups.conflicts.length - 3} more conflict observations
              </summary>
              <ul className="review-ai-list">
                {groups.conflicts
                  .slice(3)
                  .map((finding, index) => renderItem(finding, index))}
              </ul>
            </details>
          )}
        </section>
      )}
      {groups.checks.length > 0 && (
        <section className="review-ai-summary-section">
          <h3>Recommended reviewer checks</h3>
          <ul className="review-ai-checks">
            {groups.checks.slice(0, 3).map((finding, index) => (
              <li key={`${finding.key}-${index}`}>
                {conciseFindingTitle(finding.item, {
                  category: finding.category,
                })}
                {conciseFindingExplanation(finding.item)
                  ? `: ${conciseFindingExplanation(finding.item)}`
                  : ""}
                <small>
                  {finding.sources.length
                    ? finding.sources
                        .map(
                          (source) =>
                            source.filename +
                            (source.page ? ` · p. ${source.page}` : ""),
                        )
                        .join("; ")
                    : "Source reference not linked by the analysis"}
                </small>
              </li>
            ))}
          </ul>
          {groups.checks.length > 3 && (
            <p className="review-ai-additional">
              {groups.checks.length - 3} additional check
              {groups.checks.length - 3 === 1 ? "" : "s"} in complete analysis.
            </p>
          )}
        </section>
      )}
      {!documents.length && (
        <p className="review-muted">
          No documents have been uploaded for analysis.
        </p>
      )}
      {documents.length > 0 && !hasSuccessfulAnalysis && (
        <p className="review-muted">
          No completed analysis is available. Pending, failed, or stale analysis
          is not treated as a pass.
        </p>
      )}
      {hasSuccessfulAnalysis &&
        !keyFindings.length &&
        !groups.missing.length &&
        !groups.conflicts.length &&
        !groups.checks.length && (
          <p className="review-muted">
            Completed analyses returned no structured findings. Review the
            complete analysis if needed.
          </p>
        )}
    </section>
  );
}

function RetrievedApplicationEvidence({ items, status }) {
  const evidenceItems = Array.isArray(items)
    ? items.filter(
        (item) => item && typeof item === "object" && !Array.isArray(item),
      )
    : [];
  const { excerptCount, sourceCount } = retrievedEvidenceSummary(evidenceItems);
  const message =
    status === "FAILED"
      ? "Application document retrieval failed. No retrieved excerpts are available."
      : status === "NO_RELEVANT_APPLICATION_DOCUMENT_EVIDENCE"
        ? "No relevant application-document evidence was found."
        : "No retrieved application evidence was recorded for this analysis.";
  return (
    <details className="review-analysis-group review-retrieved-evidence">
      <summary>
        <span>
          <b>Retrieved Application Evidence</b>
          <small>
            {excerptCount} excerpt{excerptCount === 1 ? "" : "s"} ·{" "}
            {sourceCount} source document{sourceCount === 1 ? "" : "s"}
          </small>
        </span>
      </summary>
      <p className="review-ai-guidance">
        These source excerpts were retrieved to support the AI analysis.
        Retrieval does not independently verify the document or make an
        automatic decision.
      </p>
      {!excerptCount ? (
        <p className="review-muted">{message}</p>
      ) : (
        <div className="review-retrieved-evidence-list">
          {evidenceItems.map((source, index) => {
            const excerpt = typeof source?.text === "string" ? source.text : "";
            const preview = excerpt.slice(0, 480);
            return (
              <article
                className="review-retrieved-evidence-card"
                key={`${source.document_id ?? "unknown"}-${source.source_variant ?? "source"}-${source.chunk_index ?? index}`}
              >
                <div className="review-retrieved-evidence-meta">
                  <b>{source.filename || "Source filename unavailable"}</b>
                  <span>
                    {source.page_number != null
                      ? `Page ${source.page_number}`
                      : "Page not recorded"}
                    {source.category ? ` · ${source.category}` : ""}
                  </span>
                  {source.source_variant && (
                    <small>
                      {source.source_variant === "CUSTOMER_CORRECTED_UNVERIFIED"
                        ? "Customer-corrected text · unverified"
                        : source.source_variant === "ORIGINAL_OCR"
                          ? "Original OCR"
                          : "Source type recorded"}
                    </small>
                  )}
                </div>
                <blockquote>
                  {preview || "No excerpt text was returned."}
                  {excerpt.length > preview.length && " …"}
                </blockquote>
                {excerpt.length > preview.length && (
                  <details className="review-retrieved-full-excerpt">
                    <summary>Show full excerpt</summary>
                    <blockquote>{excerpt}</blockquote>
                  </details>
                )}
              </article>
            );
          })}
        </div>
      )}
    </details>
  );
}

export function AnalysisEvidence({ document }) {
  const status = document.analysis_status || "NOT_ANALYSED";
  const result =
    document.analysis_result && typeof document.analysis_result === "object"
      ? document.analysis_result
      : {};
  const analysis =
    result.analysis && typeof result.analysis === "object"
      ? result.analysis
      : null;
  const deterministic = analysisArray(result.deterministic_checks);
  const facts = analysisArray(analysis?.extracted_facts);
  const discrepancies = analysisArray(analysis?.discrepancies);
  const missing = analysisArray(analysis?.missing_information);
  const risks = analysisArray(analysis?.risk_flags);
  const evidence = analysisArray(analysis?.evidence);
  const retrievedEvidence = analysisArray(
    result.retrieved_application_evidence,
  );
  const checks = analysisArray(analysis?.recommended_reviewer_checks);
  const limitations = analysisArray(analysis?.limitations);
  const group = analysisGroup(document, analysis);
  return (
    <details className="review-analysis-document">
      <summary>
        <span className="review-analysis-document-name">
          <b>{document.filename || "Document"}</b>
          <small>
            {document.category_label || document.category || "Uncategorized"}
            {document.analysis_completed_at
              ? ` · ${dateTime(document.analysis_completed_at)}`
              : ""}
          </small>
        </span>
        <span className="review-badge">{fieldLabel(status)}</span>
      </summary>
      <div className="review-analysis-document-body">
        {status === "FAILED" && (
          <p className="review-error" role="alert">
            Analysis failed:{" "}
            {document.analysis_error ||
              "The configured analysis service returned an error."}
          </p>
        )}
        {status === "NEEDS_REANALYSIS" && (
          <p className="review-muted">
            Source text changed after analysis. The saved findings may be stale;
            no current result is presented as current.
          </p>
        )}
        {!analysis && status !== "FAILED" && status !== "NEEDS_REANALYSIS" && (
          <p className="review-muted">
            No successful document analysis is available. No result is inferred
            as a pass.
          </p>
        )}
        {analysis && (
          <>
            <p className="review-analysis-meta">
              {analysis.document_type_guess && (
                <>
                  Document type: <b>{analysis.document_type_guess}</b> ·{" "}
                </>
              )}
              {analysis.confidence && (
                <>
                  Model confidence: <b>{fieldLabel(analysis.confidence)}</b>{" "}
                  ·{" "}
                </>
              )}
              {result.provider || "Provider not recorded"}
              {result.model ? ` · ${result.model}` : ""}
            </p>
            {facts.length > 0 && (
              <section className="review-analysis-group">
                <h3>{group}</h3>
                <AnalysisFindingList items={facts} document={document} />
              </section>
            )}
            {(discrepancies.length > 0 || missing.length > 0) && (
              <section className="review-analysis-group">
                <h3>Missing or Conflicting Evidence</h3>
                {discrepancies.length > 0 && (
                  <>
                    <h4>Discrepancies</h4>
                    <AnalysisFindingList
                      items={discrepancies}
                      document={document}
                    />
                  </>
                )}
                {missing.length > 0 && (
                  <>
                    <h4>Missing information</h4>
                    <AnalysisFindingList items={missing} document={document} />
                  </>
                )}
              </section>
            )}
            {risks.length > 0 && (
              <section className="review-analysis-group">
                <h3>Other Risk Flags</h3>
                <AnalysisFindingList items={risks} document={document} />
              </section>
            )}
            {checks.length > 0 && (
              <section className="review-analysis-group">
                <h3>Recommended Reviewer Checks</h3>
                <AnalysisFindingList items={checks} document={document} />
              </section>
            )}
            {evidence.length > 0 && (
              <section className="review-analysis-group">
                <h3>Source Documents & References</h3>
                <AnalysisFindingList items={evidence} document={document} />
              </section>
            )}
            <RetrievedApplicationEvidence
              items={retrievedEvidence}
              status={result.document_retrieval_status}
            />
            {limitations.length > 0 && (
              <p className="review-analysis-limitations">
                <b>Analysis limitations:</b>{" "}
                {limitations.map(displayAnalysisValue).join(" · ")}
              </p>
            )}
          </>
        )}
        {document.extracted_fields &&
          Object.keys(document.extracted_fields).length > 0 && (
            <details className="review-analysis-raw">
              <summary>View extracted OCR fields</summary>
              <dl className="review-extracted-fields">
                {uniqueOcrFieldRows(
                  document.extracted_fields,
                  document.corrected_fields || {},
                ).map((row) => (
                  <div key={row.id}>
                    <dt>
                      {row.label}
                      {row.conflict && (
                        <span className="review-field-conflict-note">
                          Conflicting OCR values
                        </span>
                      )}
                    </dt>
                    <dd>{String(row.value)}</dd>
                    {row.sources.map((source, index) => (
                      <Fragment
                        key={`${source.key}-${source.page || "p"}-${index}`}
                      >
                        {source.evidence && (
                          <dd className="review-evidence-quote">
                            {source.evidence}
                          </dd>
                        )}
                        {source.page && (
                          <dd className="review-page-reference">
                            {source.kind} · Page {source.page}
                          </dd>
                        )}
                      </Fragment>
                    ))}
                  </div>
                ))}
              </dl>
            </details>
          )}
        {deterministic.length > 0 && (
          <section className="review-deterministic-results">
            <h3>Deterministic validation results</h3>
            <p>
              Backend comparisons, separate from AI observations and human
              decisions.
            </p>
            <ul>
              {deterministic.map((check, index) => (
                <li key={index}>
                  <b>{check.label || "Value comparison"}:</b> declared{" "}
                  {money(check.declared_value)} vs document{" "}
                  {money(check.document_value)} —{" "}
                  {check.within_configured_tolerance ? "within" : "outside"}{" "}
                  configured tolerance ({check.difference_percent}% difference;
                  ±{check.tolerance_percent}%).
                </li>
              ))}
            </ul>
          </section>
        )}
        {(result.warning ||
          analysisArray(result.validation_errors).length > 0) && (
          <details className="review-analysis-warnings">
            <summary>
              Analysis notices (
              {(result.warning ? 1 : 0) +
                analysisArray(result.validation_errors).length}
              )
            </summary>
            {result.warning && <p>{result.warning}</p>}
            {analysisArray(result.validation_errors).map((warning, index) => (
              <p key={index}>{displayAnalysisValue(warning)}</p>
            ))}
          </details>
        )}
        <details className="review-analysis-raw">
          <summary>View technical metadata and original analysis data</summary>
          <dl className="review-analysis-technical">
            <div>
              <dt>Provider</dt>
              <dd>{result.provider || "Not recorded"}</dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{result.model || "Not recorded"}</dd>
            </div>
            <div>
              <dt>Completed</dt>
              <dd>{dateTime(document.analysis_completed_at)}</dd>
            </div>
            <div>
              <dt>Analysis status</dt>
              <dd>{fieldLabel(status)}</dd>
            </div>
            <div>
              <dt>JSON validated</dt>
              <dd>
                {result.json_valid === undefined
                  ? "Not recorded"
                  : result.json_valid
                    ? "Yes"
                    : "No"}
              </dd>
            </div>
            <div>
              <dt>Input characters</dt>
              <dd>{result.input_characters ?? "Not recorded"}</dd>
            </div>
          </dl>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </details>
      </div>
    </details>
  );
}

function PolicyEvidence({ token }) {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function ask(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(
        await request("/reviewer/policy-qa", token, {
          method: "POST",
          body: JSON.stringify({ question: question.trim() }),
        }),
      );
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="review-card review-policy-evidence">
      <h2>Approved policy evidence</h2>
      <p>
        Answers use active retrieved bank policy excerpts only. A policy answer
        is supporting evidence, not a lending decision.
      </p>
      <form onSubmit={ask}>
        <label className="review-field-label">
          Question about the applicable policy
          <input
            value={question}
            minLength="5"
            maxLength="2000"
            required
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about an applicable policy requirement"
          />
        </label>
        <button
          className="review-confirm-button"
          disabled={busy || question.trim().length < 5}
        >
          {busy ? "Retrieving approved policy…" : "Ask policy question"}
        </button>
      </form>
      {result && (
        <div className="review-policy-answer">
          <p className="review-badge">
            {result.grounded
              ? "Grounded in retrieved policy"
              : "Insufficient policy evidence"}
          </p>
          <p>{result.answer}</p>
          {result.citations?.length > 0 ? (
            <ul>
              {result.citations.map((citation) => (
                <li key={`${citation.policy_id}-${citation.source_id}`}>
                  <b>
                    {citation.title} · v{citation.policy_version}
                  </b>
                  <blockquote>{citation.excerpt}</blockquote>
                </li>
              ))}
            </ul>
          ) : (
            <p className="review-muted">No policy citations were returned.</p>
          )}
          <p className="review-muted">
            {result.warning ||
              "Do not treat this answer as a lending decision."}
          </p>
        </div>
      )}
    </section>
  );
}
