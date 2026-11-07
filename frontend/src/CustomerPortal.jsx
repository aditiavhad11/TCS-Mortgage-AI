import { useEffect, useRef, useState } from "react";
import { api, token, session, clear, download } from "./api";
import { money } from "./utils/format";
import { notifyError, notifySuccess } from "./ToastProvider";
import CustomerPolicyAssistant from "./CustomerPolicyAssistant";
import PasswordRecoveryForm from "./PasswordRecoveryForm";
import {
  OCR_TARGETS,
  assignTarget,
  collectOcrSources,
  evidencePage,
  mapOcrIntoForm,
  targetValue,
} from "./utils/ocrMapping";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Bell,
  Check,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  ClipboardList,
  Clock3,
  Download,
  FileCheck2,
  FileText,
  FolderOpen,
  Eye,
  EyeOff,
  Home,
  Info,
  LogOut,
  Menu,
  MessageCircle,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
  UploadCloud,
  UserRound,
  X,
} from "lucide-react";

const CATEGORIES = [
  { value: "Mortgage Application", label: "Mortgage Application" },
  { value: "KYC", label: "KYC Documents — Identity/Address Proof" },
  { value: "Income Proof / Salary Slip", label: "Income Proof / Salary Slips" },
  { value: "Bank Statement", label: "Bank Statements" },
  { value: "ITR", label: "Income Tax Returns (ITR)" },
  { value: "Sale / Purchase Agreement", label: "Sale/Purchase Agreement" },
  { value: "Property Title", label: "Property Title Documents" },
  { value: "Property Valuation", label: "Property Valuation Report" },
  { value: "Loan Agreement", label: "Loan Agreement" },
  { value: "Amortization Schedule", label: "Amortization Schedule" },
  {
    value: "Terms / Disclosure",
    label: "Terms & Conditions / Disclosure Documents",
  },
];
const blankDetails = () => ({
  applicant: {
    full_name: "",
    gender: "",
    date_of_birth: "",
    age: "",
    mobile: "",
    email: "",
    residential_address: "",
    current_address: "",
  },
  loan: {
    purpose: "",
    income_category: "",
    down_payment: "",
    co_applicant_required: false,
    repayment_preference: "",
  },
  employment: {
    employment_type: "",
    employer_name: "",
    occupation: "",
    business_duration: "",
    monthly_income: "",
    annual_income: "",
    other_income: "",
    income_source: "",
  },
  bank: {
    account_holder_name: "",
    bank_name: "",
    account_number: "",
    ifsc: "",
    account_type: "",
  },
  property: {
    property_type: "",
    location: "",
    property_status: "",
    estimated_market_value: "",
    seller_builder: "",
    registration_details: "",
    ownership_relationship: "",
  },
  co_applicant: {
    full_name: "",
    relationship: "",
    mobile: "",
    email: "",
    annual_income: "",
    employment_type: "",
  },
});
const blankApplication = () => ({
  lender_name: "",
  product_name: "",
  property_address: "",
  property_value: "",
  requested_loan: "",
  annual_income: "",
  monthly_debt: "",
  interest_rate: "8.5",
  tenure_years: "20",
  customer_notes: "",
  details: blankDetails(),
  consents: { truthful_information: false, privacy_consent: false },
});
const STATUS_LABELS = {
  DRAFT: "Draft",
  SUBMITTED: "Submitted",
  PENDING_VALIDATION: "Pending validation",
  PENDING_ASSIGNMENT: "Awaiting reviewer assignment",
  ASSIGNED: "Assigned",
  IN_PROGRESS: "In progress",
  IN_REVIEW: "Under review",
  DOCUMENTS_REQUESTED: "Waiting for documents",
  ADDITIONAL_INFORMATION_REQUIRED: "Additional information required",
  ASSESSMENT_SUBMITTED: "Assessment submitted",
  RECOMMEND_APPROVE: "Assessment submitted",
  COMPLETED: "Review completed",
  APPROVED: "Approved",
  REJECTED: "Rejected",
};
const currencyKeys = new Set([
  "requested_loan",
  "property_value",
  "annual_income",
  "monthly_debt",
  "down_payment",
  "monthly_income",
  "other_income",
  "estimated_market_value",
]);
function safeOcrValue(key, value) {
  if (value == null) return "";
  if (/account_number|identity_document_number/i.test(key)) {
    const raw = String(value).replace(/\s/g, "");
    return raw.length > 4
      ? `${"•".repeat(Math.min(8, raw.length - 4))}${raw.slice(-4)}`
      : "••••";
  }
  return value;
}

function safeError(error) {
  const message = error?.message || "Something went wrong. Please try again.";
  try {
    const parsed = JSON.parse(message);
    if (Array.isArray(parsed?.errors))
      return parsed.errors.map((x) => `• ${x}`).join("\n");
    if (parsed?.message) return parsed.message;
  } catch {
    /* normal text */
  }
  return message;
}
function labelStatus(status) {
  return (
    STATUS_LABELS[status] ||
    String(status || "Unknown")
      .replaceAll("_", " ")
      .toLowerCase()
      .replace(/^./, (x) => x.toUpperCase())
  );
}
function Field({
  label,
  value,
  onChange,
  type = "text",
  required = false,
  hint,
  placeholder,
  full = false,
  min,
  max,
  step,
  readOnly = false,
  options,
  autoComplete,
  inputMode,
  pattern,
  maxLength,
}) {
  return (
    <label className={`form-field ${full ? "field-full" : ""}`}>
      <span>
        {label}
        {required && <i aria-hidden="true"> *</i>}
      </span>
      {options ? (
        <select
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          required={required}
          disabled={readOnly}
          autoComplete={autoComplete}
        >
          <option value="">Select {label.toLowerCase()}</option>
          {options.map((o) =>
            typeof o === "string" ? (
              <option key={o} value={o}>
                {o}
              </option>
            ) : (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ),
          )}
        </select>
      ) : type === "textarea" ? (
        <textarea
          rows={3}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          required={required}
          placeholder={placeholder}
          readOnly={readOnly}
          maxLength={maxLength}
        />
      ) : (
        <input
          type={type}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          required={required}
          placeholder={placeholder}
          min={min}
          max={max}
          step={step}
          readOnly={readOnly}
          autoComplete={autoComplete}
          inputMode={inputMode}
          pattern={pattern}
          maxLength={maxLength}
        />
      )}
      {hint && <small className="field-hint">{hint}</small>}
    </label>
  );
}
function MappedField({
  sources = [],
  value,
  onChange,
  onSelectSource,
  hint,
  ...props
}) {
  const primary = sources[0];
  const original = primary?.original;
  const changed =
    primary && String(value ?? "") !== String(primary.value ?? "");
  const conflicts =
    [...new Set(sources.map((source) => String(source.value ?? "")))].length >
    1;
  const moneyValue = (item) =>
    typeof item === "number" ? money(item) : String(item ?? "Not found");
  return (
    <div className={`mapped-field ${props.full ? "field-full" : ""}`}>
      <Field value={value} onChange={onChange} {...props} />
      {primary && (changed || primary.corrected) && (
        <small className="original-value">
          Original OCR Value: {moneyValue(original)}
        </small>
      )}
      {sources.length > 0 && (
        <div className="mapped-evidence" aria-label="Source evidence">
          {sources.map((source, index) => (
            <small
              className="evidence-snippet"
              key={`${source.doc.id}-${source.key}-${source.page || ""}-${index}`}
            >
              From {source.doc.original_filename} (
              {source.doc.category_label || source.doc.category})
              {source.page ? ` · Page ${source.page}` : ""}
              {source.evidence
                ? `: ${source.evidence.replace(/^\[PAGE\s+\d+\]\s*/i, "")}`
                : ""}
            </small>
          ))}
        </div>
      )}
      {conflicts && (
        <div className="ocr-conflict" role="alert">
          <b>Document values differ — confirm the correct value</b>
          {sources.map((source, index) => (
            <button
              type="button"
              key={`${source.doc.id}-${source.key}-${source.page || ""}-${index}`}
              onClick={() =>
                onSelectSource ? onSelectSource(source) : onChange(source.value)
              }
            >
              {source.doc.category_label || source.doc.category} ·{" "}
              {source.doc.original_filename}: {moneyValue(source.value)}
              {source.page ? ` · Page ${source.page}` : ""} · Use this value
            </button>
          ))}
        </div>
      )}
      {hint && <small className="field-hint mapped-field-hint">{hint}</small>}
    </div>
  );
}
function StatCard({ icon: Icon, label, value, detail, tone = "blue" }) {
  return (
    <article className="customer-stat">
      <span className={`stat-icon ${tone}`}>
        <Icon size={18} />
      </span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
        {detail && <p>{detail}</p>}
      </div>
    </article>
  );
}
function EmptyState({
  icon: Icon = FolderOpen,
  title,
  description,
  action,
  onAction,
}) {
  return (
    <div className="customer-empty">
      <span>
        <Icon size={25} />
      </span>
      <h3>{title}</h3>
      <p>{description}</p>
      {action && (
        <button className="btn btn-primary" onClick={onAction}>
          {action}
        </button>
      )}
    </div>
  );
}

export default function CustomerPortal() {
  const [user, setUser] = useState(null);
  const [authChecking, setAuthChecking] = useState(() => Boolean(token()));
  const [mode, setMode] = useState(() =>
    new URLSearchParams(window.location.search).has("reset_token")
      ? "reset"
      : "login",
  );
  const [resetToken, setResetToken] = useState(
    () => new URLSearchParams(window.location.search).get("reset_token") || "",
  );
  const [auth, setAuth] = useState({
    full_name: "",
    email: "",
    mobile: "",
    password: "",
    confirm_password: "",
    code: "",
  });
  const [verifyEmail, setVerifyEmail] = useState("");
  const [otpDelivery, setOtpDelivery] = useState("");
  const [resendAt, setResendAt] = useState(0);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const sessionCheckStarted = useRef(false);
  const [apps, setApps] = useState([]);
  const [banks, setBanks] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [app, setApp] = useState(null);
  const [form, setForm] = useState(blankApplication());
  const [docs, setDocs] = useState([]);
  const [docRequirements, setDocRequirements] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState(CATEGORIES[0].value);
  const [page, setPage] = useState("dashboard");
  const [step, setStep] = useState(0);
  const [tab, setTab] = useState("details");
  const [analysis, setAnalysis] = useState(null);
  const [showFullAnalysis, setShowFullAnalysis] = useState(false);
  const [analysisHistory, setAnalysisHistory] = useState([]);
  const [estimates, setEstimates] = useState(null);
  const [fieldDrafts, setFieldDrafts] = useState({});
  const [ocrFieldSources, setOcrFieldSources] = useState({});
  const [profileMobile, setProfileMobile] = useState(user?.mobile || "");
  const [busy, setBusy] = useState(false);
  const [analysingDocs, setAnalysingDocs] = useState([]);
  const [deletingNotifications, setDeletingNotifications] = useState([]);
  const [deletingApplications, setDeletingApplications] = useState([]);
  const deletionInFlight = useRef(new Set());
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const [lastSaved, setLastSaved] = useState(null);
  const [confirmSubmitOpen, setConfirmSubmitOpen] = useState(false);
  const [submissionIssues, setSubmissionIssues] = useState([]);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.has("reset_token")) {
      url.searchParams.delete("reset_token");
      window.history.replaceState(
        {},
        "",
        `${url.pathname}${url.search}${url.hash}`,
      );
    }
  }, []);

  const notify = (text) => {
    setMessage("");
    setError("");
    notifySuccess(text);
  };
  const fail = () => {
    setMessage("");
    setError("");
    notifyError();
  };
  const clearFeedback = () => {
    setMessage("");
    setError("");
  };

  async function loadDashboard() {
    const [applicationRows, notificationRows, dashboard] = await Promise.all([
      api("/applications"),
      api("/notifications"),
      api("/customer/dashboard"),
    ]);
    setApps(applicationRows);
    setNotifications(notificationRows);
    setProfileMobile(dashboard.customer?.mobile || user?.mobile || "");
  }
  useEffect(() => {
    api("/applications/approved-banks")
      .then(setBanks)
      .catch(() => setBanks([]));
    if (!token()) {
      setAuthChecking(false);
      return;
    }
    if (!sessionCheckStarted.current) {
      sessionCheckStarted.current = true;
      api("/auth/me")
        .then(async (current) => {
          setUser(current);
          setProfileMobile(current.mobile);
          try {
            await loadDashboard();
          } catch (e) {
            if (
              e instanceof TypeError ||
              /failed to fetch|networkerror|load failed/i.test(e?.message || "")
            )
              fail(
                new Error(
                  "Your profile is verified, but the dashboard could not connect. Please retry.",
                ),
              );
            else fail(e);
          }
        })
        .catch((e) => {
          clear();
          setUser(null);
          if (
            e instanceof TypeError ||
            /failed to fetch|networkerror|load failed/i.test(e?.message || "")
          )
            fail(
              new Error(
                "Cannot connect to the mortgage service. Check that the backend is running and try again.",
              ),
            );
          else
            fail(
              new Error(
                "Your saved sign-in is invalid or expired. Please sign in again.",
              ),
            );
        })
        .finally(() => setAuthChecking(false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    const handleExpiredSession = () => {
      setUser(null);
      setAuthChecking(false);
      setApps([]);
      setNotifications([]);
      setApp(null);
      setDocs([]);
      setMode("login");
      setMessage("");
      setError("");
    };
    window.addEventListener("mortgage:session-expired", handleExpiredSession);
    return () =>
      window.removeEventListener(
        "mortgage:session-expired",
        handleExpiredSession,
      );
  }, []);
  useEffect(() => {
    if (resendAt <= Date.now()) return undefined;
    const timer = window.setInterval(
      () => setResendAt((v) => (v <= Date.now() ? 0 : v)),
      500,
    );
    return () => window.clearInterval(timer);
  }, [resendAt]);
  useEffect(() => {
    if (!user?.id) return undefined;
    let active = true;
    const refresh = async () => {
      try {
        const [applicationRows, notificationRows] = await Promise.all([
          api("/applications"),
          api("/notifications"),
        ]);
        if (!active) return;
        setApps(applicationRows);
        setNotifications(notificationRows);
        if (app?.id) {
          const current = applicationRows.find((row) => row.id === app.id);
          if (current) setApp(current);
        }
      } catch {
        /* transient refresh errors must not erase the last persisted view */
      }
    };
    const timer = window.setInterval(refresh, 30000);
    window.addEventListener("focus", refresh);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
    };
  }, [user?.id, app?.id]);

  function setAuthField(key, value) {
    setAuth((prev) => ({ ...prev, [key]: value }));
  }
  async function authSubmit(event) {
    event.preventDefault();
    clearFeedback();
    setBusy(true);
    try {
      if (mode === "register") {
        if (auth.password !== auth.confirm_password)
          throw new Error("Password and confirm password do not match.");
        const result = await api("/auth/register", {
          method: "POST",
          body: JSON.stringify(auth),
        });
        setVerifyEmail(auth.email.trim().toLowerCase());
        setOtpDelivery(result.delivery || "");
        setResendAt(Date.now() + (result.resend_after_seconds || 60) * 1000);
        setMode("verify");
        notify(
          result.delivery === "email"
            ? "Verification code sent to your registered email."
            : "Development mode: the OTP is printed in the backend terminal; no email was sent.",
        );
      } else if (mode === "verify") {
        const result = await api("/auth/verify-otp", {
          method: "POST",
          body: JSON.stringify({
            email: verifyEmail || auth.email,
            code: auth.code,
          }),
        });
        session(result);
        setUser(result.customer);
        setPage("dashboard");
        await loadDashboard();
        notify("Email verified. Your customer workspace is ready.");
      } else {
        const result = await api("/auth/login", {
          method: "POST",
          body: JSON.stringify({
            email: auth.email.trim().toLowerCase(),
            password: auth.password,
          }),
        });
        if (!result?.access_token || !result?.customer?.id)
          throw new Error(
            "The sign-in service did not return a valid customer session.",
          );
        session(result);
        let profile;
        try {
          profile = await api("/auth/me");
        } catch (e) {
          clear();
          throw e;
        }
        if (Number(profile?.id) !== Number(result.customer.id)) {
          clear();
          throw new Error(
            "The authenticated profile did not match the signed-in account. Please try again.",
          );
        }
        session({ ...result, customer: profile });
        setUser(profile);
        setProfileMobile(profile.mobile || "");
        await loadDashboard();
        setPage("dashboard");
        notify("Signed in successfully.");
      }
    } catch (e) {
      if (
        e instanceof TypeError ||
        /failed to fetch|networkerror|load failed/i.test(e?.message || "")
      )
        fail(
          new Error(
            "Cannot connect to the mortgage service. Check that the backend is running and try again.",
          ),
        );
      else fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function resendOTP() {
    clearFeedback();
    setBusy(true);
    try {
      const result = await api("/auth/resend-otp", {
        method: "POST",
        body: JSON.stringify({ email: verifyEmail || auth.email }),
      });
      setOtpDelivery(result.delivery || "");
      setResendAt(Date.now() + (result.resend_after_seconds || 60) * 1000);
      notify(
        result.delivery === "email"
          ? "A new verification code was emailed."
          : "Development mode: a new code was printed in the backend terminal; no email was sent.",
      );
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  function signOut() {
    clear();
    setUser(null);
    setApps([]);
    setApp(null);
    setDocs([]);
    setPage("dashboard");
    setMode("login");
    clearFeedback();
  }

  function trackOcrEdit(target, value) {
    const sources = (ocrFieldSources[target] || []).slice(0, 1);
    if (!sources.length) return;
    setFieldDrafts((prev) => {
      const next = { ...prev };
      sources.forEach((source) => {
        next[source.doc.id] = {
          ...(next[source.doc.id] || {}),
          [source.key]: value,
        };
      });
      return next;
    });
  }
  function confirmOcrSource(target, source) {
    setOcrFieldSources((prev) => ({
      ...prev,
      [target]: [
        source,
        ...(prev[target] || []).filter((item) => item !== source),
      ],
    }));
    setFieldDrafts((prev) => ({
      ...prev,
      [source.doc.id]: {
        ...(prev[source.doc.id] || {}),
        [source.key]: source.value,
      },
    }));
    setForm((prev) => assignTarget(prev, target, source.value));
  }
  function updateForm(key, value) {
    trackOcrEdit(key, value);
    setForm((prev) => ({ ...prev, [key]: value }));
  }
  function updateSection(section, key, value) {
    trackOcrEdit(`details.${section}.${key}`, value);
    setForm((prev) => ({
      ...prev,
      details: {
        ...prev.details,
        [section]: { ...(prev.details?.[section] || {}), [key]: value },
      },
    }));
  }
  function setDocumentFieldDrafts(documentId, updates) {
    setFieldDrafts((prev) => ({
      ...prev,
      [documentId]: { ...(prev[documentId] || {}), ...updates },
    }));
    Object.entries(updates).forEach(([key, value]) =>
      (OCR_TARGETS[key] || []).forEach((target) => {
        const mappedValue = targetValue(target, value);
        setForm((prev) => assignTarget(prev, target, mappedValue));
      }),
    );
  }
  async function startApplication() {
    clearFeedback();
    setBusy(true);
    try {
      const initial = blankApplication();
      const createPayload = {
        ...initial,
        property_value: 0,
        requested_loan: 0,
        annual_income: 0,
        monthly_debt: 0,
        interest_rate: 8.5,
        tenure_years: 20,
      };
      const created = await api("/applications", {
        method: "POST",
        body: JSON.stringify(createPayload),
      });
      setApp(created);
      setForm({
        ...created,
        ...initial,
        details: { ...initial.details, ...(created.details || {}) },
        consents: { ...initial.consents, ...(created.consents || {}) },
      });
      setSubmissionIssues([]);
      setDocs([]);
      setDocRequirements([]);
      setAnalysis(null);
      setAnalysisHistory([]);
      setEstimates(null);
      setFieldDrafts({});
      setOcrFieldSources({});
      setStep(-1);
      setTab("details");
      setPage("application");
      try {
        const checklist = await api(
          `/applications/${created.id}/document-requirements`,
        );
        setDocRequirements(checklist.items || []);
      } catch {
        /* draft remains available if checklist service is temporarily unavailable */
      }
      await loadDashboard();
      notify(
        "Application draft created. Your progress will be saved as you continue.",
      );
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function openApplication(row, targetPage = "application") {
    clearFeedback();
    setBusy(true);
    try {
      const [detail, documentRows, requirementResult, history, metrics] =
        await Promise.all([
          api(`/applications/${row.id}`),
          api(`/applications/${row.id}/documents`),
          api(`/applications/${row.id}/document-requirements`),
          api(`/ai/applications/${row.id}/analysis-history`),
          api(`/applications/${row.id}/estimates`).catch(() => null),
        ]);
      const initial = blankApplication();
      const mergedDetails = { ...initial.details, ...(detail.details || {}) };
      for (const section of Object.keys(initial.details))
        mergedDetails[section] = {
          ...initial.details[section],
          ...(detail.details?.[section] || {}),
        };
      const coreValues = { ...detail };
      if (detail.status === "DRAFT")
        for (const key of [
          "requested_loan",
          "property_value",
          "annual_income",
          "monthly_debt",
        ])
          if (coreValues[key] === 0) coreValues[key] = "";
      setApp(detail);
      setSubmissionIssues([]);
      const mapped = mapOcrIntoForm(
        {
          ...initial,
          ...coreValues,
          details: mergedDetails,
          consents: { ...initial.consents, ...(detail.consents || {}) },
        },
        documentRows,
      );
      setForm(mapped.form);
      setOcrFieldSources(mapped.sources);
      setDocs(documentRows);
      setDocRequirements(requirementResult.items || []);
      setAnalysisHistory(history || []);
      setEstimates(metrics);
      const latest = (history || [])[0];
      setAnalysis(
        latest ? { ...(latest.result || {}), status: latest.status } : null,
      );
      setFieldDrafts({});
      setStep(detail.status === "DRAFT" && !documentRows.length ? -1 : 0);
      setTab("details");
      setPage(targetPage);
      if (detail.last_saved_at) setLastSaved(detail.last_saved_at);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function saveDraft({ silent = false } = {}) {
    if (!app) return null;
    const payload = { ...form };
    for (const key of [
      "property_value",
      "requested_loan",
      "annual_income",
      "monthly_debt",
      "interest_rate",
      "tenure_years",
    ]) {
      const value = payload[key];
      payload[key] =
        value === "" || value == null
          ? key === "tenure_years"
            ? 20
            : key === "interest_rate"
              ? 8.5
              : 0
          : Number(value);
    }
    const saved = await api(`/applications/${app.id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    const pendingCorrections = Object.entries(fieldDrafts).filter(
      ([, values]) =>
        Object.keys(values || {}).some((key) => !key.startsWith("__")),
    );
    if (pendingCorrections.length) {
      const updatedDocs = await Promise.all(
        pendingCorrections.map(async ([documentId, values]) => {
          const corrected_fields = Object.fromEntries(
            Object.entries(values).filter(([key]) => !key.startsWith("__")),
          );
          return api(`/applications/${app.id}/documents/${documentId}/fields`, {
            method: "PUT",
            body: JSON.stringify({
              corrected_fields,
              reason: "Customer correction from mortgage application form",
            }),
          });
        }),
      );
      setDocs((prev) =>
        prev.map(
          (doc) => updatedDocs.find((updated) => updated.id === doc.id) || doc,
        ),
      );
      setFieldDrafts((prev) => {
        const next = { ...prev };
        pendingCorrections.forEach(([id]) => {
          next[id] = Object.fromEntries(
            Object.entries(next[id] || {}).filter(([key]) =>
              key.startsWith("__"),
            ),
          );
        });
        return next;
      });
      setOcrFieldSources(
        collectOcrSources(
          docs.map(
            (doc) =>
              updatedDocs.find((updated) => updated.id === doc.id) || doc,
          ),
        ),
      );
    }
    setApp(saved);
    setForm((prev) => ({
      ...prev,
      ...saved,
      requested_loan: prev.requested_loan,
      property_value: prev.property_value,
      annual_income: prev.annual_income,
      monthly_debt: prev.monthly_debt,
      details: { ...prev.details, ...(saved.details || {}) },
      consents: { ...prev.consents, ...(saved.consents || {}) },
    }));
    setLastSaved(saved.last_saved_at || saved.updated_at);
    await loadDashboard();
    try {
      setEstimates(await api(`/applications/${app.id}/estimates`));
    } catch {
      setEstimates(null);
    }
    if (!silent) notify("Application saved as draft.");
    return saved;
  }
  async function nextStep() {
    clearFeedback();
    setBusy(true);
    try {
      await saveDraft({ silent: true });
      setStep((s) => Math.min(5, s + 1));
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function previousStep() {
    setStep((s) => Math.max(0, s - 1));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  async function uploadDocument(event) {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length || !app) return;
    clearFeedback();
    setBusy(true);
    try {
      const uploaded = [];
      for (const file of files) {
        const body = new FormData();
        body.append("category", selectedCategory);
        body.append("file", file);
        uploaded.push(
          await api(`/applications/${app.id}/documents`, {
            method: "POST",
            body,
          }),
        );
      }
      const allDocs = [...docs, ...uploaded];
      setDocs(allDocs);
      const mapped = mapOcrIntoForm(form, allDocs);
      setForm(mapped.form);
      setOcrFieldSources(mapped.sources);
      const requirementResult = await api(
        `/applications/${app.id}/document-requirements`,
      );
      setDocRequirements(requirementResult.items || []);
      await loadDashboard();
      notify(
        `${uploaded.length} file${uploaded.length === 1 ? "" : "s"} uploaded under ${CATEGORIES.find((c) => c.value === selectedCategory)?.label || selectedCategory}.`,
      );
    } catch (e) {
      try {
        const current = await api(`/applications/${app.id}/documents`);
        setDocs(current);
        const mapped = mapOcrIntoForm(form, current);
        setForm(mapped.form);
        setOcrFieldSources(mapped.sources);
      } catch {
        /* preserve the last loaded state */
      }
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function confirmDocumentCategory(doc, category = doc.category) {
    if (!app || busy) return;
    clearFeedback();
    setBusy(true);
    try {
      const updated = await api(
        `/applications/${app.id}/documents/${doc.id}/category`,
        { method: "PUT", body: JSON.stringify({ category, confirm: true }) },
      );
      setDocs((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      );
      notify(
        category === doc.category
          ? "You confirmed the selected document category."
          : `Document category changed to ${updated.category_label || updated.category} and confirmed.`,
      );
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function removeDocument(doc) {
    if (
      !app ||
      !editable ||
      !window.confirm(`Remove ${doc.original_filename}?`)
    )
      return;
    clearFeedback();
    setBusy(true);
    try {
      await api(`/applications/${app.id}/documents/${doc.id}`, {
        method: "DELETE",
      });
      const updated = docs.filter((item) => item.id !== doc.id);
      setDocs(updated);
      const mapped = mapOcrIntoForm(form, updated);
      setForm(mapped.form);
      setOcrFieldSources(mapped.sources);
      const requirementResult = await api(
        `/applications/${app.id}/document-requirements`,
      );
      setDocRequirements(requirementResult.items || []);
      await loadDashboard();
      notify("Document removed from this draft.");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function replaceDocument(doc, event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !app) return;
    clearFeedback();
    setBusy(true);
    try {
      const body = new FormData();
      body.append("category", doc.category);
      body.append("file", file);
      const replacement = await api(`/applications/${app.id}/documents`, {
        method: "POST",
        body,
      });
      await api(`/applications/${app.id}/documents/${doc.id}`, {
        method: "DELETE",
      });
      const updated = [
        ...docs.filter((item) => item.id !== doc.id),
        replacement,
      ];
      setDocs(updated);
      const mapped = mapOcrIntoForm(form, updated);
      setForm(mapped.form);
      setOcrFieldSources(mapped.sources);
      const requirementResult = await api(
        `/applications/${app.id}/document-requirements`,
      );
      setDocRequirements(requirementResult.items || []);
      await loadDashboard();
      notify(
        `${doc.original_filename} was replaced with ${replacement.original_filename}.`,
      );
    } catch (e) {
      try {
        const current = await api(`/applications/${app.id}/documents`);
        setDocs(current);
        const mapped = mapOcrIntoForm(form, current);
        setForm(mapped.form);
        setOcrFieldSources(mapped.sources);
      } catch {
        /* preserve the last loaded state */
      }
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function saveTextCorrection(doc) {
    clearFeedback();
    setBusy(true);
    try {
      const result = await api(
        `/applications/${app.id}/documents/${doc.id}/text`,
        {
          method: "PUT",
          body: JSON.stringify({
            edited_text: doc.edited_text ?? doc.extracted_text,
          }),
        },
      );
      setDocs((prev) => prev.map((d) => (d.id === result.id ? result : d)));
      notify("Text correction saved. Original OCR evidence is preserved.");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function saveFieldCorrection(doc) {
    const drafts = Object.fromEntries(
      Object.entries(fieldDrafts[doc.id] || {}).filter(
        ([key]) => !key.startsWith("__"),
      ),
    );
    if (!Object.keys(drafts).length) {
      notify("No field changes to save.");
      return;
    }
    clearFeedback();
    setBusy(true);
    try {
      const result = await api(
        `/applications/${app.id}/documents/${doc.id}/fields`,
        {
          method: "PUT",
          body: JSON.stringify({
            corrected_fields: drafts,
            reason: "Customer correction to OCR-extracted fields",
          }),
        },
      );
      const updatedDocs = docs.map((d) => (d.id === result.id ? result : d));
      setDocs(updatedDocs);
      setOcrFieldSources(collectOcrSources(updatedDocs));
      setFieldDrafts((prev) => ({ ...prev, [doc.id]: {} }));
      notify(
        "Corrected fields saved. Original values and edit history are retained.",
      );
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function runDocumentAnalysis(doc, force = false) {
    if (!app || analysingDocs.includes(doc.id)) return;
    clearFeedback();
    setAnalysingDocs((prev) => [...prev, doc.id]);
    setDocs((prev) =>
      prev.map((d) =>
        d.id === doc.id ? { ...d, analysis_status: "ANALYSING" } : d,
      ),
    );
    try {
      const result = await api(
        `/ai/applications/${app.id}/documents/${doc.id}/analyze${force ? "?force=true" : ""}`,
        { method: "POST" },
      );
      notify(
        result.cached
          ? "Showing the saved analysis; the document has not changed since it was analysed."
          : "NVIDIA analysis completed for this document. Verify findings against the original.",
      );
    } catch (e) {
      setMessage("");
      setError("");
      notifyError(safeError(e));
    } finally {
      try {
        setDocs(await api(`/applications/${app.id}/documents`));
      } catch {
        /* keep current list */
      }
      setAnalysingDocs((prev) => prev.filter((id) => id !== doc.id));
    }
  }
  async function runAnalysis() {
    if (!app || !docs.length) return;
    clearFeedback();
    setBusy(true);
    try {
      await saveDraft({ silent: true });
      const result = await api(`/ai/applications/${app.id}/analyze`, {
        method: "POST",
      });
      setAnalysis(result);
      setAnalysisHistory((prev) => [
        {
          id: result.run_id,
          status: result.status,
          created_at: new Date().toISOString(),
          result,
        },
        ...prev,
      ]);
      setTab("analysis");
      try {
        setDocs(await api(`/applications/${app.id}/documents`));
      } catch {
        /* keep existing document cards if refresh is unavailable */
      }
      notify(
        `NVIDIA analysis completed for ${result.successful_count} of ${result.analysis_count} document(s). Verify findings against the originals.`,
      );
    } catch (e) {
      setMessage("");
      setError("");
      notifyError(safeError(e));
      try {
        const history = await api(
          `/ai/applications/${app.id}/analysis-history`,
        );
        setAnalysisHistory(history);
        if (history[0]) {
          setAnalysis({
            ...(history[0].result || {}),
            status: history[0].status,
          });
          setTab("analysis");
        }
      } catch {
        /* keep current state */
      }
    } finally {
      setBusy(false);
    }
  }
  function submissionStep(message) {
    const text = String(message).toLowerCase();
    if (/document|upload|readable/.test(text)) return 4;
    if (/co-applicant/.test(text)) return 1;
    if (
      /applicant|date of birth|residential address|mobile number|email address/.test(
        text,
      )
    )
      return 0;
    if (/lender|loan|employment|employer|occupation|income/.test(text))
      return 1;
    if (/property/.test(text)) return 3;
    return 5;
  }
  function validateSubmission() {
    const issues = [];
    const applicant = form.details?.applicant || {};
    const loan = form.details?.loan || {};
    const employment = form.details?.employment || {};
    const property = form.details?.property || {};
    const add = (label, step) => issues.push({ label, step });
    if (!String(form.lender_name || "").trim())
      add("Select an approved lender", 1);
    else if (
      banks.length &&
      !banks.some((bank) => bank.code === form.lender_name)
    )
      add("Select a lender from the approved banks list", 1);
    if (!(Number(form.requested_loan) > 0))
      add("Enter a requested loan amount greater than zero", 1);
    if (!loan.purpose) add("Select a loan purpose", 1);
    if (!String(applicant.full_name || "").trim())
      add("Enter the applicant's full name", 0);
    if (
      !String(applicant.date_of_birth || "").trim() ||
      Number.isNaN(Date.parse(applicant.date_of_birth)) ||
      new Date(applicant.date_of_birth) >= new Date(new Date().toDateString())
    )
      add("Enter a valid past date of birth", 0);
    const mobileDigits = String(applicant.mobile || "").replace(/\D/g, "");
    if (!mobileDigits) add("Enter the applicant's mobile number", 0);
    else if (mobileDigits.length < 10 || mobileDigits.length > 15)
      add("Enter a valid applicant mobile number", 0);
    const email = String(applicant.email || "").trim();
    if (!email) add("Enter the applicant's email address", 0);
    else if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email))
      add("Enter a valid applicant email address", 0);
    if (!String(applicant.residential_address || "").trim())
      add("Enter the residential address", 0);
    if (!employment.employment_type) add("Select the employment type", 1);
    if (!String(employment.occupation || "").trim())
      add("Enter the occupation", 1);
    if (
      ["Salaried", "Business owner", "Self-employed"].includes(
        employment.employment_type,
      ) &&
      !String(employment.employer_name || "").trim()
    )
      add("Enter the employer / business name for this employment type", 1);
    if (
      !(Number(form.annual_income) > 0 || Number(employment.monthly_income) > 0)
    )
      add("Enter monthly or annual income greater than zero", 1);
    if (!property.property_type) add("Select the property type", 3);
    if (!String(form.property_address || "").trim())
      add("Enter the property address", 3);
    if (!(Number(form.property_value) > 0))
      add("Enter the declared property/agreement value", 3);
    if (loan.co_applicant_required) {
      if (!String(form.details?.co_applicant?.full_name || "").trim())
        add(
          "Enter the co-applicant's full name or turn off the co-applicant option",
          1,
        );
      if (!String(form.details?.co_applicant?.relationship || "").trim())
        add("Enter the co-applicant's relationship", 1);
    }
    for (const [label, value, step] of [
      ["Monthly income", employment.monthly_income, 1],
      ["Employment annual income", employment.annual_income, 1],
      ["Other declared annual income", employment.other_income, 1],
      ["Down payment", loan.down_payment, 1],
      ["Estimated market value", property.estimated_market_value, 3],
      ["Existing monthly loan obligations", form.monthly_debt, 1],
      [
        "Co-applicant annual income",
        form.details?.co_applicant?.annual_income,
        1,
      ],
    ])
      if (
        value !== "" &&
        value != null &&
        (!Number.isFinite(Number(value)) || Number(value) < 0)
      )
        add(`${label} must be a valid non-negative amount`, step);
    if (
      String(form.details?.bank?.ifsc || "").trim() &&
      !/^[A-Za-z]{4}0[A-Za-z0-9]{6}$/.test(form.details.bank.ifsc.trim())
    )
      add("Enter a valid IFSC code or leave it blank if not required", 2);
    if (!form.consents?.truthful_information)
      add("Confirm that the information supplied is accurate", 5);
    if (!form.consents?.privacy_consent)
      add("Confirm the privacy and document-processing consent", 5);
    for (const requirement of docRequirements.filter(
      (item) => item.required && item.status !== "UPLOADED",
    ))
      add(`Upload the required document: ${requirement.label}`, 4);
    for (const category of new Set(
      docRequirements
        .filter((item) => item.required && item.status === "UPLOADED")
        .map((item) => item.category),
    )) {
      const categoryDocs = docs.filter((doc) => doc.category === category);
      if (
        categoryDocs.length &&
        !categoryDocs.some(
          (doc) =>
            doc.extraction_status === "COMPLETED" ||
            String(doc.extracted_text || doc.edited_text || "").trim(),
        )
      )
        add(`Upload a readable ${category} document`, 4);
    }
    return issues;
  }
  function requestApplicationSubmit() {
    clearFeedback();
    const issues = validateSubmission();
    setSubmissionIssues(issues);
    if (issues.length) {
      setConfirmSubmitOpen(false);
      setStep(issues[0].step);
      setTab("details");
      setError(
        `Please complete the required information before submitting:\n${issues.map((issue) => `• ${issue.label}`).join("\n")}`,
      );
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    setConfirmSubmitOpen(true);
  }
  async function submitApplication() {
    clearFeedback();
    setBusy(true);
    try {
      await saveDraft({ silent: true });
      const result = await api(`/applications/${app.id}/submit`, {
        method: "POST",
      });
      setApp(result);
      setConfirmSubmitOpen(false);
      await loadDashboard();
      notify(
        "Application submitted successfully. The backend has recorded the current status.",
      );
      setPage("application");
      setStep(5);
    } catch (e) {
      const validationMessage = safeError(e).toLowerCase();
      fail(e);
      setConfirmSubmitOpen(false);
      if (
        validationMessage.includes("applicant") ||
        validationMessage.includes("date of birth") ||
        validationMessage.includes("residential address")
      )
        setStep(0);
      else if (
        validationMessage.includes("loan purpose") ||
        validationMessage.includes("employment") ||
        validationMessage.includes("income") ||
        validationMessage.includes("lender")
      )
        setStep(1);
      else if (validationMessage.includes("property")) setStep(3);
      else if (
        validationMessage.includes("document") ||
        validationMessage.includes("upload") ||
        validationMessage.includes("readable")
      ) {
        setStep(4);
        setTab("details");
      } else setStep(5);
    } finally {
      setBusy(false);
    }
  }
  async function markRead(notification) {
    try {
      await api(`/notifications/${notification.id}`, {
        method: "PATCH",
        body: JSON.stringify({ read: !notification.read }),
      });
      setNotifications((prev) =>
        prev.map((n) =>
          n.id === notification.id ? { ...n, read: !notification.read } : n,
        ),
      );
    } catch (e) {
      fail(e);
    }
  }
  async function deleteNotification(notification) {
    const requestKey = `notification:${notification.id}`;
    if (deletionInFlight.current.has(requestKey)) return;
    deletionInFlight.current.add(requestKey);
    clearFeedback();
    setDeletingNotifications((prev) => [...prev, notification.id]);
    try {
      await api(`/notifications/${notification.id}`, { method: "DELETE" });
      setNotifications((prev) =>
        prev.filter((item) => item.id !== notification.id),
      );
      try {
        await loadDashboard();
      } catch {
        /* deletion succeeded; keep the locally updated count */
      }
      notifySuccess("Notification deleted.");
    } catch {
      notifyError();
    } finally {
      deletionInFlight.current.delete(requestKey);
      setDeletingNotifications((prev) =>
        prev.filter((id) => id !== notification.id),
      );
    }
  }
  async function deleteDraftApplication(application) {
    if (application.status !== "DRAFT") return;
    const requestKey = `application:${application.id}`;
    if (deletionInFlight.current.has(requestKey)) return;
    deletionInFlight.current.add(requestKey);
    clearFeedback();
    setDeletingApplications((prev) => [...prev, application.id]);
    try {
      await api(`/applications/${application.id}`, { method: "DELETE" });
      setApps((prev) => prev.filter((item) => item.id !== application.id));
      try {
        await loadDashboard();
      } catch {
        /* deletion succeeded; keep the locally updated counts */
      }
      notifySuccess("Draft application deleted.");
    } catch {
      notifyError();
    } finally {
      deletionInFlight.current.delete(requestKey);
      setDeletingApplications((prev) =>
        prev.filter((id) => id !== application.id),
      );
    }
  }
  async function updateProfile(event) {
    event.preventDefault();
    clearFeedback();
    setBusy(true);
    try {
      const updated = await api("/auth/me", {
        method: "PATCH",
        body: JSON.stringify({ mobile: profileMobile }),
      });
      setUser(updated);
      session({ access_token: token(), customer: updated });
      notify("Profile updated successfully.");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  const editable =
    app &&
    [
      "DRAFT",
      "DOCUMENTS_REQUESTED",
      "ADDITIONAL_INFORMATION_REQUIRED",
    ].includes(app.status);
  const draftCount = apps.filter((item) => item.status === "DRAFT").length;
  const approvedCount = apps.filter(
    (item) => item.status === "APPROVED",
  ).length;
  const underReviewCount = apps.filter((item) =>
    [
      "SUBMITTED",
      "PENDING_VALIDATION",
      "PENDING_ASSIGNMENT",
      "ASSIGNED",
      "IN_PROGRESS",
      "IN_REVIEW",
      "DOCUMENTS_REQUESTED",
      "ADDITIONAL_INFORMATION_REQUIRED",
      "ASSESSMENT_SUBMITTED",
      "RECOMMEND_APPROVE",
      "RECOMMEND_DECLINE",
      "COMPLETED",
    ].includes(item.status),
  ).length;
  const unreadCount = notifications.filter((n) => !n.read).length;
  const currentApplicant = form.details?.applicant || {};
  const currentEmployment = form.details?.employment || {};
  const currentBank = form.details?.bank || {};
  const currentLoan = form.details?.loan || {};
  const currentProperty = form.details?.property || {};

  if (resetToken || (!user && mode === "forgot"))
    return (
      <div className="password-recovery-page">
        <PasswordRecoveryForm
          accountType="CUSTOMER"
          initialToken={resetToken}
          email={auth.email}
          className="customer-auth-form"
          onBack={() => {
            clear();
            setUser(null);
            setAuthChecking(false);
            setApps([]);
            setNotifications([]);
            setApp(null);
            setDocs([]);
            setResetToken("");
            setAuth((prev) => ({
              ...prev,
              password: "",
              confirm_password: "",
            }));
            setMode("login");
          }}
        />
      </div>
    );
  if (!user && authChecking)
    return (
      <div className="customer-session-loading" role="status">
        <ShieldCheck size={18} /> Verifying your secure session…
      </div>
    );
  if (!user)
    return (
      <div className="customer-auth-shell">
        <section className="auth-brand-panel">
          <div className="customer-brand">
            <span className="brand-symbol">M</span>
            <span>
              <b>TCS Mortgage AI</b>
              <small>Customer application portal</small>
            </span>
          </div>
          <div className="auth-message">
            <span className="auth-kicker">HOME FINANCE WORKSPACE</span>
            <h1>
              A clearer path
              <br />
              to your mortgage.
            </h1>
            <p>
              Prepare your application, organise supporting documents and follow
              real application updates in one secure workspace.
            </p>
            <div className="auth-benefit">
              <ShieldCheck size={18} /> Private document workspace
            </div>
            <div className="auth-benefit">
              <FileCheck2 size={18} /> Readable extracted information
            </div>
            <div className="auth-benefit">
              <Activity size={18} /> Status updates from your bank workflow
            </div>
          </div>
          <small className="auth-footer">
            TCS Mortgage AI · Customer portal
          </small>
        </section>
        <section className="auth-form-panel">
          <form className="customer-auth-form" onSubmit={authSubmit}>
            <span className="section-kicker">
              {mode === "verify"
                ? "EMAIL VERIFICATION"
                : mode === "register"
                  ? "CREATE CUSTOMER ACCOUNT"
                  : "CUSTOMER ACCESS"}
            </span>
            <h2>
              {mode === "verify"
                ? "Verify your email"
                : mode === "register"
                  ? "Create your account"
                  : "Welcome back"}
            </h2>
            <p className="auth-description">
              {mode === "verify"
                ? `Enter the verification code sent to ${verifyEmail || auth.email}.`
                : mode === "register"
                  ? "Register to create, save and track your mortgage application."
                  : "Sign in with your registered email address and password to continue."}
            </p>
            {(message || error) && (
              <div
                className={`feedback ${error ? "is-error" : "is-success"}`}
                role="status"
              >
                {error || message}
              </div>
            )}
            {mode === "register" && (
              <Field
                label="Full name"
                value={auth.full_name}
                onChange={(v) => setAuthField("full_name", v)}
                placeholder="Enter your full legal name"
                required
              />
            )}
            {mode === "login" && (
              <Field
                label="Email address"
                value={auth.email}
                onChange={(v) => setAuthField("email", v)}
                placeholder="Enter your registered email address"
                required
                type="email"
                autoComplete="username"
              />
            )}
            {mode === "register" && (
              <>
                <Field
                  label="Mobile number"
                  value={auth.mobile}
                  onChange={(v) => setAuthField("mobile", v)}
                  placeholder="10-digit mobile number"
                  required
                  type="tel"
                />{" "}
                <Field
                  label="Email address"
                  value={auth.email}
                  onChange={(v) => setAuthField("email", v)}
                  placeholder="name@example.com"
                  required
                  type="email"
                />
              </>
            )}
            {mode !== "verify" && (
              <>
                <label className="form-field">
                  <span>Password *</span>
                  <div className="password-control">
                    <input
                      type={showPassword ? "text" : "password"}
                      value={auth.password}
                      onChange={(e) => setAuthField("password", e.target.value)}
                      minLength={mode === "register" ? 8 : 1}
                      maxLength={128}
                      autoComplete={
                        mode === "register"
                          ? "new-password"
                          : "current-password"
                      }
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-label={
                        showPassword ? "Hide password" : "Show password"
                      }
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                  {mode === "register" && (
                    <>
                      <small className="field-hint">
                        Use at least 8 characters. Avoid sharing your password.
                      </small>
                      <small
                        className={`password-strength strength-${auth.password.length < 8 ? "weak" : auth.password.length >= 12 && /[A-Z]/.test(auth.password) && /[0-9]/.test(auth.password) && /[^A-Za-z0-9]/.test(auth.password) ? "strong" : "fair"}`}
                      >
                        {auth.password.length < 8
                          ? "Password strength: add more characters"
                          : auth.password.length >= 12 &&
                              /[A-Z]/.test(auth.password) &&
                              /[0-9]/.test(auth.password) &&
                              /[^A-Za-z0-9]/.test(auth.password)
                            ? "Password strength: strong"
                            : "Password strength: moderate — consider a longer mixed password"}
                      </small>
                    </>
                  )}
                </label>
                {mode === "login" && (
                  <button
                    type="button"
                    className="recovery-link"
                    onClick={() => {
                      setMode("forgot");
                      clearFeedback();
                    }}
                  >
                    Forgot password?
                  </button>
                )}
                {mode === "register" && (
                  <label className="form-field">
                    <span>Confirm password *</span>
                    <div className="password-control">
                      <input
                        type={showConfirm ? "text" : "password"}
                        value={auth.confirm_password}
                        onChange={(e) =>
                          setAuthField("confirm_password", e.target.value)
                        }
                        minLength={8}
                        maxLength={128}
                        autoComplete="new-password"
                        required
                      />
                      <button
                        type="button"
                        onClick={() => setShowConfirm((v) => !v)}
                        aria-label={
                          showConfirm
                            ? "Hide confirm password"
                            : "Show confirm password"
                        }
                      >
                        {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                    </div>
                  </label>
                )}
              </>
            )}
            {mode === "verify" && (
              <>
                <Field
                  label="6-digit verification code"
                  value={auth.code}
                  onChange={(v) =>
                    setAuthField("code", v.replace(/\D/g, "").slice(0, 6))
                  }
                  placeholder="Enter OTP"
                  required
                  inputMode="numeric"
                />
                <p className="field-hint">
                  {otpDelivery === "email"
                    ? "Check your email inbox and spam folder."
                    : "If running in development mode, check the backend terminal. No email was sent."}
                </p>
              </>
            )}
            <button className="btn btn-primary auth-submit" disabled={busy}>
              {busy
                ? "Please wait…"
                : mode === "verify"
                  ? "Verify email"
                  : mode === "register"
                    ? "Create account"
                    : "Sign in"}
              <ArrowRight size={16} />
            </button>
            {mode === "verify" && (
              <button
                className="btn btn-secondary auth-resend"
                type="button"
                onClick={resendOTP}
                disabled={busy || Date.now() < resendAt}
              >
                {Date.now() < resendAt
                  ? `Resend available in ${Math.ceil((resendAt - Date.now()) / 1000)}s`
                  : "Resend verification code"}
              </button>
            )}
            <div className="auth-switch">
              {mode === "verify" ? (
                <button
                  type="button"
                  onClick={() => {
                    setMode("register");
                    clearFeedback();
                  }}
                >
                  Back to registration
                </button>
              ) : (
                <>
                  {mode === "register"
                    ? "Already registered?"
                    : "New to the portal?"}
                  <button
                    type="button"
                    onClick={() => {
                      setMode(mode === "register" ? "login" : "register");
                      clearFeedback();
                    }}
                  >
                    {mode === "register" ? "Sign in" : "Create an account"}
                  </button>
                </>
              )}
            </div>
            <p className="auth-security">
              <ShieldCheck size={14} /> Your dashboard opens only after
              successful email verification.
            </p>
          </form>
        </section>
      </div>
    );

  const navItems = [
    { id: "dashboard", label: "Dashboard", icon: Home },
    { id: "applications", label: "My Applications", icon: ClipboardList },
    { id: "apply", label: "Apply for Loan", icon: Plus },
    { id: "documents", label: "Documents & Requests", icon: FolderOpen },
    { id: "policy-assistant", label: "Policy Assistant", icon: MessageCircle },
    {
      id: "notifications",
      label: "Notifications",
      icon: Bell,
      count: unreadCount,
    },
    { id: "profile", label: "Profile", icon: UserRound },
  ];
  function navigate(id) {
    clearFeedback();
    setMobileNav(false);
    if (id === "apply") {
      startApplication();
      return;
    }
    if (id === "documents" && !app && apps.length) {
      setPage("documents");
      return;
    }
    setPage(id);
    if (id !== "application")
      setApp(
        id === "dashboard" ||
          id === "applications" ||
          id === "notifications" ||
          id === "profile" ||
          id === "documents"
          ? app
          : null,
      );
  }
  function openApplicationFromList(row) {
    openApplication(row, "application");
  }
  const applicationReadOnly = app && !editable;

  return (
    <div className="customer-shell">
      <aside className={`customer-sidebar ${mobileNav ? "nav-open" : ""}`}>
        <div className="customer-brand">
          <span className="brand-symbol">M</span>
          <span>
            <b>TCS Mortgage AI</b>
            <small>Customer workspace</small>
          </span>
        </div>
        <div className="sidebar-caption">WORKSPACE</div>
        <nav className="customer-nav">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={`customer-nav-item ${page === item.id || (page === "application" && item.id === "applications") ? "active" : ""}`}
                onClick={() => navigate(item.id)}
              >
                <Icon size={18} />
                <span>{item.label}</span>
                {item.count > 0 && <b className="nav-count">{item.count}</b>}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-note">
            <ShieldCheck size={16} />
            <span>
              <b>Private workspace</b>
              <small>Only your authorised records</small>
            </span>
          </div>
          <button className="customer-nav-item signout" onClick={signOut}>
            <LogOut size={18} />
            <span>Sign out</span>
          </button>
        </div>
      </aside>
      <main className="customer-main">
        <header className="customer-topbar">
          <button
            className="mobile-menu"
            onClick={() => setMobileNav((v) => !v)}
            aria-label="Toggle navigation"
          >
            <Menu size={20} />
          </button>
          <div className="topbar-location">
            <span>Customer portal</span>
            <ChevronRight size={14} />
            <b>
              {page === "application"
                ? app?.reference || "Application"
                : navItems.find((x) => x.id === page)?.label || "Dashboard"}
            </b>
          </div>
          <div className="topbar-user">
            <button
              className="icon-button notification-shortcut"
              onClick={() => setPage("notifications")}
              aria-label="Notifications"
            >
              <Bell size={18} />
              {unreadCount > 0 && <i />}
            </button>
            <span className="user-avatar">
              {user.full_name?.trim()?.[0]?.toUpperCase() || "C"}
            </span>
            <span className="topbar-user-text">
              <b>{user.full_name}</b>
              <small>Customer</small>
            </span>
          </div>
        </header>
        <div className="customer-content">
          {(message || error) && (
            <div
              className={`feedback global-feedback ${error ? "is-error" : "is-success"}`}
              role="status"
            >
              <span>{error || message}</span>
              <button onClick={clearFeedback} aria-label="Dismiss message">
                <X size={16} />
              </button>
            </div>
          )}
          {page === "policy-assistant" && (
            <>
              <div className="page-heading">
                <div>
                  <span className="section-kicker">POLICY GUIDANCE</span>
                  <h1>Ask about mortgage policies</h1>
                  <p>
                    Get a plain-language explanation grounded in active,
                    customer-visible policy information.
                  </p>
                </div>
              </div>
              <CustomerPolicyAssistant applications={apps} />
            </>
          )}
          {page === "dashboard" && (
            <>
              <div className="page-heading">
                <div>
                  <span className="section-kicker">CUSTOMER OVERVIEW</span>
                  <h1>Good to see you, {user.full_name.split(" ")[0]}.</h1>
                  <p>
                    Track your applications, complete document requests and
                    review the latest updates.
                  </p>
                </div>
                <button
                  className="btn btn-primary"
                  onClick={startApplication}
                  disabled={busy}
                >
                  <Plus size={17} /> Start new application
                </button>
              </div>
              <div className="stats-grid">
                <StatCard
                  icon={ClipboardList}
                  label="Total applications"
                  value={apps.length}
                  detail="All saved applications"
                />
                <StatCard
                  icon={Clock3}
                  label="Draft applications"
                  value={draftCount}
                  detail="Saved and not submitted"
                  tone="amber"
                />
                <StatCard
                  icon={Activity}
                  label="Applications under review"
                  value={underReviewCount}
                  detail="Submitted and in the review workflow"
                  tone="violet"
                />
                <StatCard
                  icon={CheckCircle2}
                  label="Approved applications"
                  value={approvedCount}
                  detail="Persisted approved status"
                  tone="green"
                />
              </div>
              <section className="surface-card">
                <div className="surface-heading">
                  <div>
                    <h2>My applications</h2>
                    <p>Your saved application status and next action.</p>
                  </div>
                  <button
                    className="btn btn-quiet"
                    onClick={() => setPage("applications")}
                  >
                    View all <ArrowRight size={15} />
                  </button>
                </div>
                {!apps.length ? (
                  <EmptyState
                    icon={FolderOpen}
                    title="No applications yet"
                    description="Start a mortgage application to save your details and upload supporting documents."
                    action="Start application"
                    onAction={startApplication}
                  />
                ) : (
                  <div className="dashboard-applications">
                    <div className="dashboard-applications-head">
                      <span>Application ID</span>
                      <span>Requested loan</span>
                      <span>Selected bank</span>
                      <span>Current status</span>
                      <span>Action</span>
                    </div>
                    {apps.slice(0, 5).map((row) => (
                      <div className="dashboard-applications-row" key={row.id}>
                        <b>{row.reference}</b>
                        <span>{money(row.requested_loan)}</span>
                        <span>{row.lender_name || "Not selected"}</span>
                        <span>
                          <i
                            className={`status-pill status-${String(row.status).toLowerCase()}`}
                          >
                            {labelStatus(row.status)}
                          </i>
                        </span>
                        <button
                          className="btn btn-small btn-secondary"
                          onClick={() => openApplicationFromList(row)}
                        >
                          {row.status === "DRAFT"
                            ? "Continue draft"
                            : "View application"}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
          {page === "applications" && (
            <>
              <div className="page-heading">
                <div>
                  <span className="section-kicker">APPLICATION TRACKING</span>
                  <h1>My applications</h1>
                  <p>
                    View your drafts, submitted applications and
                    customer-visible review status.
                  </p>
                </div>
                <button
                  className="btn btn-primary"
                  onClick={startApplication}
                  disabled={busy}
                >
                  <Plus size={17} /> New application
                </button>
              </div>
              <section className="surface-card">
                {apps.length ? (
                  <div className="table-scroll">
                    <table className="customer-table">
                      <thead>
                        <tr>
                          <th>Application</th>
                          <th>Lender / Purpose</th>
                          <th>Requested loan</th>
                          <th>Submitted</th>
                          <th>Status</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {apps.map((row) => (
                          <tr key={row.id}>
                            <td>
                              <b>{row.reference}</b>
                              <small>
                                Updated{" "}
                                {new Date(row.updated_at).toLocaleDateString(
                                  "en-IN",
                                )}
                              </small>
                            </td>
                            <td>
                              {row.lender_name || "Lender not selected"}
                              <small>
                                {row.details?.loan?.purpose ||
                                  row.product_name ||
                                  "Mortgage"}
                              </small>
                            </td>
                            <td>{money(row.requested_loan)}</td>
                            <td>
                              {row.submitted_at
                                ? new Date(row.submitted_at).toLocaleDateString(
                                    "en-IN",
                                  )
                                : "Not submitted"}
                            </td>
                            <td>
                              <span
                                className={`status-pill status-${String(row.status).toLowerCase()}`}
                              >
                                {labelStatus(row.status)}
                              </span>
                            </td>
                            <td>
                              <div className="customer-row-actions">
                                <button
                                  className="btn btn-small btn-secondary"
                                  onClick={() => openApplicationFromList(row)}
                                >
                                  {row.status === "DRAFT"
                                    ? "Continue draft"
                                    : "View details"}
                                </button>
                                {row.status === "DRAFT" && (
                                  <button
                                    className="customer-icon-delete"
                                    title="Delete draft"
                                    aria-label={`Delete draft ${row.reference}`}
                                    disabled={deletingApplications.includes(
                                      row.id,
                                    )}
                                    onClick={() => deleteDraftApplication(row)}
                                  >
                                    <Trash2 size={15} />
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState
                    title="No applications found"
                    description="Create a new mortgage application to get started."
                    action="Start application"
                    onAction={startApplication}
                  />
                )}
              </section>
            </>
          )}
          {page === "application" && app && (
            <>
              <div className="page-heading application-heading">
                <div>
                  <button
                    className="back-link"
                    onClick={() => {
                      setPage("applications");
                      setApp(null);
                      clearFeedback();
                    }}
                  >
                    <ArrowLeft size={15} /> My applications
                  </button>
                  <span className="section-kicker">{app.reference}</span>
                  <h1>
                    {app.status === "DRAFT"
                      ? "Mortgage application"
                      : "Application details"}
                  </h1>
                  <p>
                    {app.status === "DRAFT"
                      ? "Complete each section and save your progress at any time."
                      : "View your submitted details, documents and permitted status updates."}
                  </p>
                </div>
                <span
                  className={`status-pill status-${String(app.status).toLowerCase()}`}
                >
                  {labelStatus(app.status)}
                </span>
              </div>
              {editable && step === -1 && (
                <section className="surface-card upload-first-step">
                  <div className="wizard-progress-top upload-step-progress">
                    <b>Step 1 · Documents upload</b>
                    <span>Next: six-step mortgage application</span>
                  </div>
                  <div className="form-section-title">
                    <span>
                      <UploadCloud size={17} />
                    </span>
                    <div>
                      <h2>Documents upload</h2>
                      <p>
                        Upload available evidence first. You can add more
                        documents later; the checklist marks the current
                        application requirements, while additional
                        lender-specific requests may be made during review.
                      </p>
                    </div>
                  </div>
                  <div className="form-grid upload-bank-select">
                    <Field
                      label="Lender / bank"
                      value={form.lender_name}
                      onChange={(value) => updateForm("lender_name", value)}
                      options={
                        banks.length
                          ? banks.map((bank) => ({
                              value: bank.code,
                              label: bank.name,
                            }))
                          : []
                      }
                      hint="Select the intended lender if known. The checklist reflects the requirements currently returned by the application service."
                    />
                  </div>
                  <DocumentChecklist
                    docs={docs}
                    requirements={docRequirements}
                  />
                  <div className="upload-panel">
                    <div className="form-grid upload-fields">
                      <Field
                        label="Document category"
                        value={selectedCategory}
                        onChange={setSelectedCategory}
                        options={CATEGORIES.map((c) => ({
                          value: c.value,
                          label: c.label,
                        }))}
                      />
                      <label className="form-field">
                        <span>Select files</span>
                        <input
                          type="file"
                          multiple
                          accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff"
                          onChange={uploadDocument}
                          disabled={busy}
                        />
                        <small className="field-hint">
                          Select multiple PDF, PNG, JPG or TIFF files for this
                          category. Choose another category to add those
                          documents too.
                        </small>
                      </label>
                    </div>
                    <div className="inline-info">
                      <Info size={16} /> Uploading runs the existing OCR
                      extraction. Use each document’s Run Analysis action or
                      analyze all uploaded documents after upload.
                    </div>
                  </div>
                  <div className="document-cards">
                    {docs.map((doc) => (
                      <DocumentCard
                        key={doc.id}
                        doc={doc}
                        editable
                        busy={busy}
                        drafts={fieldDrafts[doc.id] || {}}
                        setDrafts={(updates) =>
                          setDocumentFieldDrafts(doc.id, updates)
                        }
                        saveFields={() => saveFieldCorrection(doc)}
                        saveText={() => saveTextCorrection(doc)}
                        runDocAnalysis={(force) =>
                          runDocumentAnalysis(doc, force)
                        }
                        analysing={analysingDocs.includes(doc.id)}
                        downloadFile={() =>
                          download(
                            `/applications/${app.id}/documents/${doc.id}/file`,
                            doc.original_filename,
                          ).catch(fail)
                        }
                        onRemove={() => removeDocument(doc)}
                        onReplace={(event) => replaceDocument(doc, event)}
                        onConfirmCategory={confirmDocumentCategory}
                      />
                    ))}
                    {!docs.length && (
                      <EmptyState
                        icon={UploadCloud}
                        title="Upload documents to get started"
                        description="You can select several files in the same category, then repeat for other document types."
                      />
                    )}
                  </div>
                  <div className="document-analysis-action">
                    <div>
                      <b>Document analysis</b>
                      <p>
                        Analyze available OCR text using the existing NVIDIA
                        document pipeline.
                      </p>
                    </div>
                    <button
                      className="btn btn-secondary"
                      disabled={
                        busy ||
                        !docs.length ||
                        docs.some(
                          (doc) =>
                            doc.category_match_status === "MISMATCH_PENDING",
                        )
                      }
                      onClick={runAnalysis}
                    >
                      <Activity size={16} /> Analyze uploaded documents
                    </button>
                  </div>
                  <div className="wizard-actions">
                    <button
                      className="btn btn-quiet"
                      onClick={() => saveDraft().catch(fail)}
                      disabled={busy}
                    >
                      <Save size={15} /> Save draft
                    </button>
                    <button
                      className="btn btn-primary"
                      onClick={async () => {
                        try {
                          if (docs.length && !analysis) await runAnalysis();
                          setStep(0);
                          setTab("details");
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        } catch (e) {
                          fail(e);
                        }
                      }}
                      disabled={busy}
                    >
                      Continue to application <ArrowRight size={15} />
                    </button>
                  </div>
                </section>
              )}
              {editable && step >= 0 && (
                <div className="wizard-progress">
                  <div className="wizard-progress-top">
                    <b>Application progress</b>
                    <span>Step {step + 1} of 6</span>
                  </div>
                  <div className="progress-track">
                    <span style={{ width: `${((step + 1) / 6) * 100}%` }} />
                  </div>
                  <div className="wizard-steps">
                    {[
                      "Applicant",
                      "Loan & income",
                      "Financial details",
                      "Property",
                      "Documents",
                      "Review & submit",
                    ].map((name, i) => (
                      <button
                        key={name}
                        className={`${step === i ? "current" : ""} ${step > i ? "done" : ""}`}
                        onClick={() => setStep(i)}
                      >
                        <span>{step > i ? <Check size={13} /> : i + 1}</span>
                        {name}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {!editable && (
                <div className="readonly-banner">
                  <Info size={17} />
                  <span>
                    This application is{" "}
                    <b>{labelStatus(app.status).toLowerCase()}</b>. Submitted
                    application fields are read-only unless the bank requests
                    additional information.
                  </span>
                </div>
              )}
              {step >= 0 && (
                <div className="application-tabs">
                  <button
                    className={tab === "details" ? "selected" : ""}
                    onClick={() => setTab("details")}
                  >
                    Application details
                  </button>
                  <button
                    className={tab === "documents" ? "selected" : ""}
                    onClick={() => setTab("documents")}
                  >
                    Documents <span>{docs.length}</span>
                  </button>
                  <button
                    className={tab === "analysis" ? "selected" : ""}
                    onClick={() => setTab("analysis")}
                  >
                    Document analysis
                  </button>
                  <button
                    className={tab === "activity" ? "selected" : ""}
                    onClick={() => setTab("activity")}
                  >
                    History
                  </button>
                </div>
              )}
              {submissionIssues.length > 0 && (
                <section className="submission-validation" role="alert">
                  <b>Complete these required items before submitting:</b>
                  <ul>
                    {submissionIssues.map((issue, index) => (
                      <li key={`${issue.label}-${index}`}>
                        <button
                          type="button"
                          onClick={() => {
                            setStep(issue.step);
                            setTab("details");
                            window.scrollTo({ top: 0, behavior: "smooth" });
                          }}
                        >
                          {issue.label}
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              {tab === "details" && (
                <section
                  className="surface-card form-surface"
                  data-submission-attempted={
                    submissionIssues.length > 0 ? "true" : "false"
                  }
                >
                  {step === 0 && (
                    <>
                      <div className="form-section-title">
                        <span>01</span>
                        <div>
                          <h2>Applicant details</h2>
                          <p>
                            Use the applicant's legal and current contact
                            details.
                          </p>
                        </div>
                      </div>
                      <div className="form-grid">
                        <MappedField
                          label="Full name"
                          sources={
                            ocrFieldSources["details.applicant.full_name"]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.applicant.full_name",
                              source,
                            )
                          }
                          value={currentApplicant.full_name}
                          onChange={(v) =>
                            updateSection("applicant", "full_name", v)
                          }
                          required
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Date of birth"
                          type="date"
                          sources={
                            ocrFieldSources["details.applicant.date_of_birth"]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.applicant.date_of_birth",
                              source,
                            )
                          }
                          value={currentApplicant.date_of_birth}
                          onChange={(v) =>
                            updateSection("applicant", "date_of_birth", v)
                          }
                          required
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Gender"
                          sources={ocrFieldSources["details.applicant.gender"]}
                          onSelectSource={(source) =>
                            confirmOcrSource("details.applicant.gender", source)
                          }
                          value={currentApplicant.gender}
                          onChange={(v) =>
                            updateSection("applicant", "gender", v)
                          }
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Age (as stated on document)"
                          sources={ocrFieldSources["details.applicant.age"]}
                          onSelectSource={(source) =>
                            confirmOcrSource("details.applicant.age", source)
                          }
                          value={currentApplicant.age}
                          onChange={(v) => updateSection("applicant", "age", v)}
                          readOnly={applicationReadOnly}
                          hint="Verify the stated age against the document date."
                        />
                        <MappedField
                          label="Mobile number"
                          type="tel"
                          placeholder="10-digit mobile number"
                          sources={ocrFieldSources["details.applicant.mobile"]}
                          onSelectSource={(source) =>
                            confirmOcrSource("details.applicant.mobile", source)
                          }
                          value={currentApplicant.mobile}
                          onChange={(v) =>
                            updateSection("applicant", "mobile", v)
                          }
                          required
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Email address"
                          type="email"
                          placeholder="name@example.com"
                          sources={ocrFieldSources["details.applicant.email"]}
                          onSelectSource={(source) =>
                            confirmOcrSource("details.applicant.email", source)
                          }
                          value={currentApplicant.email}
                          onChange={(v) =>
                            updateSection("applicant", "email", v)
                          }
                          required
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Residential address"
                          sources={
                            ocrFieldSources[
                              "details.applicant.residential_address"
                            ]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.applicant.residential_address",
                              source,
                            )
                          }
                          value={currentApplicant.residential_address}
                          onChange={(v) =>
                            updateSection("applicant", "residential_address", v)
                          }
                          full
                          required
                          readOnly={applicationReadOnly}
                          placeholder="House/flat, street, area, city, state and PIN code"
                        />
                        <Field
                          label="Current address (if different)"
                          value={currentApplicant.current_address}
                          onChange={(v) =>
                            updateSection("applicant", "current_address", v)
                          }
                          full
                          readOnly={applicationReadOnly}
                          placeholder="Leave blank if same as residential address"
                        />
                      </div>
                    </>
                  )}
                  {step === 1 && (
                    <>
                      <div className="form-section-title">
                        <span>02</span>
                        <div>
                          <h2>Loan requirements, employment & income</h2>
                          <p>
                            Enter declared information. Submission does not
                            imply eligibility or approval.
                          </p>
                        </div>
                      </div>
                      <div className="form-grid">
                        <MappedField
                          label="Loan type / purpose"
                          sources={ocrFieldSources["details.loan.purpose"]}
                          onSelectSource={(source) =>
                            confirmOcrSource("details.loan.purpose", source)
                          }
                          value={currentLoan.purpose}
                          onChange={(v) => updateSection("loan", "purpose", v)}
                          options={[
                            "Home Purchase",
                            "Home Construction",
                            "Home Improvement",
                            "Home Extension",
                            "Balance Transfer",
                          ]}
                          required
                          readOnly={applicationReadOnly}
                        />
                        <Field
                          label="Lender / bank"
                          value={form.lender_name}
                          onChange={(v) => updateForm("lender_name", v)}
                          options={
                            banks.length
                              ? banks.map((b) => ({
                                  value: b.code,
                                  label: b.name,
                                }))
                              : []
                          }
                          required
                          readOnly={applicationReadOnly}
                          hint={
                            banks.length
                              ? "Only banks approved by the platform are listed."
                              : "No approved banks are currently available. Bank onboarding must be completed first."
                          }
                        />
                        <MappedField
                          label="Loan type / product"
                          sources={ocrFieldSources.product_name}
                          onSelectSource={(source) =>
                            confirmOcrSource("product_name", source)
                          }
                          value={form.product_name}
                          onChange={(v) => updateForm("product_name", v)}
                          placeholder="e.g. Home loan"
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Requested loan amount (₹)"
                          type="number"
                          min="1"
                          step="1"
                          placeholder="Enter amount in ₹"
                          sources={ocrFieldSources.requested_loan}
                          onSelectSource={(source) =>
                            confirmOcrSource("requested_loan", source)
                          }
                          value={form.requested_loan}
                          onChange={(v) => updateForm("requested_loan", v)}
                          required
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Preferred tenure (years)"
                          type="number"
                          min="1"
                          max="40"
                          step="1"
                          placeholder="e.g. 20"
                          sources={ocrFieldSources.tenure_years}
                          onSelectSource={(source) =>
                            confirmOcrSource("tenure_years", source)
                          }
                          value={form.tenure_years}
                          onChange={(v) => updateForm("tenure_years", v)}
                          required
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Employment type"
                          sources={
                            ocrFieldSources[
                              "details.employment.employment_type"
                            ]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.employment.employment_type",
                              source,
                            )
                          }
                          value={currentEmployment.employment_type}
                          onChange={(v) => {
                            updateSection("employment", "employment_type", v);
                            updateSection("loan", "income_category", v);
                          }}
                          options={[
                            "Salaried",
                            "Self-employed",
                            "Business owner",
                            "Professional",
                            "Other",
                          ]}
                          required
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Employer / business name"
                          sources={
                            ocrFieldSources["details.employment.employer_name"]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.employment.employer_name",
                              source,
                            )
                          }
                          value={currentEmployment.employer_name}
                          onChange={(v) =>
                            updateSection("employment", "employer_name", v)
                          }
                          required={
                            currentEmployment.employment_type === "Salaried" ||
                            currentEmployment.employment_type ===
                              "Business owner" ||
                            currentEmployment.employment_type ===
                              "Self-employed"
                          }
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Occupation"
                          sources={
                            ocrFieldSources["details.employment.occupation"]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.employment.occupation",
                              source,
                            )
                          }
                          value={currentEmployment.occupation}
                          onChange={(v) =>
                            updateSection("employment", "occupation", v)
                          }
                          required
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Employment / business duration"
                          sources={
                            ocrFieldSources[
                              "details.employment.business_duration"
                            ]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.employment.business_duration",
                              source,
                            )
                          }
                          value={currentEmployment.business_duration}
                          onChange={(v) =>
                            updateSection("employment", "business_duration", v)
                          }
                          placeholder="e.g. 4 years"
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Monthly income (₹)"
                          type="number"
                          min="0"
                          step="1"
                          sources={
                            ocrFieldSources["details.employment.monthly_income"]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.employment.monthly_income",
                              source,
                            )
                          }
                          value={currentEmployment.monthly_income}
                          onChange={(v) =>
                            updateSection("employment", "monthly_income", v)
                          }
                          readOnly={applicationReadOnly}
                          hint="Enter monthly income, annual income, or both."
                        />
                        <MappedField
                          label="Annual income (₹)"
                          type="number"
                          min="0"
                          step="1"
                          sources={ocrFieldSources.annual_income}
                          onSelectSource={(source) => {
                            confirmOcrSource("annual_income", source);
                            confirmOcrSource(
                              "details.employment.annual_income",
                              source,
                            );
                          }}
                          value={form.annual_income}
                          onChange={(v) => {
                            updateForm("annual_income", v);
                            updateSection("employment", "annual_income", v);
                          }}
                          readOnly={applicationReadOnly}
                          hint="At least one income figure is required."
                        />
                        <MappedField
                          label="Other declared annual income (₹)"
                          sources={
                            ocrFieldSources["details.employment.other_income"]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.employment.other_income",
                              source,
                            )
                          }
                          type="number"
                          min="0"
                          step="1"
                          value={currentEmployment.other_income}
                          onChange={(v) =>
                            updateSection("employment", "other_income", v)
                          }
                          readOnly={applicationReadOnly}
                        />
                        <Field
                          label="Existing monthly loan obligations (₹)"
                          type="number"
                          min="0"
                          step="1"
                          value={form.monthly_debt}
                          onChange={(v) => updateForm("monthly_debt", v)}
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Applicant contribution / down payment (₹)"
                          type="number"
                          min="0"
                          step="1"
                          sources={ocrFieldSources["details.loan.down_payment"]}
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.loan.down_payment",
                              source,
                            )
                          }
                          value={currentLoan.down_payment}
                          onChange={(v) =>
                            updateSection("loan", "down_payment", v)
                          }
                          readOnly={applicationReadOnly}
                        />
                        <Field
                          label="Income source"
                          value={currentEmployment.income_source}
                          onChange={(v) =>
                            updateSection("employment", "income_source", v)
                          }
                          placeholder="Salary, business, professional income…"
                          readOnly={applicationReadOnly}
                        />
                        <Field
                          label="Repayment preference"
                          value={currentLoan.repayment_preference}
                          onChange={(v) =>
                            updateSection("loan", "repayment_preference", v)
                          }
                          options={["Monthly EMI", "Other / to be discussed"]}
                          readOnly={applicationReadOnly}
                        />
                      </div>
                      {currentEmployment.employment_type &&
                        currentEmployment.employment_type !== "Salaried" && (
                          <div className="inline-info">
                            <Info size={16} /> Self-employed/business applicants
                            should upload applicable ITR and supporting
                            business/income evidence. W-2/1099 formats are not
                            assumed for Indian applicants.
                          </div>
                        )}
                      <div className="coapplicant-toggle">
                        <label>
                          <input
                            type="checkbox"
                            checked={Boolean(currentLoan.co_applicant_required)}
                            disabled={applicationReadOnly}
                            onChange={(e) =>
                              updateSection(
                                "loan",
                                "co_applicant_required",
                                e.target.checked,
                              )
                            }
                          />{" "}
                          Add a co-applicant (if applicable)
                        </label>
                      </div>
                      {currentLoan.co_applicant_required && (
                        <div className="form-grid nested-grid">
                          <Field
                            label="Co-applicant full name"
                            value={form.details?.co_applicant?.full_name}
                            onChange={(v) =>
                              updateSection("co_applicant", "full_name", v)
                            }
                            required
                            readOnly={applicationReadOnly}
                          />
                          <Field
                            label="Relationship"
                            value={form.details?.co_applicant?.relationship}
                            onChange={(v) =>
                              updateSection("co_applicant", "relationship", v)
                            }
                            required
                            readOnly={applicationReadOnly}
                          />
                          <Field
                            label="Co-applicant mobile"
                            value={form.details?.co_applicant?.mobile}
                            onChange={(v) =>
                              updateSection("co_applicant", "mobile", v)
                            }
                            type="tel"
                            readOnly={applicationReadOnly}
                          />
                          <Field
                            label="Co-applicant email"
                            value={form.details?.co_applicant?.email}
                            onChange={(v) =>
                              updateSection("co_applicant", "email", v)
                            }
                            type="email"
                            readOnly={applicationReadOnly}
                          />
                          <Field
                            label="Co-applicant annual income (₹)"
                            value={form.details?.co_applicant?.annual_income}
                            onChange={(v) =>
                              updateSection("co_applicant", "annual_income", v)
                            }
                            type="number"
                            readOnly={applicationReadOnly}
                          />
                          <Field
                            label="Co-applicant employment type"
                            value={form.details?.co_applicant?.employment_type}
                            onChange={(v) =>
                              updateSection(
                                "co_applicant",
                                "employment_type",
                                v,
                              )
                            }
                            options={[
                              "Salaried",
                              "Self-employed",
                              "Business owner",
                              "Other",
                            ]}
                            readOnly={applicationReadOnly}
                          />
                        </div>
                      )}
                    </>
                  )}
                  {step === 2 && (
                    <>
                      <div className="form-section-title">
                        <span>03</span>
                        <div>
                          <h2>Financial evidence</h2>
                          <p>
                            Use uploaded bank statements and income documents as
                            evidence. No bank account details or existing debt
                            need to be typed into this form.
                          </p>
                        </div>
                      </div>
                      {ocrFieldSources["details.bank.account_holder_name"]
                        ?.length > 0 ||
                      ocrFieldSources["details.bank.bank_name"]?.length > 0 ||
                      ocrFieldSources["details.bank.ifsc"]?.length > 0 ||
                      ocrFieldSources.interest_rate?.length > 0 ? (
                        <div className="form-grid">
                          {ocrFieldSources["details.bank.account_holder_name"]
                            ?.length > 0 && (
                            <MappedField
                              label="Account holder (from document)"
                              sources={
                                ocrFieldSources[
                                  "details.bank.account_holder_name"
                                ]
                              }
                              onSelectSource={(source) =>
                                confirmOcrSource(
                                  "details.bank.account_holder_name",
                                  source,
                                )
                              }
                              value={currentBank.account_holder_name}
                              onChange={() => {}}
                              readOnly
                            />
                          )}
                          {ocrFieldSources["details.bank.bank_name"]?.length >
                            0 && (
                            <MappedField
                              label="Bank name (from document)"
                              sources={
                                ocrFieldSources["details.bank.bank_name"]
                              }
                              onSelectSource={(source) =>
                                confirmOcrSource(
                                  "details.bank.bank_name",
                                  source,
                                )
                              }
                              value={currentBank.bank_name}
                              onChange={() => {}}
                              readOnly
                            />
                          )}
                          {ocrFieldSources["details.bank.ifsc"]?.length > 0 && (
                            <MappedField
                              label="IFSC (from document)"
                              sources={ocrFieldSources["details.bank.ifsc"]}
                              onSelectSource={(source) =>
                                confirmOcrSource("details.bank.ifsc", source)
                              }
                              value={currentBank.ifsc}
                              onChange={() => {}}
                              readOnly
                            />
                          )}
                          {ocrFieldSources.interest_rate?.length > 0 && (
                            <MappedField
                              label="Interest rate (%) (from document)"
                              type="number"
                              sources={ocrFieldSources.interest_rate}
                              onSelectSource={(source) =>
                                confirmOcrSource("interest_rate", source)
                              }
                              value={form.interest_rate}
                              onChange={() => {}}
                              readOnly
                            />
                          )}
                        </div>
                      ) : (
                        <p className="muted-copy">
                          Upload a bank statement or income document to use its
                          extracted evidence. Requirements depend on the
                          selected bank’s policy.
                        </p>
                      )}
                    </>
                  )}
                  {step === 3 && (
                    <>
                      <div className="form-section-title">
                        <span>04</span>
                        <div>
                          <h2>Property details</h2>
                          <p>
                            Declared values are not independently verified until
                            supporting evidence is reviewed.
                          </p>
                        </div>
                      </div>
                      <div className="form-grid">
                        <MappedField
                          label="Property type"
                          sources={
                            ocrFieldSources["details.property.property_type"]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.property.property_type",
                              source,
                            )
                          }
                          value={currentProperty.property_type}
                          onChange={(v) =>
                            updateSection("property", "property_type", v)
                          }
                          options={[
                            "Apartment / Flat",
                            "Independent House",
                            "Plot / Land",
                            "Under-construction property",
                            "Other",
                          ]}
                          required
                          readOnly={applicationReadOnly}
                        />
                        <Field
                          label="Property status"
                          value={currentProperty.property_status}
                          onChange={(v) =>
                            updateSection("property", "property_status", v)
                          }
                          options={[
                            "Proposed",
                            "Under Construction",
                            "Ready to Move",
                            "Existing property",
                            "Other",
                          ]}
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Property address"
                          sources={ocrFieldSources.property_address}
                          onSelectSource={(source) =>
                            confirmOcrSource("property_address", source)
                          }
                          value={form.property_address}
                          onChange={(v) => {
                            updateForm("property_address", v);
                            updateSection("property", "location", v);
                          }}
                          full
                          required
                          readOnly={applicationReadOnly}
                          placeholder="Full property address"
                        />
                        <Field
                          label="Property location / locality"
                          value={currentProperty.location}
                          onChange={(v) =>
                            updateSection("property", "location", v)
                          }
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Agreement / declared value (₹)"
                          sources={ocrFieldSources.property_value}
                          onSelectSource={(source) =>
                            confirmOcrSource("property_value", source)
                          }
                          value={form.property_value}
                          onChange={(v) => updateForm("property_value", v)}
                          type="number"
                          min="1"
                          placeholder="Enter amount in ₹"
                          required
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Estimated market value (₹), if available"
                          sources={
                            ocrFieldSources[
                              "details.property.estimated_market_value"
                            ]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.property.estimated_market_value",
                              source,
                            )
                          }
                          value={currentProperty.estimated_market_value}
                          onChange={(v) =>
                            updateSection(
                              "property",
                              "estimated_market_value",
                              v,
                            )
                          }
                          type="number"
                          min="0"
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Seller / builder"
                          sources={
                            ocrFieldSources["details.property.seller_builder"]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.property.seller_builder",
                              source,
                            )
                          }
                          value={currentProperty.seller_builder}
                          onChange={(v) =>
                            updateSection("property", "seller_builder", v)
                          }
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Registration / agreement reference"
                          sources={
                            ocrFieldSources[
                              "details.property.registration_details"
                            ]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.property.registration_details",
                              source,
                            )
                          }
                          value={currentProperty.registration_details}
                          onChange={(v) =>
                            updateSection("property", "registration_details", v)
                          }
                          readOnly={applicationReadOnly}
                        />
                        <MappedField
                          label="Ownership / relationship to property"
                          sources={
                            ocrFieldSources[
                              "details.property.ownership_relationship"
                            ]
                          }
                          onSelectSource={(source) =>
                            confirmOcrSource(
                              "details.property.ownership_relationship",
                              source,
                            )
                          }
                          value={currentProperty.ownership_relationship}
                          onChange={(v) =>
                            updateSection(
                              "property",
                              "ownership_relationship",
                              v,
                            )
                          }
                          readOnly={applicationReadOnly}
                        />
                        <Field
                          label="Additional application notes"
                          value={form.customer_notes}
                          onChange={(v) => updateForm("customer_notes", v)}
                          full
                          type="textarea"
                          readOnly={applicationReadOnly}
                          placeholder="Add relevant information for the application. Do not include passwords or account PINs."
                        />
                      </div>
                    </>
                  )}
                  {step === 4 && (
                    <>
                      <div className="form-section-title">
                        <span>05</span>
                        <div>
                          <h2>Supporting documents</h2>
                          <p>
                            The checklist shows current application
                            requirements; requirements may depend on application
                            details and bank policy.
                          </p>
                        </div>
                      </div>
                      <DocumentChecklist
                        docs={docs}
                        requirements={docRequirements}
                      />
                      <div className="upload-panel">
                        <div className="form-grid upload-fields">
                          <Field
                            label="Document category"
                            value={selectedCategory}
                            onChange={setSelectedCategory}
                            options={CATEGORIES.map((c) => ({
                              value: c.value,
                              label: c.label,
                            }))}
                          />
                          <label className="form-field">
                            <span>Select files *</span>
                            <input
                              type="file"
                              multiple
                              accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff"
                              onChange={uploadDocument}
                              disabled={!editable || busy}
                            />
                            <small className="field-hint">
                              Select multiple PDF, PNG, JPG or TIFF files for
                              this category.
                            </small>
                          </label>
                        </div>
                        <div className="inline-info">
                          <Info size={16} /> Upload confirms receipt only. OCR
                          can fail or misread information; verify extracted
                          values against the original document.
                        </div>
                      </div>
                      <div className="document-cards">
                        {docs.map((doc) => (
                          <DocumentCard
                            key={doc.id}
                            doc={doc}
                            editable={Boolean(editable)}
                            busy={busy}
                            drafts={fieldDrafts[doc.id] || {}}
                            setDrafts={(updates) =>
                              setDocumentFieldDrafts(doc.id, updates)
                            }
                            saveFields={() => saveFieldCorrection(doc)}
                            saveText={() => saveTextCorrection(doc)}
                            runDocAnalysis={(force) =>
                              runDocumentAnalysis(doc, force)
                            }
                            analysing={analysingDocs.includes(doc.id)}
                            downloadFile={() =>
                              download(
                                `/applications/${app.id}/documents/${doc.id}/file`,
                                doc.original_filename,
                              ).catch(fail)
                            }
                            onRemove={() => removeDocument(doc)}
                            onReplace={(event) => replaceDocument(doc, event)}
                            onConfirmCategory={confirmDocumentCategory}
                          />
                        ))}
                        {!docs.length && (
                          <EmptyState
                            icon={UploadCloud}
                            title="No documents uploaded"
                            description="Select a category above and upload the first supporting document."
                          />
                        )}
                      </div>
                      <div className="document-analysis-action">
                        <div>
                          <b>Document intelligence</b>
                          <p>
                            Run the configured NVIDIA analysis service on
                            successfully extracted document text.
                          </p>
                        </div>
                        <button
                          className="btn btn-secondary"
                          disabled={
                            busy ||
                            !docs.length ||
                            !editable ||
                            docs.some(
                              (doc) =>
                                doc.category_match_status ===
                                "MISMATCH_PENDING",
                            )
                          }
                          onClick={runAnalysis}
                        >
                          <Activity size={16} />{" "}
                          {busy ? "Processing…" : "Analyze all documents"}
                        </button>
                      </div>
                    </>
                  )}
                  {step === 5 && (
                    <>
                      <div className="form-section-title">
                        <span>06</span>
                        <div>
                          <h2>Review and submit</h2>
                          <p>
                            Review your entries and acknowledge the declarations
                            before submission.
                          </p>
                        </div>
                      </div>
                      <div className="review-summary">
                        <SummaryRow
                          label="Applicant"
                          value={currentApplicant.full_name || "Not provided"}
                        />
                        <SummaryRow
                          label="Email"
                          value={currentApplicant.email || "Not provided"}
                        />
                        <SummaryRow
                          label="Loan purpose"
                          value={currentLoan.purpose || "Not selected"}
                        />
                        <SummaryRow
                          label="Lender"
                          value={
                            banks.find((b) => b.code === form.lender_name)
                              ?.name ||
                            form.lender_name ||
                            "Not selected"
                          }
                        />
                        <SummaryRow
                          label="Requested loan"
                          value={money(form.requested_loan)}
                        />
                        <SummaryRow
                          label="Declared property value"
                          value={money(form.property_value)}
                        />
                        <SummaryRow
                          label="Annual income"
                          value={money(form.annual_income)}
                        />
                        <SummaryRow
                          label="Documents uploaded"
                          value={`${docs.length} file(s)`}
                        />
                        <SummaryRow
                          label="Current state"
                          value={labelStatus(app.status)}
                        />
                      </div>
                      {estimates &&
                        (Number(form.requested_loan) > 0 ||
                          Number(form.property_value) > 0) && (
                          <div className="estimate-card">
                            <div className="estimate-card-title">
                              <b>Deterministic financial estimates</b>
                              <small>
                                Calculated by the backend from the values
                                currently saved in this draft.
                              </small>
                            </div>
                            <div className="estimate-metrics">
                              <div>
                                <span>Estimated monthly EMI</span>
                                <b>
                                  {money(estimates.estimated_monthly_emi_inr)}
                                </b>
                              </div>
                              <div>
                                <span>Loan-to-value (LTV)</span>
                                <b>
                                  {estimates.loan_to_value_percent == null
                                    ? "Not available"
                                    : `${estimates.loan_to_value_percent}%`}
                                </b>
                              </div>
                              <div>
                                <span>Debt-to-income (DTI)</span>
                                <b>
                                  {estimates.debt_to_income_percent == null
                                    ? "Not available"
                                    : `${estimates.debt_to_income_percent}%`}
                                </b>
                              </div>
                            </div>
                            <p>
                              {estimates.disclaimer}
                              {estimates.income_basis
                                ? ` ${estimates.income_basis}`
                                : ""}
                            </p>
                          </div>
                        )}
                      {editable && (
                        <div className="consent-stack">
                          <label>
                            <input
                              type="checkbox"
                              required
                              checked={Boolean(
                                form.consents?.truthful_information,
                              )}
                              onChange={(e) =>
                                updateForm("consents", {
                                  ...form.consents,
                                  truthful_information: e.target.checked,
                                })
                              }
                            />{" "}
                            I confirm that the information provided is accurate
                            to the best of my knowledge. *
                          </label>
                          <label>
                            <input
                              type="checkbox"
                              required
                              checked={Boolean(form.consents?.privacy_consent)}
                              onChange={(e) =>
                                updateForm("consents", {
                                  ...form.consents,
                                  privacy_consent: e.target.checked,
                                })
                              }
                            />{" "}
                            I consent to processing of my application documents
                            for mortgage assessment, subject to applicable
                            privacy notices. *
                          </label>
                        </div>
                      )}
                      <div className="inline-info">
                        <ShieldCheck size={16} /> Submission confirms the
                        application details only. It is not a loan approval. The
                        backend will validate required fields and documents
                        before accepting submission.
                      </div>
                      {editable && (
                        <button
                          className="btn btn-primary submit-application"
                          disabled={busy}
                          onClick={requestApplicationSubmit}
                        >
                          Submit application <ArrowRight size={16} />
                        </button>
                      )}
                    </>
                  )}
                  {editable && (
                    <div className="wizard-actions">
                      <button
                        className="btn btn-secondary"
                        onClick={previousStep}
                        disabled={step === 0 || busy}
                      >
                        <ArrowLeft size={15} /> Previous
                      </button>
                      <div className="save-state">
                        {lastSaved && (
                          <small>
                            Last saved{" "}
                            {new Date(lastSaved).toLocaleTimeString("en-IN", {
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </small>
                        )}
                        <button
                          className="btn btn-quiet"
                          onClick={() => saveDraft().catch(fail)}
                          disabled={busy}
                        >
                          <Save size={15} /> Save draft
                        </button>
                      </div>
                      {step < 5 && (
                        <button
                          className="btn btn-primary"
                          onClick={nextStep}
                          disabled={busy}
                        >
                          Save & continue <ArrowRight size={15} />
                        </button>
                      )}
                    </div>
                  )}
                  {!editable && (
                    <div className="wizard-actions">
                      <button
                        className="btn btn-secondary"
                        onClick={() =>
                          download(
                            `/applications/${app.id}/receipt.pdf`,
                            `${app.reference}-receipt.pdf`,
                          ).catch(fail)
                        }
                        disabled={app.status === "DRAFT"}
                      >
                        <Download size={15} /> Download submission receipt
                      </button>
                      <button
                        className="btn btn-quiet"
                        onClick={() => setTab("activity")}
                      >
                        View history <ArrowRight size={15} />
                      </button>
                    </div>
                  )}
                </section>
              )}
              {tab === "documents" && (
                <section className="surface-card">
                  <DocumentChecklist
                    docs={docs}
                    requirements={docRequirements}
                  />
                  {editable && (
                    <div className="upload-panel">
                      <div className="form-grid upload-fields">
                        <Field
                          label="Document category"
                          value={selectedCategory}
                          onChange={setSelectedCategory}
                          options={CATEGORIES.map((c) => ({
                            value: c.value,
                            label: c.label,
                          }))}
                        />
                        <label className="form-field">
                          <span>Select files *</span>
                          <input
                            type="file"
                            multiple
                            accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff"
                            onChange={uploadDocument}
                            disabled={busy}
                          />
                        </label>
                      </div>
                    </div>
                  )}
                  <div className="document-cards">
                    {docs.map((doc) => (
                      <DocumentCard
                        key={doc.id}
                        doc={doc}
                        editable={Boolean(editable)}
                        busy={busy}
                        drafts={fieldDrafts[doc.id] || {}}
                        setDrafts={(updates) =>
                          setDocumentFieldDrafts(doc.id, updates)
                        }
                        saveFields={() => saveFieldCorrection(doc)}
                        saveText={() => saveTextCorrection(doc)}
                        runDocAnalysis={(force) =>
                          runDocumentAnalysis(doc, force)
                        }
                        analysing={analysingDocs.includes(doc.id)}
                        downloadFile={() =>
                          download(
                            `/applications/${app.id}/documents/${doc.id}/file`,
                            doc.original_filename,
                          ).catch(fail)
                        }
                        onRemove={() => removeDocument(doc)}
                        onReplace={(event) => replaceDocument(doc, event)}
                        onConfirmCategory={confirmDocumentCategory}
                      />
                    ))}
                    {!docs.length && (
                      <EmptyState
                        title="No documents available"
                        description="Uploaded files and their processing status will appear here."
                      />
                    )}
                  </div>
                </section>
              )}
              {tab === "analysis" && (
                <section className="surface-card">
                  <div className="surface-heading">
                    <div>
                      <h2>Document intelligence results</h2>
                      <p>
                        AI findings are assistive observations, not verified
                        facts or lending decisions.
                      </p>
                    </div>
                    <button
                      className="btn btn-secondary"
                      disabled={
                        busy ||
                        !docs.length ||
                        !editable ||
                        docs.some(
                          (doc) =>
                            doc.category_match_status === "MISMATCH_PENDING",
                        )
                      }
                      onClick={runAnalysis}
                    >
                      <Activity size={16} /> Analyze all documents
                    </button>
                  </div>
                  {analysis ? (
                    <AnalysisPreview
                      result={analysis}
                      onOpen={() => setShowFullAnalysis(true)}
                    />
                  ) : (
                    <EmptyState
                      icon={Activity}
                      title="No saved analysis result"
                      description="Run document analysis when readable extracted text is available. NVIDIA credentials and model access are required."
                      action={editable ? "Analyze documents" : undefined}
                      onAction={runAnalysis}
                    />
                  )}
                </section>
              )}
              {tab === "activity" && (
                <section className="surface-card">
                  <div className="surface-heading">
                    <div>
                      <h2>Application history</h2>
                      <p>Customer-visible events recorded by the backend.</p>
                    </div>
                  </div>
                  <ActivityList applicationId={app.id} />
                </section>
              )}
            </>
          )}
          {page === "documents" && (
            <>
              <div className="page-heading">
                <div>
                  <span className="section-kicker">DOCUMENTS & REQUESTS</span>
                  <h1>Documents and requests</h1>
                  <p>
                    Choose an application to upload requested evidence or review
                    extraction status.
                  </p>
                </div>
              </div>
              <section className="surface-card">
                {apps.length ? (
                  <div className="application-list">
                    {apps.map((row) => (
                      <article className="application-row" key={row.id}>
                        <span className="application-icon">
                          <FolderOpen size={19} />
                        </span>
                        <div className="application-row-main">
                          <b>{row.reference}</b>
                          <p>
                            {row.lender_name || "Lender not selected"} ·{" "}
                            {labelStatus(row.status)}
                          </p>
                        </div>
                        <div className="application-row-amount">
                          <b>
                            {row.document_checklist?.filter(
                              (d) => d.status === "UPLOADED",
                            ).length || 0}{" "}
                            documents
                          </b>
                        </div>
                        <div className="customer-row-actions">
                          <button
                            className="btn btn-small btn-secondary"
                            onClick={() =>
                              openApplication(row, "application").then(() =>
                                setTab("documents"),
                              )
                            }
                          >
                            Open documents
                          </button>
                          {row.status === "DRAFT" && (
                            <button
                              className="customer-icon-delete"
                              title="Delete draft"
                              aria-label={`Delete draft ${row.reference}`}
                              disabled={deletingApplications.includes(row.id)}
                              onClick={() => deleteDraftApplication(row)}
                            >
                              <Trash2 size={15} />
                            </button>
                          )}
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    title="No application documents"
                    description="Create a mortgage application before uploading supporting documents."
                    action="Start application"
                    onAction={startApplication}
                  />
                )}
              </section>
            </>
          )}
          {page === "notifications" && (
            <>
              <div className="page-heading">
                <div>
                  <span className="section-kicker">CUSTOMER UPDATES</span>
                  <h1>Notifications</h1>
                  <p>
                    Updates reflect events recorded by the application backend.
                  </p>
                </div>
              </div>
              <section className="surface-card">
                {notifications.length ? (
                  <div className="notification-list">
                    {notifications.map((n) => (
                      <article
                        className={`notification-row ${n.read ? "read" : "unread"}`}
                        key={n.id}
                      >
                        <span className="notification-icon">
                          <Bell size={17} />
                        </span>
                        <div className="notification-body">
                          <b>{n.title}</b>
                          <p>{n.message}</p>
                          <small>
                            {new Date(n.created_at).toLocaleString("en-IN")}
                            {n.application_id
                              ? ` · Application #${n.application_id}`
                              : ""}
                          </small>
                        </div>
                        <div className="customer-row-actions">
                          <button
                            className="btn btn-small btn-secondary"
                            onClick={() => markRead(n)}
                          >
                            {n.read ? "Mark unread" : "Mark read"}
                          </button>
                          <button
                            className="customer-icon-delete"
                            title="Delete notification"
                            aria-label={`Delete notification: ${n.title}`}
                            disabled={deletingNotifications.includes(n.id)}
                            onClick={() => deleteNotification(n)}
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    icon={Bell}
                    title="You're all caught up"
                    description="Customer-visible application updates and document requests will appear here."
                  />
                )}
              </section>
            </>
          )}
          {page === "profile" && (
            <>
              <div className="page-heading">
                <div>
                  <span className="section-kicker">ACCOUNT SETTINGS</span>
                  <h1>My profile</h1>
                  <p>
                    Review your registered details and update your mobile
                    number.
                  </p>
                </div>
              </div>
              <div className="profile-layout">
                <section className="surface-card">
                  <div className="profile-card-heading">
                    <span className="profile-large-avatar">
                      {user.full_name?.[0]?.toUpperCase()}
                    </span>
                    <div>
                      <h2>{user.full_name}</h2>
                      <p>
                        {user.is_verified
                          ? "Email verified"
                          : "Email not verified"}
                      </p>
                    </div>
                  </div>
                  <form onSubmit={updateProfile} className="form-grid">
                    <Field
                      label="Full name"
                      value={user.full_name}
                      onChange={() => {}}
                      readOnly
                    />
                    <Field
                      label="Registered email"
                      value={user.email}
                      onChange={() => {}}
                      type="email"
                      readOnly
                      hint="Email changes require a separate verification workflow."
                    />
                    <Field
                      label="Mobile number"
                      value={profileMobile}
                      onChange={setProfileMobile}
                      type="tel"
                      required
                    />
                    <div className="field-full">
                      <button className="btn btn-primary" disabled={busy}>
                        Save profile changes <Check size={15} />
                      </button>
                    </div>
                  </form>
                </section>
                <section className="surface-card security-card">
                  <ShieldCheck size={22} />
                  <h2>Account security</h2>
                  <p>
                    Your session is protected by a backend-issued token. Sign
                    out when using a shared device.
                  </p>
                  <button className="btn btn-secondary" onClick={signOut}>
                    <LogOut size={15} /> Sign out
                  </button>
                </section>
              </div>
            </>
          )}
        </div>
      </main>
      {confirmSubmitOpen && (
        <div className="modal-backdrop" role="presentation">
          <section
            className="confirm-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="submit-confirm-title"
          >
            <span className="confirm-modal-icon">
              <ClipboardCheck size={22} />
            </span>
            <h2 id="submit-confirm-title">Submit this mortgage application?</h2>
            <p>
              The backend will validate required details, consent and supporting
              documents. Once submitted, editing is restricted unless the bank
              requests additional information. Submission is not loan approval.
            </p>
            <div className="confirm-modal-actions">
              <button
                className="btn btn-secondary"
                disabled={busy}
                onClick={() => setConfirmSubmitOpen(false)}
              >
                Review application
              </button>
              <button
                className="btn btn-primary"
                disabled={busy}
                onClick={submitApplication}
              >
                {busy ? "Submitting…" : "Confirm submission"}
              </button>
            </div>
          </section>
        </div>
      )}
      {showFullAnalysis && analysis && (
        <div
          className="modal-backdrop analysis-modal-backdrop"
          role="presentation"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setShowFullAnalysis(false);
          }}
        >
          <section
            className="analysis-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="full-analysis-title"
          >
            <header>
              <div>
                <span className="section-kicker">DOCUMENT INTELLIGENCE</span>
                <h2 id="full-analysis-title">Full mortgage analysis</h2>
                <p>
                  Review findings against original documents before relying on
                  them.
                </p>
              </div>
              <button
                className="btn btn-quiet"
                aria-label="Close analysis"
                onClick={() => setShowFullAnalysis(false)}
              >
                <X size={18} />
              </button>
            </header>
            <div className="analysis-modal-body">
              <AnalysisResults result={analysis} history={analysisHistory} />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function SummaryRow({ label, value }) {
  return (
    <div className="summary-row">
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}
function DocumentChecklist({ docs, requirements }) {
  const items = requirements.length
    ? requirements
    : CATEGORIES.map((c) => ({
        category: c.value,
        label: c.label,
        required: false,
        status: docs.some((d) => d.category === c.value)
          ? "UPLOADED"
          : "OPTIONAL",
      }));
  return (
    <div className="document-checklist">
      <div className="checklist-heading">
        <div>
          <b>Document checklist</b>
          <small>
            Required status is an intake baseline; bank-specific rules can add
            requirements.
          </small>
        </div>
        <span>
          {items.filter((i) => i.status === "UPLOADED").length}/{items.length}{" "}
          uploaded categories
        </span>
      </div>
      <div className="checklist-list">
        {items.map((item) => (
          <div
            className={`checklist-line ${item.status === "UPLOADED" ? "is-uploaded" : item.status === "MISSING" ? "is-missing" : "is-optional"}`}
            key={item.category}
          >
            <span className="checkmark">
              {item.status === "UPLOADED" ? (
                <Check size={13} />
              ) : item.status === "MISSING" ? (
                "!"
              ) : (
                "—"
              )}
            </span>
            <span>
              {item.label ||
                CATEGORIES.find((c) => c.value === item.category)?.label ||
                item.category}
              <small>
                {item.required
                  ? "Required for current intake checklist"
                  : "Optional / conditional by stage or policy"}
              </small>
            </span>
            <b>
              {item.status === "UPLOADED"
                ? "Uploaded"
                : item.status === "MISSING"
                  ? "Missing"
                  : "Optional"}
            </b>
          </div>
        ))}
      </div>
    </div>
  );
}
export function DocumentCard({
  doc,
  editable,
  busy,
  drafts,
  setDrafts,
  saveFields,
  saveText,
  downloadFile,
  runDocAnalysis,
  analysing,
  onRemove,
  onReplace,
  onConfirmCategory,
}) {
  const [showText, setShowText] = useState(false);
  const fields = doc.extracted_fields || {};
  const corrections = doc.corrected_fields || {};
  const keys = Object.keys(fields);
  const canAnalyse = Boolean(
    (doc.extracted_text || "").trim() || (doc.edited_text || "").trim(),
  );
  const hasAnalysisResult =
    doc.analysis_result &&
    typeof doc.analysis_result === "object" &&
    !Array.isArray(doc.analysis_result);
  const mismatchPending = doc.category_match_status === "MISMATCH_PENDING";
  const categoryUnverified = doc.category_match_status === "UNVERIFIED";
  const detectedCategoryLabel =
    CATEGORIES.find((category) => category.value === doc.detected_category)
      ?.label || doc.detected_category;
  const fieldLabel = (key) =>
    ({
      gender: "Gender",
      date_of_birth: "Date of birth",
      age: "Age",
      employment_type: "Employment type",
      occupation: "Job title / occupation",
      employment_duration: "Employment duration",
      monthly_income: "Monthly income",
      other_income: "Other income",
      total_income: "Total income",
      tax_paid: "Tax paid",
      identity_document_type: "Identity document type",
      identity_document_number: "Identity document number",
      account_number: "Bank account number",
      bank_name: "Bank name",
      residential_address: "Residential address",
      property_type: "Property type",
      ownership_relationship: "Ownership details",
      purchase_price: "Purchase price",
      agreement_value: "Agreement value",
      valuation_amount: "Property valuation",
      property_identifier: "Property identifier",
      total_debits: "Total debits / withdrawals",
      salary_credits: "Salary credits",
      recurring_commitments: "Recurring commitments",
      fees_charges: "Fees and charges",
      agreement_date: "Agreement date",
      applicant_name: "Applicant name",
      employer_name: "Employer / company",
      email: "Email address",
      mobile: "Mobile number",
      document_date: "Document date",
      annual_income: "Annual / reported income",
      gross_salary: "Gross salary",
      net_salary: "Net salary",
      property_value: "Property / valuation amount",
      loan_amount: "Loan / principal amount",
      interest_rate: "Interest rate",
      ifsc: "IFSC code",
      account_holder: "Account holder",
      property_address: "Property address",
      salary_period: "Salary period",
      deductions: "Deductions",
      assessment_year: "Assessment year",
      statement_period: "Statement period",
      opening_balance: "Opening balance",
      closing_balance: "Closing balance",
      total_credits: "Total credits / deposits",
      buyer_name: "Buyer / purchaser",
      seller_name: "Seller / vendor",
      registration_number: "Registration / document number",
      loan_tenure: "Loan tenure",
      emi_amount: "EMI / monthly instalment",
    })[key] || key.replaceAll("_", " ").replace(/^./, (x) => x.toUpperCase());
  return (
    <article className="document-card">
      <div className="document-card-head">
        <span className="document-file-icon">
          <FileText size={18} />
        </span>
        <div className="document-title">
          <b>
            {doc.category_label ||
              CATEGORIES.find((c) => c.value === doc.category)?.label ||
              doc.category}
          </b>
          <small>
            {doc.original_filename} · {Math.ceil(doc.size_bytes / 1024)} KB ·{" "}
            {new Date(doc.created_at).toLocaleDateString("en-IN")}
          </small>
        </div>
        <div className="document-status-stack">
          <span
            className={`status-pill status-${String(doc.extraction_status).toLowerCase()}`}
          >
            OCR: {doc.extraction_status || "PENDING"}
          </span>
          <span
            className={`status-pill status-${String(doc.verification_status || "PENDING").toLowerCase()}`}
          >
            Review: {labelStatus(doc.verification_status || "PENDING")}
          </span>
          <span
            className={`status-pill status-${analysing ? "running" : String(doc.analysis_status || "NOT_ANALYSED").toLowerCase()}`}
          >
            Analysis:{" "}
            {labelStatus(
              analysing ? "ANALYSING" : doc.analysis_status || "NOT_ANALYSED",
            )}
          </span>
        </div>
      </div>
      <p className="document-extraction-message">
        {doc.extraction_message || "Document received."}
      </p>
      {mismatchPending && (
        <div className="inline-error category-mismatch-warning" role="alert">
          <b>Document mismatch detected.</b>
          <span>
            You selected {doc.category_label || doc.category}, but this file
            appears to be a {detectedCategoryLabel} document. Please select the
            correct category or upload the intended document.
          </span>
          <small>
            Nemotron category check (
            {Math.round((doc.category_match_confidence || 0) * 100)}%
            confidence): {doc.category_match_reason}
          </small>
          <button
            className="btn btn-secondary btn-small"
            disabled={busy || !editable}
            onClick={() => onConfirmCategory?.(doc, doc.detected_category)}
          >
            Change category to {detectedCategoryLabel} and confirm
          </button>
          <span>
            Or use Replace file to upload the intended{" "}
            {doc.category_label || doc.category} document.
          </span>
        </div>
      )}
      {categoryUnverified && (
        <div className="inline-info category-unverified-note" role="status">
          <Info size={15} />
          <span>
            {doc.category_match_reason ||
              "The document category could not be verified."}{" "}
            {doc.detected_category
              ? `Suggested category: ${detectedCategoryLabel}.`
              : "No reliable category was detected."}
          </span>
          {editable && (
            <button
              className="btn btn-secondary btn-small"
              disabled={busy || !editable}
              onClick={() => onConfirmCategory?.(doc, doc.category)}
            >
              Confirm selected category
            </button>
          )}
        </div>
      )}
      <details className="document-fields-details">
        <summary>
          {keys.length
            ? `Expand extracted fields (${keys.length})`
            : "Extraction details"}
        </summary>
        {keys.length > 0 ? (
          <div className="extracted-fields">
            <div className="extracted-heading">
              <b>Extracted information</b>
              <small>
                OCR suggestions — verify against the original document. Only
                enter a correction when a value is wrong.
              </small>
            </div>
            <div className="form-grid">
              {keys.map((key) => {
                const metadata = fields[key] || {};
                const original = metadata.value;
                const corrected = corrections[key]?.value;
                const current =
                  drafts[key] !== undefined
                    ? drafts[key]
                    : corrected !== undefined
                      ? corrected
                      : original;
                const sensitive =
                  /account_number|identity_document_number/i.test(key);
                const changed =
                  String(current ?? "") !== String(original ?? "");
                const numeric =
                  typeof original === "number" ||
                  /amount|income|salary|balance|credits|deductions|value|emi/i.test(
                    key,
                  );
                const label = fieldLabel(key);
                const evidence = metadata.evidence;
                const page =
                  metadata.page_number ||
                  evidence?.match(/\[PAGE\s+(\d+)\]/i)?.[1] ||
                  evidencePage(doc, evidence);
                return (
                  <label className="form-field" key={key}>
                    <span>
                      {label}
                      {changed && <em className="edited-tag">Corrected</em>}
                    </span>
                    <input
                      aria-label={label}
                      placeholder={`Enter ${label.toLowerCase()}${numeric ? " in ₹" : ""}`}
                      value={safeOcrValue(key, current)}
                      type={
                        sensitive
                          ? "text"
                          : numeric
                            ? "number"
                            : key === "email"
                              ? "email"
                              : "text"
                      }
                      step={numeric ? "any" : undefined}
                      min={numeric ? "0" : undefined}
                      inputMode={numeric ? "decimal" : undefined}
                      readOnly={!editable || sensitive}
                      onChange={(e) =>
                        setDrafts({
                          [key]: numeric
                            ? e.target.value === ""
                              ? ""
                              : Number(e.target.value)
                            : e.target.value,
                        })
                      }
                    />
                    {changed && (
                      <small className="original-value">
                        Original OCR:{" "}
                        {sensitive
                          ? safeOcrValue(key, original)
                          : numeric && original !== "" && original != null
                            ? money(original)
                            : String(original ?? "Not found")}
                      </small>
                    )}
                    {corrected !== undefined && !changed && (
                      <small className="field-hint">
                        Saved correction:{" "}
                        {sensitive
                          ? safeOcrValue(key, corrected)
                          : numeric
                            ? money(corrected)
                            : String(corrected)}
                      </small>
                    )}
                    {sensitive && (
                      <small className="evidence-snippet">
                        Sensitive identifier masked
                      </small>
                    )}
                    {!sensitive && fields[key]?.evidence && (
                      <small className="evidence-snippet">
                        Source evidence{page ? ` · Page ${page}` : ""}: “
                        {evidence.replace(/^\[PAGE\s+\d+\]\s*/i, "")}"
                      </small>
                    )}
                    {fields[key]?.alternates?.length > 0 && (
                      <div className="ocr-conflict">
                        <b>
                          Multiple OCR values — confirm against the document
                        </b>
                        {fields[key].alternates.map((alternate, i) => (
                          <span key={i}>
                            {sensitive
                              ? safeOcrValue(key, alternate.value)
                              : numeric
                                ? money(alternate.value)
                                : String(alternate.value)}
                            {alternate.page_number
                              ? ` · Page ${alternate.page_number}`
                              : ""}
                          </span>
                        ))}
                      </div>
                    )}
                  </label>
                );
              })}
            </div>
            {editable &&
              Object.keys(drafts).some((key) => !key.startsWith("__")) && (
                <button
                  className="btn btn-secondary btn-small"
                  disabled={busy}
                  onClick={saveFields}
                >
                  <Save size={14} /> Save field corrections
                </button>
              )}
          </div>
        ) : (
          <div className="no-fields">
            <Info size={15} />
            <span>
              No reliably labelled fields were identified automatically. The
              extracted text remains available as source evidence; no values
              have been invented.
            </span>
          </div>
        )}
      </details>
      <div className="document-actions">
        <button className="btn btn-small btn-secondary" onClick={downloadFile}>
          <Download size={14} /> Download original
        </button>
        <button
          className="btn btn-small btn-quiet"
          onClick={() => setShowText((v) => !v)}
        >
          {showText ? "Close document details" : "View Analysis & OCR"}
        </button>
        {canAnalyse && (
          <button
            className="btn btn-small btn-primary"
            disabled={analysing || !editable || mismatchPending}
            onClick={() => runDocAnalysis(doc.analysis_status === "FAILED")}
          >
            <Activity size={14} />{" "}
            {analysing
              ? "Analysing…"
              : doc.analysis_status === "FAILED"
                ? "Retry analysis"
                : doc.analysis_status === "ANALYSED"
                  ? "Run analysis again"
                  : doc.analysis_status === "NEEDS_REANALYSIS"
                    ? "Re-run analysis"
                    : "Run analysis"}
          </button>
        )}
        {editable && onReplace && (
          <label className="btn btn-small btn-quiet replace-document">
            Replace file
            <input
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff"
              onChange={onReplace}
              disabled={busy}
            />
          </label>
        )}
        {editable && onRemove && (
          <button
            className="btn btn-small btn-quiet remove-document"
            onClick={onRemove}
            disabled={busy}
          >
            Remove
          </button>
        )}
      </div>
      {doc.analysis_status === "FAILED" && doc.analysis_error && (
        <div className="inline-error">
          Analysis failed: {doc.analysis_error}
        </div>
      )}
      {hasAnalysisResult && doc.analysis_status !== "FAILED" && (
        <details className="document-analysis-result">
          <summary>
            Saved analysis result
            {doc.analysis_status === "NEEDS_REANALYSIS"
              ? " (outdated — document changed since analysis)"
              : ""}
            {doc.analysis_duration_ms
              ? ` · ${(doc.analysis_duration_ms / 1000).toFixed(1)}s`
              : ""}
          </summary>
          <AnalysisResults
            result={{
              status: "COMPLETED",
              successful_count: 1,
              analysis_count: 1,
              results: [doc.analysis_result],
            }}
          />
        </details>
      )}
      {showText && (
        <div
          className="modal-backdrop analysis-modal-backdrop"
          role="presentation"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setShowText(false);
          }}
        >
          <section
            className="analysis-modal document-evidence-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby={`doc-evidence-${doc.id}`}
          >
            <header>
              <div>
                <span className="section-kicker">
                  {doc.category_label || doc.category}
                </span>
                <h2 id={`doc-evidence-${doc.id}`}>Document analysis & OCR</h2>
                <p>{doc.original_filename}</p>
              </div>
              <button
                className="btn btn-quiet"
                aria-label="Close document details"
                onClick={() => setShowText(false)}
              >
                <X size={18} />
              </button>
            </header>
            <div className="analysis-modal-body">
              {hasAnalysisResult && (
                <AnalysisResults
                  result={{
                    status: "COMPLETED",
                    successful_count: 1,
                    analysis_count: 1,
                    results: [doc.analysis_result],
                  }}
                />
              )}
              <div className="ocr-evidence">
                <details>
                  <summary>View Original OCR Text</summary>
                  <pre>
                    {doc.extracted_text || "No readable text was extracted."}
                  </pre>
                </details>
                <details>
                  <summary>View Corrected OCR Text</summary>
                  {doc.edited_text && <pre>{doc.edited_text}</pre>}
                  {editable && (
                    <>
                      <label className="form-field">
                        <span>Corrected OCR text (optional)</span>
                        <textarea
                          rows={5}
                          placeholder="Correct OCR text only where needed"
                          value={
                            drafts.__edited_text ??
                            doc.edited_text ??
                            doc.extracted_text ??
                            ""
                          }
                          onChange={(e) =>
                            setDrafts({ __edited_text: e.target.value })
                          }
                        />
                      </label>
                      <button
                        className="btn btn-secondary btn-small"
                        disabled={busy}
                        onClick={() =>
                          saveText({
                            ...doc,
                            edited_text:
                              drafts.__edited_text ??
                              doc.edited_text ??
                              doc.extracted_text,
                          })
                        }
                      >
                        Save text correction
                      </button>
                    </>
                  )}
                </details>
              </div>
            </div>
          </section>
        </div>
      )}
      {doc.field_correction_history?.length > 0 && (
        <details className="correction-history">
          <summary>
            Correction history ({doc.field_correction_history.length})
          </summary>
          {doc.field_correction_history
            .slice()
            .reverse()
            .slice(0, 10)
            .map((h, i) => (
              <p key={`${h.changed_at}-${i}`}>
                <b>{fieldLabel(h.field)}</b>:{" "}
                {safeOcrValue(h.field, h.previous_value ?? "—")} →{" "}
                {safeOcrValue(h.field, h.corrected_value ?? "—")}{" "}
                <small>{new Date(h.changed_at).toLocaleString("en-IN")}</small>
              </p>
            ))}
        </details>
      )}
    </article>
  );
}
function AnalysisPreview({ result, onOpen }) {
  const results = result.results || result.result?.results || [];
  const findingCount = results.reduce(
    (count, item) =>
      count +
      (item.analysis
        ? [
            item.analysis.extracted_facts,
            item.analysis.discrepancies,
            item.analysis.missing_information,
            item.analysis.risk_flags,
          ].reduce((n, list) => n + (Array.isArray(list) ? list.length : 0), 0)
        : 0),
    0,
  );
  return (
    <div className="analysis-preview">
      <div className="analysis-summary">
        <span
          className={`status-pill status-${String(result.status || "COMPLETED").toLowerCase()}`}
        >
          {labelStatus(result.status || "COMPLETED")}
        </span>
        <b>
          {result.successful_count ?? results.filter((r) => r.analysis).length}{" "}
          of {result.analysis_count ?? results.length} documents analysed
        </b>
        <small>
          {findingCount} extracted facts, discrepancies, missing information or
          risk flags. Findings require human verification.
        </small>
        <button className="btn btn-secondary btn-small" onClick={onOpen}>
          View Full Analysis <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}
function AnalysisResultsLegacy({ result, history }) {
  const results = result.results || result.result?.results || [];
  return (
    <>
      <details className="analysis-group">
        <summary>Analysis Summary</summary>
        <div className="analysis-summary">
          <span
            className={`status-pill status-${String(result.status || "COMPLETED").toLowerCase()}`}
          >
            {labelStatus(result.status || "COMPLETED")}
          </span>
          <b>
            {result.successful_count ??
              results.filter((r) => r.analysis).length}{" "}
            of {result.analysis_count ?? results.length} documents analysed
          </b>
          <small>
            Model findings require human verification. No automated lending
            decision is made.
          </small>
        </div>
        <CustomerPolicyReferences
          references={
            result.customer_policy_references ||
            result.result?.customer_policy_references ||
            []
          }
          retrievalStatus={
            result.policy_retrieval_status ||
            result.result?.policy_retrieval_status
          }
        />
      </details>
      <AnalysisList
        title="Cross-document numerical comparisons"
        items={(
          result.cross_document_checks ||
          result.result?.cross_document_checks ||
          []
        ).map(
          (check) =>
            `${check.label}: ${check.document_a_category} ${money(check.document_a_value)} vs ${check.document_b_category} ${money(check.document_b_value)}; difference ${check.difference_percent}% (tolerance ${check.tolerance_percent}%). ${check.within_configured_tolerance ? "Within tolerance" : "Outside tolerance"}. Confirm periods and original sources before drawing a conclusion.`,
        )}
      />
      {results.map((item, idx) => {
        const a = item.analysis || {};
        const summary = a.document_type_guess || "Not confidently identified";
        const validationItems =
          item.deterministic_checks || item.validation_errors || [];
        const findings = [
          ...(a.extracted_facts || []),
          ...(a.discrepancies || []),
          ...(a.missing_information || []),
          ...(a.risk_flags || []),
        ];
        return (
          <article
            className="analysis-document"
            key={`${item.document_id || idx}-${idx}`}
          >
            <div className="analysis-document-title">
              <div>
                <b>
                  {item.category_label ||
                    CATEGORIES.find((c) => c.value === item.category)?.label ||
                    item.category ||
                    `Document ${idx + 1}`}
                </b>
                <small>
                  {item.model
                    ? `Provider: ${item.provider} · Model: ${item.model}`
                    : "Analysis status"}
                </small>
              </div>
              <span
                className={`status-pill status-${item.error ? "failed" : "completed"}`}
              >
                {item.error ? "Failed" : "Findings available"}
              </span>
            </div>
            {item.error ? (
              <div className="inline-error">{item.error}</div>
            ) : (
              <>
                <details className="analysis-group">
                  <summary>Analysis Summary</summary>
                  <div className="analysis-block">
                    <p>{summary}</p>
                    <div className="analysis-confidence">
                      <span>Model confidence (only if returned):</span>
                      <b>{a.confidence || "Not provided"}</b>
                    </div>
                  </div>
                </details>
                <details className="analysis-group">
                  <summary>Findings</summary>
                  <AnalysisList
                    title="Extracted facts"
                    items={a.extracted_facts}
                  />
                  <AnalysisList
                    title="Potential discrepancies"
                    items={a.discrepancies}
                  />
                  <AnalysisList
                    title="Missing information"
                    items={a.missing_information}
                  />
                  <AnalysisList title="Risk flags" items={a.risk_flags} />
                  <AnalysisList
                    title="Evidence excerpts"
                    items={(a.evidence || []).map((e) =>
                      typeof e === "string"
                        ? e
                        : `${e.source_reference?.page_number ? `Page ${e.source_reference.page_number} · ` : ""}${e.claim || "Claim"}: “${e.exact_quote || e.quote || "No exact quote supplied"}”${e.source_reference?.quote_verified_against_source ? ` (${e.source_reference.source_kind === "CUSTOMER_CORRECTED_TEXT" ? "customer-corrected text, not independently verified" : "original OCR source quote verified"})` : " (source quote not verified)"}`,
                    )}
                  />
                </details>
                <details className="analysis-group">
                  <summary>Validation</summary>
                  <AnalysisList
                    title="Backend numerical comparisons"
                    items={validationItems.map((check) =>
                      typeof check === "object"
                        ? `${check.label || check.message || "Validation"}: ${check.declared_value !== undefined ? `declared ${money(check.declared_value)} vs document ${money(check.document_value)}; difference ${check.difference_percent}% (configured tolerance ${check.tolerance_percent}%). ${check.within_configured_tolerance ? "Within tolerance" : "Outside tolerance"}. Neither value is independently verified.` : JSON.stringify(check)}`
                        : check,
                    )}
                  />
                  {!validationItems.length && (
                    <p className="muted-copy">
                      No additional validation details were returned for this
                      document.
                    </p>
                  )}
                </details>
                <details className="analysis-group">
                  <summary>Limitations</summary>
                  <AnalysisList
                    title="Limitations / uncertainty"
                    items={a.limitations}
                  />
                  {(!a.limitations || !a.limitations.length) && (
                    <p className="muted-copy">
                      No limitations were provided by the analysis.
                    </p>
                  )}
                </details>
              </>
            )}
          </article>
        );
      })}
      {history?.length > 1 && (
        <details className="analysis-history">
          <summary>Previous analysis runs ({history.length - 1})</summary>
          {history.slice(1).map((row) => (
            <p key={row.id || row.created_at}>
              <b>{labelStatus(row.status)}</b> ·{" "}
              {new Date(row.created_at).toLocaleString("en-IN")}{" "}
              {row.error_message && `— ${row.error_message}`}
            </p>
          ))}
        </details>
      )}
    </>
  );
}
const CUSTOMER_ANALYSIS_SECTIONS = [
  ["property", "Property Details & Valuation"],
  ["income", "Income & Tax Findings"],
  ["terms", "Mortgage Terms & Conditions"],
  ["missing", "Missing Information"],
  ["conflicts", "Conflicting Evidence / Discrepancies"],
  ["risks", "Risk Flags & Observations"],
  ["evidence", "Source Documents & Evidence"],
  ["other", "Other Findings"],
];
const CUSTOMER_ANALYSIS_FIELDS = new Set([
  "scenario",
  "document_type_guess",
  "extracted_facts",
  "discrepancies",
  "missing_information",
  "risk_flags",
  "evidence",
  "confidence",
  "limitations",
]);

function customerAnalysisSection(item) {
  const text = (
    typeof item === "string" ? item : JSON.stringify(item ?? "")
  ).toLowerCase();
  if (
    /\b(property|valuation|valuer|market value|purchase price|ltv|loan.to.value|title deed|plot|flat|apartment)\b/.test(
      text,
    )
  )
    return "property";
  if (
    /\b(income|salary|salaried|employer|itr|tax|taxable|bank credits|form 16|gross pay|net pay)\b/.test(
      text,
    )
  )
    return "income";
  if (
    /\b(interest rate|floating|fixed rate|tenure|emi|instalment|installment|prepayment|foreclosure|processing fee|loan agreement|mortgage terms|default clause)\b/.test(
      text,
    )
  )
    return "terms";
  return "other";
}

function CustomerAnalysisList({ items }) {
  if (!Array.isArray(items) || !items.length) return null;
  return (
    <ul>
      {items.map((item, index) => {
        const text =
          typeof item === "string"
            ? item
            : !item || typeof item !== "object"
              ? String(item ?? "")
              : item.description ||
                item.finding ||
                item.claim ||
                item.summary ||
                item.message ||
                JSON.stringify(item);
        return (
          <li key={index}>
            {text}
            {item && typeof item === "object" && (
              <details>
                <summary>View all returned fields</summary>
                <pre>{JSON.stringify(item, null, 2)}</pre>
              </details>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function AnalysisResults({ result = {}, history = [] } = {}) {
  const nested = result?.result;
  const results = (
    Array.isArray(result?.results)
      ? result.results
      : Array.isArray(nested?.results)
        ? nested.results
        : []
  ).filter((item) => item && typeof item === "object");
  const crossChecks = (
    Array.isArray(result?.cross_document_checks)
      ? result.cross_document_checks
      : Array.isArray(nested?.cross_document_checks)
        ? nested.cross_document_checks
        : []
  ).filter((item) => item && typeof item === "object");
  const policyReferences = (
    Array.isArray(result?.customer_policy_references)
      ? result.customer_policy_references
      : Array.isArray(nested?.customer_policy_references)
        ? nested.customer_policy_references
        : []
  ).filter((item) => item && typeof item === "object");
  const policyStatus =
    result?.policy_retrieval_status || nested?.policy_retrieval_status;
  return (
    <>
      <details className="analysis-group">
        <summary>Analysis Summary</summary>
        <div className="analysis-summary">
          <span
            className={`status-pill status-${String(result.status || "COMPLETED").toLowerCase()}`}
          >
            {labelStatus(result.status || "COMPLETED")}
          </span>
          <b>
            {result.successful_count ??
              results.filter((row) => row.analysis).length}{" "}
            of {result.analysis_count ?? results.length} documents analysed
          </b>
          <small>
            Model findings require human verification. No automated lending
            decision is made.
          </small>
        </div>
        <CustomerPolicyReferences
          references={policyReferences}
          retrievalStatus={policyStatus}
        />
      </details>
      {crossChecks.length > 0 && (
        <details className="analysis-group">
          <summary>Conflicting Evidence / Discrepancies</summary>
          <div className="analysis-block">
            <ul>
              {crossChecks.map((check, index) => (
                <li
                  key={index}
                >{`${check.label}: ${check.document_a_category} ${money(check.document_a_value)} vs ${check.document_b_category} ${money(check.document_b_value)}; difference ${check.difference_percent}% (tolerance ${check.tolerance_percent}%). ${check.within_configured_tolerance ? "Within tolerance" : "Outside tolerance"}. Confirm periods and original sources before drawing a conclusion.`}</li>
              ))}
            </ul>
          </div>
        </details>
      )}
      {results.map((item, index) => {
        const analysis = item.analysis || {};
        const sections = Object.fromEntries(
          CUSTOMER_ANALYSIS_SECTIONS.map(([key]) => [key, []]),
        );
        (Array.isArray(analysis.extracted_facts)
          ? analysis.extracted_facts
          : []
        ).forEach((finding) =>
          sections[customerAnalysisSection(finding)].push(finding),
        );
        (Array.isArray(analysis.missing_information)
          ? analysis.missing_information
          : []
        ).forEach((finding) => sections.missing.push(finding));
        (Array.isArray(analysis.discrepancies)
          ? analysis.discrepancies
          : []
        ).forEach((finding) => sections.conflicts.push(finding));
        (Array.isArray(analysis.risk_flags) ? analysis.risk_flags : []).forEach(
          (finding) => sections.risks.push(finding),
        );
        (Array.isArray(analysis.evidence) ? analysis.evidence : []).forEach(
          (evidence) => sections.evidence.push(evidence),
        );
        (Array.isArray(analysis.limitations)
          ? analysis.limitations
          : []
        ).forEach((limitation) => sections.other.push(limitation));
        Object.entries(analysis)
          .filter(([key]) => !CUSTOMER_ANALYSIS_FIELDS.has(key))
          .forEach(([key, value]) => sections.other.push({ [key]: value }));
        const validation = Array.isArray(item.deterministic_checks)
          ? item.deterministic_checks
          : Array.isArray(item.validation_errors)
            ? item.validation_errors
            : [];
        validation.forEach((check) =>
          sections.other.push(
            typeof check === "object"
              ? `${check.label || check.message || "Validation"}: ${check.declared_value !== undefined ? `declared ${money(check.declared_value)} vs document ${money(check.document_value)}; difference ${check.difference_percent}% (configured tolerance ${check.tolerance_percent}%). ${check.within_configured_tolerance ? "Within tolerance" : "Outside tolerance"}. Neither value is independently verified.` : JSON.stringify(check)}`
              : check,
          ),
        );
        const summary = [
          analysis.scenario,
          analysis.document_type_guess,
        ].filter(Boolean);
        const hasMetadata =
          item.provider || item.model || item.analysis_completed_at;
        return (
          <article
            className="analysis-document"
            key={`${item.document_id || index}-${index}`}
          >
            <div className="analysis-document-title">
              <div>
                <b>
                  {item.category_label ||
                    CATEGORIES.find(
                      (category) => category.value === item.category,
                    )?.label ||
                    item.category ||
                    `Document ${index + 1}`}
                </b>
                <small>
                  {item.model
                    ? `Provider: ${item.provider} · Model: ${item.model}`
                    : "Analysis status"}
                </small>
              </div>
              <span
                className={`status-pill status-${item.error ? "failed" : "completed"}`}
              >
                {item.error ? "Failed" : "Findings available"}
              </span>
            </div>
            {item.error ? (
              <div className="inline-error">{item.error}</div>
            ) : (
              <>
                {(summary.length > 0 || analysis.confidence != null) && (
                  <details className="analysis-group">
                    <summary>Analysis Summary</summary>
                    <div className="analysis-block">
                      {summary.map((value, summaryIndex) => (
                        <p key={summaryIndex}>{value}</p>
                      ))}
                      {analysis.confidence != null && (
                        <div className="analysis-confidence">
                          <span>Model confidence (only if returned):</span>
                          <b>{analysis.confidence}</b>
                        </div>
                      )}
                    </div>
                  </details>
                )}
                {CUSTOMER_ANALYSIS_SECTIONS.map(
                  ([key, title]) =>
                    sections[key].length > 0 && (
                      <details className="analysis-group" key={key}>
                        <summary>{title}</summary>
                        <div className="analysis-block">
                          <CustomerAnalysisList items={sections[key]} />
                        </div>
                      </details>
                    ),
                )}
                {hasMetadata && (
                  <details className="analysis-group">
                    <summary>Analysis Metadata</summary>
                    <div className="analysis-block">
                      <CustomerAnalysisList
                        items={[
                          {
                            provider: item.provider,
                            model: item.model,
                            completed_at: item.analysis_completed_at,
                            status: item.analysis_status,
                          },
                        ]}
                      />
                    </div>
                  </details>
                )}
              </>
            )}
          </article>
        );
      })}
      {Array.isArray(history) && history.length > 1 && (
        <details className="analysis-history">
          <summary>Previous analysis runs ({history.length - 1})</summary>
          {history.slice(1).map((row) => (
            <p key={row.id || row.created_at}>
              <b>{labelStatus(row.status)}</b> ·{" "}
              {new Date(row.created_at).toLocaleString("en-IN")}{" "}
              {row.error_message && `— ${row.error_message}`}
            </p>
          ))}
        </details>
      )}
    </>
  );
}

function CustomerPolicyReferences({ references, retrievalStatus }) {
  return (
    <section className="customer-policy-reference">
      <div className="extracted-heading">
        <b>Customer-visible policy guidance</b>
        <small>
          Only active policy summaries explicitly marked safe for customer
          display are shown. Internal policy content is not exposed.
        </small>
      </div>
      {references.length ? (
        references.map((ref, i) => (
          <article
            className="policy-reference-item"
            key={`${ref.policy_id}-${ref.chunk_index}-${i}`}
          >
            <div>
              <b>{ref.title}</b>
              <span>
                {ref.category} · Version {ref.version}
              </span>
            </div>
            <p>{ref.summary_excerpt}</p>
            <small>
              Source policy #{ref.policy_id} · Retrieval:{" "}
              {ref.retrieval_method || "policy search"}
            </small>
          </article>
        ))
      ) : (
        <p className="muted-copy">
          {retrievalStatus === "FAILED"
            ? "Customer-visible policy retrieval could not be completed. No policy conclusion was generated."
            : "No relevant customer-visible policy summary was retrieved. This does not mean that the bank has no internal policy; confidential policy content is not shown here."}
        </p>
      )}
    </section>
  );
}
function AnalysisList({ title, items }) {
  if (!Array.isArray(items) || !items.length) return null;
  const readable = (item) => {
    if (typeof item === "string") return item;
    if (!item || typeof item !== "object") return String(item ?? "");
    const preferred =
      item.description || item.finding || item.claim || item.summary;
    if (preferred) return String(preferred);
    return Object.entries(item)
      .map(
        ([key, value]) =>
          `${key.replaceAll("_", " ")}: ${Array.isArray(value) ? value.join(", ") : typeof value === "object" ? "details available" : String(value)}`,
      )
      .join(" · ");
  };
  return (
    <div className="analysis-block">
      <h4>{title}</h4>
      <ul>
        {items.map((item, i) => (
          <li key={i}>{readable(item)}</li>
        ))}
      </ul>
    </div>
  );
}
function ActivityList({ applicationId }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api(`/applications/${applicationId}/activity`)
      .then((r) => {
        if (active) setItems(r);
      })
      .catch(() => {
        if (active) notifyError();
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [applicationId]);
  if (loading) return <p className="muted-copy">Loading activity…</p>;
  if (error) return <p className="inline-error">{error}</p>;
  if (!items.length)
    return (
      <EmptyState
        title="No activity recorded yet"
        description="Application events will appear here when actions are persisted by the backend."
      />
    );
  return (
    <div className="timeline">
      {items.map((item) => (
        <div className="timeline-item" key={item.id}>
          <span className="timeline-dot">
            <Activity size={13} />
          </span>
          <div>
            <b>{item.message}</b>
            <small>{new Date(item.created_at).toLocaleString("en-IN")}</small>
          </div>
        </div>
      ))}
    </div>
  );
}
