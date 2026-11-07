import "./admin.css";
import { useEffect, useState } from "react";
import { api } from "./api";
import {
  Activity,
  ShieldCheck,
  Users,
  ClipboardList,
  Settings,
  FileText,
  History,
  LogOut,
  RefreshCw,
  Plus,
  CheckCircle2,
  AlertTriangle,
  Building2,
  Trash2,
  Search,
  Clock3,
  UserCheck,
  UserX,
  Landmark,
  Eye,
  EyeOff,
} from "lucide-react";
import { money } from "./utils/format";
import { notifyError, notifySuccess } from "./ToastProvider";
const API = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1"
).replace(/\/$/, "");
async function adminApi(path, opts = {}) {
  const h = new Headers(opts.headers || {});
  const t = localStorage.getItem("mortgage_admin_token");
  if (t) h.set("Authorization", `Bearer ${t}`);
  if (opts.body && !(opts.body instanceof FormData))
    h.set("Content-Type", "application/json");
  const r = await fetch(`${API}${path}`, { ...opts, headers: h });
  const ct = r.headers.get("content-type") || "";
  const b = ct.includes("application/json") ? await r.json() : await r.text();
  if (!r.ok) throw Error(b?.detail || `Request failed (${r.status})`);
  return b;
}
async function downloadAdminCsv(path) {
  const h = new Headers({
    Authorization: `Bearer ${localStorage.getItem("mortgage_admin_token") || ""}`,
  });
  const r = await fetch(`${API}${path}`, { headers: h });
  if (!r.ok) throw Error("Export failed.");
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = path.includes("audit")
    ? "security-audit.csv"
    : "platform-report.csv";
  a.click();
  URL.revokeObjectURL(url);
}
export default function AdminPortal() {
  const [admin, setAdmin] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("mortgage_admin") || "null");
    } catch {
      return null;
    }
  });
  const [login, setLogin] = useState({ email: "" });
  const [tab, setTab] = useState("dashboard");
  const [dash, setDash] = useState(null);
  const [apps, setApps] = useState([]);
  const [reviewers, setReviewers] = useState([]);
  const [policies, setPolicies] = useState([]);
  const [logs, setLogs] = useState([]);
  const [config, setConfig] = useState(null);
  const [verify, setVerify] = useState(null);
  const [ops, setOps] = useState({});
  const [customerQuery, setCustomerQuery] = useState("");
  const [customerPage, setCustomerPage] = useState(0);
  const [customerFilters, setCustomerFilters] = useState({
    status: "all",
    verified: "all",
    start: "",
    end: "",
    sort: "newest",
    limit: 25,
  });
  const [adminQuery, setAdminQuery] = useState("");
  const [adminStatus, setAdminStatus] = useState("all");
  const [showAdminInvite, setShowAdminInvite] = useState(false);
  const [noticeFilter, setNoticeFilter] = useState("all");
  const [noticeSeverity, setNoticeSeverity] = useState("all");
  const [noticeRead, setNoticeRead] = useState("all");
  const [noticeQuery, setNoticeQuery] = useState("");
  const [noticeDates, setNoticeDates] = useState({ start: "", end: "" });
  const [noticeOffset, setNoticeOffset] = useState(0);
  const [monitoringHours, setMonitoringHours] = useState(24);
  const [auditOffset, setAuditOffset] = useState(0);
  const [reportPeriod, setReportPeriod] = useState({ start: "", end: "" });
  const [appliedReportPeriod, setAppliedReportPeriod] = useState({
    start: "",
    end: "",
  });
  const [reportDateError, setReportDateError] = useState("");
  const [auditFilters, setAuditFilters] = useState({
    actor: "",
    action: "",
    resource_type: "",
    outcome: "",
    severity: "",
    category: "",
    start: "",
    end: "",
  });
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [newReviewer, setNewReviewer] = useState({
    full_name: "",
    email: "",
    password: "",
    bank_code: "BANK-DEMO",
  });
  const [showTemporaryPassword, setShowTemporaryPassword] = useState(false);
  const [assignment, setAssignment] = useState({
    application_id: "",
    reviewer_id: "",
  });
  const [policy, setPolicy] = useState({
    title: "",
    policy_version: "1.0",
    category: "Mortgage",
    content: "",
    active: true,
    bank_id: "",
  });
  const [banks, setBanks] = useState([]);
  const EMPTY_BANK_FORM = {
    name: "",
    institution_type: "",
    contact_email: "",
    contact_phone: "",
    address: "",
    ifsc_code: "",
    license_number: "",
  };
  const [bankForm, setBankForm] = useState(EMPTY_BANK_FORM);
  const [bankFormErrors, setBankFormErrors] = useState({});
  const [inviteForm, setInviteForm] = useState({
    bank_id: "",
    full_name: "",
    email: "",
  });
  const [inviteResult, setInviteResult] = useState(null);
  const [bankDetail, setBankDetail] = useState(null);
  const [rejectReason, setRejectReason] = useState("");
  const [pending, setPending] = useState(null);
  const [otp, setOtp] = useState("");
  function updateBankField(field, value) {
    setBankForm((current) => ({ ...current, [field]: value }));
    setBankFormErrors((current) => ({ ...current, [field]: "" }));
  }
  function validateBankForm(values = bankForm) {
    const errors = {};
    const name = values.name.trim();
    const email = values.contact_email.trim();
    const phone = values.contact_phone.trim();
    const address = values.address.trim();
    const ifsc = values.ifsc_code.trim().toUpperCase();
    if (name.length < 3)
      errors.name = "Enter the institution name (at least 3 characters).";
    else if (name.length > 180)
      errors.name = "Institution name must be 180 characters or fewer.";
    if (
      ![
        "Public Sector Bank",
        "Private Sector Bank",
        "Cooperative Bank",
        "NBFC",
        "Other",
      ].includes(values.institution_type)
    )
      errors.institution_type = "Select a supported institution type.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))
      errors.contact_email = "Enter a valid official email address.";
    if (
      !/^(?:\+91[\s-]?)?(?:[6-9]\d{9}|0\d{2,4}[\s-]?\d{6,8}|[2-9]\d{1,3}[\s-]?\d{6,8})$/.test(
        phone,
      )
    )
      errors.contact_phone =
        "Enter a valid Indian mobile or official landline number.";
    if (address.length < 10)
      errors.address = "Enter the complete registered office address.";
    else if (address.length > 1000)
      errors.address = "Address must be 1,000 characters or fewer.";
    if (ifsc && !/^[A-Z]{4}0[A-Z0-9]{6}$/.test(ifsc))
      errors.ifsc_code = "Enter a valid 11-character IFSC code.";
    if (
      values.institution_type !== "Other" &&
      values.license_number.trim().length < 4
    )
      errors.license_number =
        "A registration or license number is required for this institution type.";
    else if (values.license_number.trim().length > 80)
      errors.license_number =
        "Registration or license number must be 80 characters or fewer.";
    setBankFormErrors(errors);
    return Object.keys(errors).length === 0;
  }
  function registerBank(e) {
    e.preventDefault();
    const values = {
      ...bankForm,
      name: bankForm.name.trim(),
      contact_email: bankForm.contact_email.trim().toLowerCase(),
      contact_phone: bankForm.contact_phone.trim(),
      address: bankForm.address.trim(),
      ifsc_code: bankForm.ifsc_code.trim().toUpperCase(),
      license_number: bankForm.license_number.trim(),
    };
    if (!validateBankForm(values)) return;
    setBankForm(values);
    run(async () => {
      await adminApi("/admin/banks", {
        method: "POST",
        body: JSON.stringify(values),
      });
      setBankForm(EMPTY_BANK_FORM);
      setBankFormErrors({});
    }, "Bank registered pending approval.");
  }
  async function load() {
    setBusy(true);
    setErr("");
    try {
      if (tab === "dashboard") setDash(await adminApi("/admin/dashboard"));
      if (tab === "audit") {
        const params = new URLSearchParams({
          limit: "50",
          offset: String(auditOffset),
          ...auditFilters,
        });
        Object.keys(auditFilters).forEach((k) => {
          if (!auditFilters[k]) params.delete(k);
        });
        const p = await adminApi(`/admin/audit-logs?${params}`);
        setOps((v) => ({ ...v, auditTotal: p.total || 0 }));
        setLogs(p.items || []);
      }
      if (tab === "configuration" || tab === "settings")
        setConfig(await adminApi("/admin/configuration"));
      if (tab === "users") {
        const params = new URLSearchParams({
          q: customerQuery,
          status: customerFilters.status,
          verified: customerFilters.verified,
          sort: customerFilters.sort,
          limit: String(customerFilters.limit),
          offset: String(customerPage * customerFilters.limit),
        });
        if (customerFilters.start) params.set("start", customerFilters.start);
        if (customerFilters.end) params.set("end", customerFilters.end);
        const data = await adminApi(`/admin/customers?${params}`);
        setOps((v) => ({ ...v, customers: data }));
      }
      if (tab === "banks") setBanks(await adminApi("/admin/banks"));
      if (tab === "bankadmins") {
        setBanks(await adminApi("/admin/banks"));
        const data = await adminApi(
          `/admin/bank-admins?q=${encodeURIComponent(adminQuery)}&status=${adminStatus}`,
        );
        setOps((v) => ({ ...v, bankadmins: data }));
      }
      if (tab === "monitoring") {
        const data = await adminApi(
          `/admin/monitoring?hours=${monitoringHours}`,
        );
        setOps((v) => ({ ...v, monitoring: data }));
      }
      if (tab === "notifications") {
        const params = new URLSearchParams({
          category: noticeFilter,
          severity: noticeSeverity,
          read_status: noticeRead,
          q: noticeQuery,
          limit: "25",
          offset: String(noticeOffset),
        });
        if (noticeDates.start) params.set("start", noticeDates.start);
        if (noticeDates.end) params.set("end", noticeDates.end);
        const data = await adminApi(`/admin/notifications?${params}`);
        setOps((v) => ({ ...v, notifications: data }));
      }
      if (tab === "reports") {
        const params = new URLSearchParams();
        if (appliedReportPeriod.start)
          params.set("start", appliedReportPeriod.start);
        if (appliedReportPeriod.end) params.set("end", appliedReportPeriod.end);
        const data = await adminApi(`/admin/reports?${params}`);
        setOps((v) => ({ ...v, reports: data }));
      }
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (admin && localStorage.getItem("mortgage_admin_token")) load();
  }, [
    admin,
    tab,
    customerQuery,
    customerPage,
    customerFilters,
    adminQuery,
    adminStatus,
    noticeFilter,
    noticeSeverity,
    noticeRead,
    noticeQuery,
    noticeDates,
    noticeOffset,
    monitoringHours,
    auditFilters,
    auditOffset,
    appliedReportPeriod,
  ]);
  function finishSignIn(r) {
    localStorage.setItem("mortgage_admin_token", r.access_token);
    localStorage.setItem("mortgage_admin", JSON.stringify(r.admin));
    setAdmin(r.admin);
    setPending(null);
    setOtp("");
    setLogin({ email: "" });
    notifySuccess("Signed in successfully.");
  }
  async function signIn(e) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const r = await adminApi("/admin/login", {
        method: "POST",
        body: JSON.stringify({ email: login.email.trim() }),
      });
      setPending(r);
    } catch (error) {
      notifyError(error instanceof Error ? error.message : undefined);
    } finally {
      setBusy(false);
    }
  }
  async function verifyOtp(e) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      finishSignIn(
        await adminApi("/admin/login/verify-otp", {
          method: "POST",
          body: JSON.stringify({ email: pending.email, code: otp.trim() }),
        }),
      );
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }
  function signOut() {
    localStorage.removeItem("mortgage_admin_token");
    localStorage.removeItem("mortgage_admin");
    setAdmin(null);
  }
  async function run(fn, success) {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await fn();
      notifySuccess(success);
      await load();
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }
  if (!admin)
    return (
      <div className="auth">
        <div className="auth-side">
          <div className="brand">
            <span className="mark">M</span>
            <div>
              <b>Mortgage AI</b>
              <small>Platform administration</small>
            </div>
          </div>
          <div className="hero">
            <small>CONTROL PLANE</small>
            <h1>
              Governance.
              <br />
              Visibility.
              <br />
              Accountability.
            </h1>
            <p>
              Manage reviewer access, assignments, policy versions and audit
              activity.
            </p>
            <div className="hero-point">
              <ShieldCheck /> Restricted admin access
            </div>
          </div>
          <small className="side-foot">TCS Mortgage AI - Admin portal</small>
        </div>
        {pending ? (
          <form className="auth-form" onSubmit={verifyOtp}>
            <small className="eyebrow">PLATFORM ADMIN - STEP 2 OF 2</small>
            <h2>Enter verification code</h2>
            <p className="sub">
              A 6-digit code was emailed to <b>{pending.email}</b>. It expires
              in {pending.expires_in_minutes} minutes and works once.
            </p>
            {err && <div className="alert error">{err}</div>}
            <label className="field">
              <span>6-digit code</span>
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                required
                autoFocus
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
              />
            </label>
            <button
              className="primary wide"
              disabled={busy || otp.length !== 6}
            >
              {busy ? "Verifying..." : "Verify OTP"}
            </button>
            <button
              type="button"
              className="secondary wide"
              onClick={() => {
                setPending(null);
                setOtp("");
                setErr("");
              }}
            >
              Back to sign in
            </button>
          </form>
        ) : (
          <form className="auth-form" onSubmit={signIn}>
            <small className="eyebrow">PLATFORM ADMIN</small>
            <h2>Administrator sign in</h2>
            <p className="sub">
              Enter the email configured for Platform Admin access.
            </p>
            {err && <div className="alert error">{err}</div>}
            <label className="field">
              <span>Email address</span>
              <input
                type="email"
                required
                autoComplete="username"
                placeholder="Platform Admin email"
                value={login.email}
                onChange={(e) => setLogin({ email: e.target.value })}
              />
            </label>
            <button className="primary wide" disabled={busy}>
              {busy ? "Sending..." : "Send OTP"}
            </button>
          </form>
        )}
      </div>
    );
  const nav = [
    ["dashboard", "Dashboard", Activity],
    ["banks", "Banks & Registrations", Building2],
    ["bankadmins", "Bank Admin Management", Users],
    ["users", "Customer Management", Users],
    ["monitoring", "System Monitoring", Activity],
    ["notifications", "Notifications & Alerts", AlertTriangle],
    ["audit", "Security & Audit Logs", History],
    ["reports", "Reports & Exports", ClipboardList],
    ["settings", "Platform Settings", Settings],
  ];
  return (
    <div className="layout admin-layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="mark">M</span>
          <div>
            <b>Mortgage AI</b>
            <small>Admin control plane</small>
          </div>
        </div>
        <small className="nav-label">GOVERNANCE</small>
        {nav.map(([k, label, Icon]) => (
          <button
            key={k}
            className={`nav ${tab === k ? "active" : ""}`}
            onClick={() => setTab(k)}
          >
            <Icon />
            {label}
          </button>
        ))}
        <div className="side-bottom">
          <div className="secure">
            <ShieldCheck size={16} />
            Privileged access
          </div>
          <button className="nav" onClick={signOut}>
            <LogOut />
            Sign out
          </button>
        </div>
      </aside>
      <main>
        <header>
          <div className="breadcrumb">
            Platform administration <span>/</span>{" "}
            {nav.find((x) => x[0] === tab)?.[1]}
          </div>
          <div className="profile">
            <span className="avatar">{admin.full_name?.[0] || "A"}</span>
            <div>
              <b>{admin.full_name}</b>
              <small>Platform Admin</small>
            </div>
          </div>
        </header>
        <section className="content">
          <div className="heading">
            <div>
              <small className="eyebrow">ADMINISTRATION</small>
              <h1>
                {tab === "dashboard"
                  ? "Platform Overview"
                  : nav.find((x) => x[0] === tab)?.[1]}
              </h1>
              <p>
                {tab === "dashboard"
                  ? "Monitor bank onboarding, customers, applications, and platform operations."
                  : "Controlled configuration and operational visibility for the mortgage workflow."}
              </p>
            </div>
            <button className="secondary" onClick={load} disabled={busy}>
              <RefreshCw size={16} /> Refresh
            </button>
          </div>
          {tab === "dashboard" && (
            <>
              {!dash ? (
                <div className="panel">
                  {busy ? "Loading dashboard?" : "No dashboard data loaded."}
                </div>
              ) : (
                <div className="admin-dashboard">
                  <div className="dashboard-refresh">
                    Latest data refresh:{" "}
                    {dash.generated_at
                      ? new Date(dash.generated_at).toLocaleString()
                      : "Unavailable"}
                  </div>
                  <div className="stats">
                    <Stat
                      title="Total banks"
                      value={dash.banks}
                      icon={Landmark}
                    />
                    <Stat
                      title="Pending registrations"
                      value={dash.pending_banks}
                      icon={Clock3}
                    />
                    <Stat
                      title="Approved banks"
                      value={dash.approved_banks}
                      icon={CheckCircle2}
                    />
                    <Stat
                      title="Total customers"
                      value={dash.customers}
                      icon={Users}
                    />
                    <Stat
                      title="Active customers"
                      value={dash.active_customers}
                      icon={UserCheck}
                    />
                    <Stat
                      title="Suspended customers"
                      value={dash.suspended_customers}
                      icon={UserX}
                    />
                    <Stat
                      title="Mortgage applications"
                      value={dash.applications}
                      icon={FileText}
                    />
                    <Stat
                      title="Critical alerts"
                      value={dash.critical_alerts}
                      icon={AlertTriangle}
                    />
                  </div>
                  <div className="dashboard-grid">
                    <section className="panel status-panel">
                      <div className="dashboard-section-title">
                        <div>
                          <h2>Application status</h2>
                          <p>
                            Distribution from persisted mortgage application
                            records.
                          </p>
                        </div>
                        <b>{dash.applications || 0} total</b>
                      </div>
                      {dash.applications ? (
                        <>
                          <div
                            className="status-segments"
                            role="img"
                            aria-label="Application status distribution"
                          >
                            {Object.entries(dash.statuses || {})
                              .filter(([, n]) => n > 0)
                              .map(([s, n]) => (
                                <i
                                  key={s}
                                  className={"segment-" + s.toLowerCase()}
                                  style={{
                                    width: `${(n / dash.applications) * 100}%`,
                                  }}
                                  title={`${s.replaceAll("_", " ")}: ${n}`}
                                />
                              ))}
                          </div>
                          <div className="status-grid">
                            {Object.entries(dash.statuses || {}).map(
                              ([s, n]) => (
                                <div className="status-item" key={s}>
                                  <span>{s.replaceAll("_", " ")}</span>
                                  <b>{n}</b>
                                  <small>
                                    {((n / dash.applications) * 100).toFixed(1)}
                                    %
                                  </small>
                                </div>
                              ),
                            )}
                          </div>
                        </>
                      ) : (
                        <p className="empty-state">
                          No mortgage applications have been recorded.
                        </p>
                      )}
                    </section>
                    <section className="panel">
                      <div className="dashboard-section-title">
                        <h2>Recent bank registrations</h2>
                        <button
                          className="text-action"
                          onClick={() => setTab("banks")}
                        >
                          View all registrations
                        </button>
                      </div>
                      {dash.recent_banks?.length ? (
                        <div className="dashboard-list">
                          {dash.recent_banks.map((b) => (
                            <div className="dashboard-row" key={b.id}>
                              <div>
                                <b>{b.name}</b>
                                <small>
                                  {new Date(b.created_at).toLocaleDateString()}
                                </small>
                              </div>
                              <span
                                className={`admin-status-badge status-${String(b.status).toLowerCase()}`}
                              >
                                {b.status}
                              </span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="empty-state">
                          No bank registrations yet.
                        </p>
                      )}
                    </section>
                    <section className="panel">
                      <div className="dashboard-section-title">
                        <h2>Recent administrative activity</h2>
                        <button
                          className="text-action"
                          onClick={() => setTab("audit")}
                        >
                          Security &amp; Audit Logs
                        </button>
                      </div>
                      {dash.recent_actions?.length ? (
                        <div className="dashboard-list">
                          {dash.recent_actions.map((x) => (
                            <div className="activity-row" key={x.id}>
                              <div>
                                <b>{x.action_label || x.action}</b>
                                <small>
                                  {x.actor_role || "System"} ?{" "}
                                  {new Date(x.created_at).toLocaleString()} ?{" "}
                                  {x.outcome}
                                </small>
                                <details>
                                  <summary>Event details</summary>
                                  <code>{x.action}</code>
                                  <span>
                                    {x.resource_type} #{x.resource_id}
                                  </span>
                                  {x.detail && <p>{x.detail}</p>}
                                </details>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="empty-state">
                          No administrative activity recorded.
                        </p>
                      )}
                    </section>
                    <section className="panel ai-summary">
                      <div className="dashboard-section-title">
                        <h2>AI service summary</h2>
                        <button
                          className="text-action"
                          onClick={() => setTab("monitoring")}
                        >
                          System Monitoring
                        </button>
                      </div>
                      <div className="ai-facts">
                        <div>
                          <small>Provider</small>
                          <b>{dash.ai?.provider || "Unavailable"}</b>
                        </div>
                        <div>
                          <small>Nemotron model</small>
                          <b>{dash.ai?.model || "Unavailable"}</b>
                        </div>
                        <div>
                          <small>Configuration</small>
                          <b>
                            {dash.ai?.configured
                              ? "Configured"
                              : "Not Configured"}
                          </b>
                        </div>
                        <div>
                          <small>Verification</small>
                          <b>{dash.ai?.status || "Not Verified"}</b>
                        </div>
                      </div>
                      {dash.ai?.last_verified && (
                        <small>
                          Last verification:{" "}
                          {new Date(dash.ai.last_verified).toLocaleString()}
                        </small>
                      )}
                      <div className="ai-run-summary">
                        Recorded analysis runs: {dash.analysis?.total || 0} ?
                        Successful: {dash.analysis?.succeeded || 0} ? Failed:{" "}
                        {dash.analysis?.failed || 0}
                      </div>
                    </section>
                  </div>
                </div>
              )}
            </>
          )}
          {tab === "applications" && (
            <section className="panel">
              <div className="section-head">
                <div>
                  <h2>Application monitoring</h2>
                  <p>
                    Reviewer assignment is handled automatically by the backend
                    using bank scope, reviewer eligibility, specialisation and
                    workload capacity. Platform Admin cannot manually assign
                    cases.
                  </p>
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>REFERENCE</th>
                      <th>CUSTOMER</th>
                      <th>LOAN AMOUNT</th>
                      <th>STATUS</th>
                      <th>AUTO-ASSIGNED REVIEWER</th>
                    </tr>
                  </thead>
                  <tbody>
                    {apps.map((a) => (
                      <tr key={a.id}>
                        <td>
                          <b>{a.reference}</b>
                        </td>
                        <td>
                          {a.customer_name}
                          <small>{a.customer_email}</small>
                        </td>
                        <td>{money(a.requested_loan)}</td>
                        <td>
                          <span className="badge">{a.status}</span>
                        </td>
                        <td>
                          {a.reviewer_email || "Pending automatic assignment"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {tab === "reviewers" && (
            <>
              <section className="panel">
                <h2>Create reviewer account</h2>
                <p>
                  Use a unique email and a strong temporary password;
                  communicate it securely.
                </p>
                <form
                  className="fields"
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      await adminApi("/admin/reviewers", {
                        method: "POST",
                        body: JSON.stringify(newReviewer),
                      });
                      setNewReviewer({
                        full_name: "",
                        email: "",
                        password: "",
                        bank_code: "BANK-DEMO",
                      });
                      setShowTemporaryPassword(false);
                    }, "Reviewer created.");
                  }}
                >
                  <Field
                    label="Full name"
                    value={newReviewer.full_name}
                    set={(v) =>
                      setNewReviewer({ ...newReviewer, full_name: v })
                    }
                    required
                  />
                  <Field
                    label="Email"
                    type="email"
                    value={newReviewer.email}
                    set={(v) => setNewReviewer({ ...newReviewer, email: v })}
                    required
                  />
                  <Field
                    label="Temporary password (8+ chars)"
                    type="password"
                    visible={showTemporaryPassword}
                    onToggleVisibility={() =>
                      setShowTemporaryPassword((v) => !v)
                    }
                    value={newReviewer.password}
                    set={(v) => setNewReviewer({ ...newReviewer, password: v })}
                    required
                  />
                  <Field
                    label="Bank code"
                    value={newReviewer.bank_code}
                    set={(v) =>
                      setNewReviewer({ ...newReviewer, bank_code: v })
                    }
                    required
                  />
                  <button className="primary" disabled={busy}>
                    Create reviewer
                  </button>
                </form>
              </section>
              <section className="panel">
                <h2>Reviewer directory</h2>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>NAME</th>
                        <th>EMAIL</th>
                        <th>BANK</th>
                        <th>ACTIVE ASSIGNMENTS</th>
                        <th>STATUS / ACTION</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reviewers.map((r) => (
                        <tr key={r.id}>
                          <td>{r.full_name}</td>
                          <td>{r.email}</td>
                          <td>{r.bank_code}</td>
                          <td>{r.assigned_count}</td>
                          <td>
                            <button
                              className="secondary small"
                              onClick={() =>
                                run(
                                  () =>
                                    adminApi(
                                      `/admin/reviewers/${r.id}/active?active=${!r.is_active}`,
                                      { method: "PATCH" },
                                    ),
                                  r.is_active
                                    ? "Reviewer suspended."
                                    : "Reviewer activated.",
                                )
                              }
                            >
                              {r.is_active ? "Suspend" : "Activate"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
          {tab === "banks" && (
            <div className="bank-management">
              <section className="panel bank-panel">
                <div className="bank-section-heading">
                  <div>
                    <h2>Register institution</h2>
                    <p>
                      New entries remain pending until approved. Bank Admin
                      access is available only after approval.
                    </p>
                  </div>
                  <span className="bank-required-note">
                    <b>*</b> Required
                  </span>
                </div>
                <form
                  className="bank-registration-form"
                  onSubmit={registerBank}
                  noValidate
                >
                  <label className="field">
                    <span>
                      Bank / Financial Institution Name{" "}
                      <b className="required-mark">*</b>
                    </span>
                    <input
                      required
                      maxLength={180}
                      placeholder="e.g., ABC Bank Limited"
                      value={bankForm.name}
                      aria-invalid={Boolean(bankFormErrors.name)}
                      aria-describedby={
                        bankFormErrors.name ? "bank-name-error" : undefined
                      }
                      onChange={(e) => updateBankField("name", e.target.value)}
                    />
                    {bankFormErrors.name && (
                      <small className="field-error" id="bank-name-error">
                        {bankFormErrors.name}
                      </small>
                    )}
                  </label>
                  <label className="field">
                    <span>
                      Institution Type <b className="required-mark">*</b>
                    </span>
                    <select
                      required
                      value={bankForm.institution_type}
                      aria-invalid={Boolean(bankFormErrors.institution_type)}
                      aria-describedby={
                        bankFormErrors.institution_type
                          ? "bank-type-error"
                          : undefined
                      }
                      onChange={(e) =>
                        updateBankField("institution_type", e.target.value)
                      }
                    >
                      <option value="">Select institution type</option>
                      {[
                        "Public Sector Bank",
                        "Private Sector Bank",
                        "Cooperative Bank",
                        "NBFC",
                        "Other",
                      ].map((type) => (
                        <option key={type} value={type}>
                          {type}
                        </option>
                      ))}
                    </select>
                    {bankFormErrors.institution_type && (
                      <small className="field-error" id="bank-type-error">
                        {bankFormErrors.institution_type}
                      </small>
                    )}
                  </label>
                  <label className="field">
                    <span>
                      Official Email Address <b className="required-mark">*</b>
                    </span>
                    <input
                      type="email"
                      required
                      maxLength={254}
                      placeholder="e.g., contact@bankdomain.com"
                      value={bankForm.contact_email}
                      aria-invalid={Boolean(bankFormErrors.contact_email)}
                      aria-describedby={
                        bankFormErrors.contact_email
                          ? "bank-email-error"
                          : undefined
                      }
                      onChange={(e) =>
                        updateBankField("contact_email", e.target.value)
                      }
                    />
                    {bankFormErrors.contact_email && (
                      <small className="field-error" id="bank-email-error">
                        {bankFormErrors.contact_email}
                      </small>
                    )}
                  </label>
                  <label className="field">
                    <span>
                      Official Contact Number <b className="required-mark">*</b>
                    </span>
                    <input
                      type="tel"
                      required
                      maxLength={20}
                      placeholder="Enter 10-digit mobile or official contact number"
                      value={bankForm.contact_phone}
                      aria-invalid={Boolean(bankFormErrors.contact_phone)}
                      aria-describedby={
                        bankFormErrors.contact_phone
                          ? "bank-phone-error"
                          : undefined
                      }
                      onChange={(e) =>
                        updateBankField("contact_phone", e.target.value)
                      }
                    />
                    {bankFormErrors.contact_phone && (
                      <small className="field-error" id="bank-phone-error">
                        {bankFormErrors.contact_phone}
                      </small>
                    )}
                  </label>
                  <label className="field bank-address-field">
                    <span>
                      Registered Office Address{" "}
                      <b className="required-mark">*</b>
                    </span>
                    <textarea
                      required
                      maxLength={1000}
                      rows={3}
                      placeholder="Enter the complete registered office address"
                      value={bankForm.address}
                      aria-invalid={Boolean(bankFormErrors.address)}
                      aria-describedby={
                        bankFormErrors.address
                          ? "bank-address-error"
                          : undefined
                      }
                      onChange={(e) =>
                        updateBankField("address", e.target.value)
                      }
                    />
                    {bankFormErrors.address && (
                      <small className="field-error" id="bank-address-error">
                        {bankFormErrors.address}
                      </small>
                    )}
                  </label>
                  <label className="field">
                    <span>
                      IFSC Code{" "}
                      <small className="optional-note">
                        Optional for institution-level registration
                      </small>
                    </span>
                    <input
                      maxLength={11}
                      placeholder="e.g., ABCD0123456"
                      value={bankForm.ifsc_code}
                      aria-invalid={Boolean(bankFormErrors.ifsc_code)}
                      aria-describedby={
                        bankFormErrors.ifsc_code ? "bank-ifsc-error" : undefined
                      }
                      onChange={(e) =>
                        updateBankField("ifsc_code", e.target.value)
                      }
                    />
                    {bankFormErrors.ifsc_code && (
                      <small className="field-error" id="bank-ifsc-error">
                        {bankFormErrors.ifsc_code}
                      </small>
                    )}
                  </label>
                  <label className="field">
                    <span>
                      RBI Registration / License Number{" "}
                      {bankForm.institution_type === "Other" ? (
                        <small className="optional-note">If applicable</small>
                      ) : (
                        <b className="required-mark">*</b>
                      )}
                    </span>
                    <input
                      required={Boolean(
                        bankForm.institution_type &&
                        bankForm.institution_type !== "Other",
                      )}
                      maxLength={80}
                      placeholder="Enter the applicable registration or license number"
                      value={bankForm.license_number}
                      aria-invalid={Boolean(bankFormErrors.license_number)}
                      aria-describedby={
                        bankFormErrors.license_number
                          ? "bank-license-error"
                          : undefined
                      }
                      onChange={(e) =>
                        updateBankField("license_number", e.target.value)
                      }
                    />
                    {bankFormErrors.license_number && (
                      <small className="field-error" id="bank-license-error">
                        {bankFormErrors.license_number}
                      </small>
                    )}
                  </label>
                  <div className="bank-form-actions">
                    <button className="primary" disabled={busy}>
                      {busy ? "Saving..." : "Register institution"}
                    </button>
                  </div>
                </form>
              </section>
              <section className="panel bank-panel">
                <div className="bank-section-heading">
                  <div>
                    <h2>Bank register</h2>
                    <p>
                      Review institution details and manage approval, rejection,
                      suspension, and Bank Admin invitations.
                    </p>
                  </div>
                  <span className="bank-count">
                    {banks.length}{" "}
                    {banks.length === 1 ? "institution" : "institutions"}
                  </span>
                </div>
                <div className="table-wrap bank-table-wrap">
                  <table className="bank-table">
                    <thead>
                      <tr>
                        <th>INSTITUTION</th>
                        <th>TYPE</th>
                        <th>OFFICIAL EMAIL</th>
                        <th>CONTACT NUMBER</th>
                        <th>REGISTERED OFFICE</th>
                        <th>IFSC</th>
                        <th>RBI LICENSE</th>
                        <th>SUBMITTED</th>
                        <th>STATUS</th>
                        <th>ADMINS</th>
                        <th>ACTIONS</th>
                      </tr>
                    </thead>
                    <tbody>
                      {banks.map((b) => (
                        <tr key={b.id}>
                          <td className="bank-name-cell">{b.name}</td>
                          <td>{b.institution_type || "Other"}</td>
                          <td>{b.contact_email || "-"}</td>
                          <td>{b.contact_phone || "-"}</td>
                          <td className="bank-address-cell">
                            {b.address || "-"}
                          </td>
                          <td>{b.ifsc_code || "-"}</td>
                          <td>{b.license_number || "-"}</td>
                          <td>{new Date(b.created_at).toLocaleDateString()}</td>
                          <td>
                            <span
                              className={`bank-status status-${String(b.status).toLowerCase()}`}
                            >
                              {b.status}
                            </span>
                            {b.rejection_reason && (
                              <small className="bank-rejection-summary">
                                {b.rejection_reason}
                              </small>
                            )}
                          </td>
                          <td>{b.admin_count}</td>
                          <td>
                            <div className="bank-row-actions">
                              <button
                                className="secondary small"
                                onClick={() =>
                                  run(
                                    async () =>
                                      setBankDetail(
                                        await adminApi(`/admin/banks/${b.id}`),
                                      ),
                                    "Bank details loaded.",
                                  )
                                }
                              >
                                View details
                              </button>
                              {b.status === "APPROVED" && (
                                <button
                                  className="secondary small"
                                  onClick={() =>
                                    run(
                                      () =>
                                        adminApi(
                                          `/admin/banks/${b.id}/status?status=SUSPENDED`,
                                          { method: "PATCH" },
                                        ),
                                      "Bank suspended.",
                                    )
                                  }
                                >
                                  Suspend
                                </button>
                              )}
                              {b.status === "SUSPENDED" && (
                                <button
                                  className="secondary small"
                                  onClick={() =>
                                    run(
                                      () =>
                                        adminApi(
                                          `/admin/banks/${b.id}/status?status=APPROVED`,
                                          { method: "PATCH" },
                                        ),
                                      "Bank reactivated.",
                                    )
                                  }
                                >
                                  Reactivate
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                      {!banks.length && (
                        <tr>
                          <td className="bank-empty" colSpan={11}>
                            No institutions have been registered yet.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
              {bankDetail && (
                <section className="panel bank-panel bank-detail-panel">
                  <div className="bank-section-heading">
                    <div>
                      <h2>{bankDetail.name}</h2>
                      <p>Institution details and approval actions</p>
                    </div>
                    <span
                      className={`bank-status status-${String(bankDetail.status).toLowerCase()}`}
                    >
                      {bankDetail.status}
                    </span>
                  </div>
                  <div className="bank-detail-grid">
                    <div>
                      <small>Institution type</small>
                      <b>{bankDetail.institution_type || "Other"}</b>
                    </div>
                    <div>
                      <small>Official email</small>
                      <b>{bankDetail.contact_email}</b>
                    </div>
                    <div>
                      <small>Contact number</small>
                      <b>{bankDetail.contact_phone || "-"}</b>
                    </div>
                    <div>
                      <small>Registered office</small>
                      <b>{bankDetail.address || "-"}</b>
                    </div>
                    <div>
                      <small>IFSC</small>
                      <b>{bankDetail.ifsc_code || "-"}</b>
                    </div>
                    <div>
                      <small>RBI registration / license</small>
                      <b>{bankDetail.license_number || "-"}</b>
                    </div>
                    <div>
                      <small>Submitted</small>
                      <b>{new Date(bankDetail.created_at).toLocaleString()}</b>
                    </div>
                    <div>
                      <small>Internal bank code</small>
                      <b>{bankDetail.code}</b>
                    </div>
                    {bankDetail.rejection_reason && (
                      <div className="bank-detail-rejection">
                        <small>Rejection reason</small>
                        <b>{bankDetail.rejection_reason}</b>
                      </div>
                    )}
                  </div>
                  {bankDetail.documents?.length > 0 && (
                    <div className="bank-legacy-documents">
                      <h3>Existing registration documents</h3>
                      <ul>
                        {bankDetail.documents.map((d) => (
                          <li key={d.id}>
                            <button
                              className="secondary small"
                              onClick={async () => {
                                try {
                                  const r = await fetch(
                                    `${API}/admin/banks/${bankDetail.id}/documents/${d.id}/file`,
                                    {
                                      headers: {
                                        Authorization: `Bearer ${localStorage.getItem("mortgage_admin_token")}`,
                                      },
                                    },
                                  );
                                  if (!r.ok) throw Error("Download failed");
                                  const u = URL.createObjectURL(await r.blob());
                                  window.open(u, "_blank");
                                  setTimeout(
                                    () => URL.revokeObjectURL(u),
                                    60000,
                                  );
                                } catch {
                                  notifyError();
                                }
                              }}
                            >
                              {d.filename}
                            </button>{" "}
                            <small>{Math.ceil(d.size_bytes / 1024)} KB</small>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {bankDetail.status === "PENDING" && (
                    <div className="bank-decision-actions">
                      <label className="field">
                        <span>
                          Rejection reason <b className="required-mark">*</b>
                        </span>
                        <textarea
                          minLength={10}
                          maxLength={1000}
                          rows={2}
                          placeholder="Enter a clear reason (at least 10 characters)"
                          value={rejectReason}
                          onChange={(e) => setRejectReason(e.target.value)}
                        />
                      </label>
                      <div className="bank-action-buttons">
                        <button
                          className="primary"
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              const r = await adminApi(
                                `/admin/banks/${bankDetail.id}/decision`,
                                {
                                  method: "POST",
                                  body: JSON.stringify({
                                    decision: "APPROVED",
                                  }),
                                },
                              );
                              setInviteResult(null);
                              setBankDetail(null);
                            }, "Bank approved. Review the invitation delivery status in Bank Admin Management.")
                          }
                        >
                          Approve
                        </button>
                        <button
                          className="secondary"
                          disabled={busy || rejectReason.trim().length < 10}
                          onClick={() =>
                            run(async () => {
                              await adminApi(
                                `/admin/banks/${bankDetail.id}/decision`,
                                {
                                  method: "POST",
                                  body: JSON.stringify({
                                    decision: "REJECTED",
                                    reason: rejectReason,
                                  }),
                                },
                              );
                              setRejectReason("");
                              setBankDetail(null);
                            }, "Bank rejected and the contact was notified.")
                          }
                        >
                          Reject
                        </button>
                      </div>
                    </div>
                  )}
                </section>
              )}
            </div>
          )}
          {tab === "users" && (
            <section className="panel">
              <h2>Customer directory</h2>
              <p>
                Read-only view of customer identity and verification status.
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>NAME</th>
                      <th>EMAIL</th>
                      <th>MOBILE</th>
                      <th>VERIFIED</th>
                    </tr>
                  </thead>
                  <tbody>
                    {apps.map((u) => (
                      <tr key={u.id}>
                        <td>{u.full_name}</td>
                        <td>{u.email}</td>
                        <td>{u.mobile}</td>
                        <td>{u.verified ? "Verified" : "Pending"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {tab === "policies" && (
            <>
              <section className="panel">
                <h2>Add approved policy document</h2>
                <p>
                  Only enter approved lender policy content. This stores
                  versioned source material; it does not claim vector
                  indexing/RAG retrieval is configured.
                </p>
                <form
                  className="fields"
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(
                      () =>
                        adminApi("/admin/policies", {
                          method: "POST",
                          body: JSON.stringify({
                            ...policy,
                            bank_id: policy.bank_id
                              ? Number(policy.bank_id)
                              : null,
                          }),
                        }),
                      "Policy saved.",
                    );
                  }}
                >
                  <Field
                    label="Policy title"
                    value={policy.title}
                    set={(v) => setPolicy({ ...policy, title: v })}
                    required
                  />
                  <Field
                    label="Version"
                    value={policy.policy_version}
                    set={(v) => setPolicy({ ...policy, policy_version: v })}
                    required
                  />
                  <Field
                    label="Category"
                    value={policy.category}
                    set={(v) => setPolicy({ ...policy, category: v })}
                    required
                  />
                  <label className="field">
                    <span>Policy scope</span>
                    <select
                      value={policy.bank_id}
                      onChange={(e) =>
                        setPolicy({ ...policy, bank_id: e.target.value })
                      }
                    >
                      <option value="">Global policy (all banks)</option>
                      {banks
                        .filter((b) => b.status === "APPROVED")
                        .map((b) => (
                          <option key={b.id} value={b.id}>
                            {b.name} ({b.code})
                          </option>
                        ))}
                    </select>
                  </label>
                  <label className="field full">
                    <span>Policy content</span>
                    <textarea
                      rows="5"
                      minLength="20"
                      value={policy.content}
                      onChange={(e) =>
                        setPolicy({ ...policy, content: e.target.value })
                      }
                      required
                    />
                  </label>
                  <button className="primary" disabled={busy}>
                    Save policy version
                  </button>
                </form>
              </section>
              <section className="panel">
                <h2>Policy register</h2>
                {policies.map((p) => (
                  <article className="doc" key={p.id}>
                    <div className="doc-head">
                      <b>{p.title}</b>
                      <span className="badge">
                        {p.active ? "ACTIVE" : "ARCHIVED"}
                      </span>
                    </div>
                    <small>
                      {p.category} · v{p.policy_version} ·{" "}
                      {p.bank_id ? `Bank ID ${p.bank_id}` : "Global policy"} ·{" "}
                      {p.created_by}
                    </small>
                    <p>
                      {p.content.slice(0, 500)}
                      {p.content.length > 500 ? "…" : ""}
                    </p>
                    <button
                      className="secondary small"
                      onClick={() =>
                        run(
                          () =>
                            adminApi(
                              `/admin/policies/${p.id}/active?active=${!p.active}`,
                              { method: "PATCH" },
                            ),
                          p.active ? "Policy archived." : "Policy activated.",
                        )
                      }
                    >
                      {p.active ? "Archive" : "Activate"}
                    </button>
                  </article>
                ))}
                {!policies.length && (
                  <p>No policy documents have been registered.</p>
                )}
              </section>
            </>
          )}
          {tab === "configuration" && (
            <section className="panel">
              {!config ? (
                "Loading configuration…"
              ) : (
                <>
                  <h2>Runtime configuration</h2>
                  <p>
                    These values are read-only in the UI. Edit backend/.env
                    locally and restart the API to apply changes.
                  </p>
                  <div className="config-grid">
                    <Config label="Application" value={config.app_name} />
                    <Config
                      label="Frontend origin"
                      value={config.frontend_origin}
                    />
                    <Config
                      label="Maximum upload"
                      value={`${config.max_upload_mb} MB`}
                    />
                    <Config
                      label="Uploads directory"
                      value={config.uploads_dir}
                    />
                    <Config
                      label="NVIDIA base URL"
                      value={config.nvidia.base_url}
                    />
                    <Config label="NVIDIA model" value={config.nvidia.model} />
                    <Config
                      label="API key"
                      value={config.nvidia.api_key_masked}
                    />
                    <Config
                      label="Live inference"
                      value={
                        config.nvidia.live_inference_verified
                          ? "Verified"
                          : "Not verified"
                      }
                    />
                  </div>
                  <div className="actions">
                    <button
                      className="primary"
                      disabled={busy}
                      onClick={() =>
                        run(
                          async () =>
                            setVerify(
                              await adminApi("/admin/ai/verify", {
                                method: "POST",
                              }),
                            ),
                          "NVIDIA verification finished.",
                        )
                      }
                    >
                      Verify NVIDIA model & embeddings (real call)
                    </button>
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() =>
                        run(
                          () =>
                            adminApi("/admin/policies/reindex", {
                              method: "POST",
                            }),
                          "Policies re-indexed.",
                        )
                      }
                    >
                      Re-index policies
                    </button>
                  </div>
                  {verify && (
                    <pre className="json">
                      {JSON.stringify(verify, null, 2)}
                    </pre>
                  )}
                  <div className="alert">
                    <AlertTriangle size={17} /> Secrets are never exposed here.
                    Configuration changes require local environment changes and
                    service restart.
                  </div>
                  <p>
                    <b>Integration status:</b> NVIDIA key configured is not
                    equivalent to successful model inference. RAG/vector index
                    and NeMo Agent Toolkit status are not represented as
                    connected unless separately implemented and verified.
                  </p>
                </>
              )}
            </section>
          )}
          {tab === "bankadmins" && (
            <section className="panel admin-ops">
              <p>
                Manage authorized administrators and invitation lifecycle. Last
                login is not currently tracked.
              </p>
              <div className="bank-admin-counts">
                {[
                  ["Active", ops.bankadmins?.counts?.active],
                  ["Suspended", ops.bankadmins?.counts?.suspended],
                  ["Pending", ops.bankadmins?.counts?.pending],
                  ["Accepted", ops.bankadmins?.counts?.accepted],
                  ["Expired", ops.bankadmins?.counts?.expired],
                  ["Revoked", ops.bankadmins?.counts?.revoked],
                ].map(([label, count]) => (
                  <span key={label}>
                    <b>{count ?? 0}</b>
                    {label}
                  </span>
                ))}
              </div>
              <div className="toolbar">
                <input
                  aria-label="Search bank administrators"
                  placeholder="Search name, email, bank"
                  value={adminQuery}
                  onChange={(e) => setAdminQuery(e.target.value)}
                />
                <select
                  aria-label="Filter bank administrator status"
                  value={adminStatus}
                  onChange={(e) => setAdminStatus(e.target.value)}
                >
                  <option value="all">All statuses</option>
                  <option value="active">Active</option>
                  <option value="suspended">Suspended</option>
                  <option value="pending">Invitation pending</option>
                  <option value="accepted">Accepted</option>
                  <option value="expired">Expired</option>
                  <option value="revoked">Revoked</option>
                </select>
                <button
                  className="primary"
                  onClick={() => setShowAdminInvite((v) => !v)}
                >
                  Invite Bank Admin
                </button>
              </div>
              {showAdminInvite && (
                <>
                  <section className="panel admin-ops invite-form-panel">
                    <div className="bank-section-heading">
                      <div>
                        <h3>Invite Bank Admin</h3>
                        <p>
                          Send a single-use activation link to an administrator
                          for an approved bank.
                        </p>
                      </div>
                    </div>
                    <form
                      className="bank-invite-form"
                      onSubmit={(e) => {
                        e.preventDefault();
                        run(async () => {
                          setInviteResult(
                            await adminApi("/admin/bank-invitations", {
                              method: "POST",
                              body: JSON.stringify({
                                ...inviteForm,
                                bank_id: Number(inviteForm.bank_id),
                              }),
                            }),
                          );
                          setInviteForm({
                            bank_id: "",
                            full_name: "",
                            email: "",
                          });
                          setShowAdminInvite(false);
                        }, "Invitation email sent.");
                      }}
                    >
                      <label className="field">
                        <span>
                          Approved institution{" "}
                          <b className="required-mark">*</b>
                        </span>
                        <select
                          required
                          value={inviteForm.bank_id}
                          onChange={(e) =>
                            setInviteForm({
                              ...inviteForm,
                              bank_id: e.target.value,
                            })
                          }
                        >
                          <option value="">Select approved institution</option>
                          {banks
                            .filter((b) => b.status === "APPROVED")
                            .map((b) => (
                              <option key={b.id} value={b.id}>
                                {b.name} ({b.code})
                              </option>
                            ))}
                        </select>
                      </label>
                      <Field
                        label="Bank Admin full name"
                        value={inviteForm.full_name}
                        set={(v) =>
                          setInviteForm({ ...inviteForm, full_name: v })
                        }
                        required
                      />
                      <Field
                        label="Bank Admin email"
                        type="email"
                        value={inviteForm.email}
                        set={(v) => setInviteForm({ ...inviteForm, email: v })}
                        required
                      />
                      <div className="bank-invite-action">
                        <button
                          className="primary"
                          disabled={
                            busy ||
                            !banks.some(
                              (b) =>
                                String(b.id) === inviteForm.bank_id &&
                                b.status === "APPROVED",
                            )
                          }
                        >
                          Create invitation
                        </button>
                      </div>
                    </form>
                  </section>
                  <button
                    className="secondary small"
                    onClick={() => setShowAdminInvite(false)}
                  >
                    Cancel invitation
                  </button>
                </>
              )}
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>NAME</th>
                      <th>OFFICIAL EMAIL</th>
                      <th>BANK</th>
                      <th>ACCOUNT</th>
                      <th>INVITATION</th>
                      <th>CREATED</th>
                      <th>LAST LOGIN</th>
                      <th>ACTIONS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(ops.bankadmins?.items || []).map((u) => (
                      <tr key={`${u.kind}-${u.id}`}>
                        <td>{u.full_name}</td>
                        <td>{u.email}</td>
                        <td>{u.bank_name}</td>
                        <td>
                          {u.kind === "account"
                            ? u.active
                              ? "Active"
                              : "Suspended"
                            : "?"}
                        </td>
                        <td>
                          {u.invitation_status.replace(/^./, (c) =>
                            c.toUpperCase(),
                          )}
                        </td>
                        <td>
                          {u.created_at
                            ? new Date(u.created_at).toLocaleDateString()
                            : "—"}
                        </td>
                        <td>Not tracked</td>
                        <td>
                          <BankAdminActions row={u} banks={banks} run={run} />
                        </td>
                      </tr>
                    ))}
                    {!ops.bankadmins?.items?.length && (
                      <tr>
                        <td colSpan="8">
                          {busy
                            ? "Loading bank administrator records"
                            : adminQuery || adminStatus !== "all"
                              ? "No bank administrators or invitations match these filters."
                              : "No Bank Admin accounts or invitations have been created yet."}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {tab === "users" && (
            <section className="panel admin-ops">
              <p>
                Customer administration shows masked contact details in the
                directory; sensitive application documents are not available
                here.
              </p>
              <div className="toolbar">
                <input
                  aria-label="Search customers"
                  placeholder="Search ID, name, email, or mobile"
                  value={customerQuery}
                  onChange={(e) => {
                    setCustomerPage(0);
                    setCustomerQuery(e.target.value);
                  }}
                />
                <select
                  value={customerFilters.status}
                  onChange={(e) =>
                    setCustomerFilters({
                      ...customerFilters,
                      status: e.target.value,
                    })
                  }
                >
                  <option value="all">All account states</option>
                  <option value="active">Active</option>
                  <option value="suspended">Suspended</option>
                </select>
                <select
                  value={customerFilters.verified}
                  onChange={(e) =>
                    setCustomerFilters({
                      ...customerFilters,
                      verified: e.target.value,
                    })
                  }
                >
                  <option value="all">All verification states</option>
                  <option value="verified">Verified</option>
                  <option value="pending">Pending</option>
                </select>
                <input
                  aria-label="Registered from"
                  type="date"
                  value={customerFilters.start}
                  onChange={(e) =>
                    setCustomerFilters({
                      ...customerFilters,
                      start: e.target.value,
                    })
                  }
                />
                <input
                  aria-label="Registered to"
                  type="date"
                  value={customerFilters.end}
                  onChange={(e) =>
                    setCustomerFilters({
                      ...customerFilters,
                      end: e.target.value,
                    })
                  }
                />
                <select
                  value={customerFilters.sort}
                  onChange={(e) =>
                    setCustomerFilters({
                      ...customerFilters,
                      sort: e.target.value,
                    })
                  }
                >
                  <option value="newest">Newest registration</option>
                  <option value="oldest">Oldest registration</option>
                  <option value="name">Name A–Z</option>
                </select>
                <select
                  value={customerFilters.limit}
                  onChange={(e) => {
                    setCustomerPage(0);
                    setCustomerFilters({
                      ...customerFilters,
                      limit: Number(e.target.value),
                    });
                  }}
                >
                  <option value={10}>10 per page</option>
                  <option value={25}>25 per page</option>
                  <option value={50}>50 per page</option>
                </select>
                <button
                  className="secondary small"
                  onClick={() => {
                    setCustomerQuery("");
                    setCustomerPage(0);
                    setCustomerFilters({
                      status: "all",
                      verified: "all",
                      start: "",
                      end: "",
                      sort: "newest",
                      limit: 25,
                    });
                  }}
                >
                  Clear filters
                </button>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>NAME</th>
                      <th>EMAIL</th>
                      <th>MOBILE</th>
                      <th>REGISTERED</th>
                      <th>VERIFIED</th>
                      <th>ACCOUNT</th>
                      <th>APPLICATIONS</th>
                      <th>LAST LOGIN</th>
                      <th>ACTIONS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(ops.customers?.items || []).map((c) => (
                      <tr key={c.id}>
                        <td>{c.id}</td>
                        <td>{c.full_name}</td>
                        <td>{c.email}</td>
                        <td>{c.mobile}</td>
                        <td>
                          {c.created_at
                            ? new Date(c.created_at).toLocaleDateString()
                            : "—"}
                        </td>
                        <td>{c.verified ? "Verified" : "Pending"}</td>
                        <td>{c.active ? "Active" : "Suspended"}</td>
                        <td>{c.application_count}</td>
                        <td>Not tracked</td>
                        <td>
                          <button
                            className="secondary small"
                            onClick={() =>
                              run(
                                () =>
                                  adminApi(`/admin/customers/${c.id}`).then(
                                    (data) =>
                                      setOps((v) => ({
                                        ...v,
                                        customerDetail: data,
                                      })),
                                  ),
                                "Customer details loaded.",
                              )
                            }
                          >
                            View
                          </button>{" "}
                          <button
                            className="secondary small"
                            onClick={() => {
                              const reason = window.prompt(
                                "Enter a reason for this account change (minimum 8 characters).",
                              );
                              if (reason && reason.trim().length >= 8)
                                run(
                                  () =>
                                    adminApi(
                                      `/admin/customers/${c.id}/status`,
                                      {
                                        method: "PATCH",
                                        body: JSON.stringify({
                                          active: !c.active,
                                          reason,
                                        }),
                                      },
                                    ),
                                  c.active
                                    ? "Customer suspended."
                                    : "Customer reactivated.",
                                );
                            }}
                          >
                            {c.active ? "Suspend" : "Reactivate"}
                          </button>
                        </td>
                      </tr>
                    ))}
                    {!ops.customers?.items?.length && (
                      <tr>
                        <td colSpan="10">
                          {busy
                            ? "Loading bank administrators?"
                            : adminQuery || adminStatus !== "all"
                              ? "No bank administrators or invitations match these filters."
                              : "No Bank Admin accounts or invitations have been created yet."}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="pagination">
                <span>{ops.customers?.total || 0} customers</span>
                <button
                  className="secondary small"
                  disabled={customerPage === 0}
                  onClick={() => setCustomerPage(customerPage - 1)}
                >
                  Previous
                </button>
                <span>
                  Page {customerPage + 1} of{" "}
                  {Math.max(
                    1,
                    Math.ceil(
                      (ops.customers?.total || 0) / customerFilters.limit,
                    ),
                  )}
                </span>
                <button
                  className="secondary small"
                  disabled={
                    (customerPage + 1) * customerFilters.limit >=
                    (ops.customers?.total || 0)
                  }
                  onClick={() => setCustomerPage(customerPage + 1)}
                >
                  Next
                </button>
              </div>
              {ops.customerDetail && (
                <div className="admin-detail">
                  <h3>Customer details · #{ops.customerDetail.id}</h3>
                  <p>
                    {ops.customerDetail.full_name} · {ops.customerDetail.email}{" "}
                    · {ops.customerDetail.mobile}
                  </p>
                  <p>
                    Registered{" "}
                    {ops.customerDetail.created_at
                      ? new Date(ops.customerDetail.created_at).toLocaleString()
                      : "unknown"}{" "}
                    ·{" "}
                    {ops.customerDetail.verified
                      ? "Verified"
                      : "Verification pending"}{" "}
                    · {ops.customerDetail.active ? "Active" : "Suspended"}
                  </p>
                  <p>
                    Applications by status:{" "}
                    {Object.entries(ops.customerDetail.applications || {})
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(" · ") || "No applications"}
                  </p>
                  <button
                    className="secondary small"
                    onClick={() =>
                      setOps((v) => ({ ...v, customerDetail: null }))
                    }
                  >
                    Close details
                  </button>
                </div>
              )}
            </section>
          )}
          {tab === "monitoring" && (
            <section className="panel admin-ops">
              <div className="section-heading">
                <div>
                  <p>
                    Healthy means a recent check succeeded; Degraded means
                    recorded failures; Unavailable means a check confirmed it;
                    Unknown means no reliable signal was recorded.
                  </p>
                </div>
                <div className="inline-actions">
                  <label className="compact-label">
                    History{" "}
                    <select
                      value={monitoringHours}
                      onChange={(e) =>
                        setMonitoringHours(Number(e.target.value))
                      }
                    >
                      <option value={24}>24 hours</option>
                      <option value={168}>7 days</option>
                      <option value={720}>30 days</option>
                    </select>
                  </label>
                  <button className="secondary" onClick={load}>
                    <RefreshCw size={15} /> Refresh
                  </button>
                </div>
              </div>
              {ops.monitoring ? (
                <>
                  <p className="supporting">
                    Checked{" "}
                    {new Date(ops.monitoring.checked_at).toLocaleString()} ?
                    Incident period: last {ops.monitoring.period_hours} hours
                  </p>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>SERVICE</th>
                          <th>STATUS</th>
                          <th>LAST CHECKED</th>
                          <th>LATENCY / ERROR RATE</th>
                          <th>RECENT FAILURES / NOTES</th>
                          <th>ACTION</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ops.monitoring.services.map((s) => (
                          <tr key={s.name}>
                            <td>{s.name}</td>
                            <td>
                              <span
                                className={`admin-status-badge status-${String(s.status).toLowerCase()}`}
                              >
                                {s.status}
                              </span>
                            </td>
                            <td>
                              {s.last_checked
                                ? new Date(s.last_checked).toLocaleString()
                                : "No recent check"}
                            </td>
                            <td>
                              {s.latency_ms != null
                                ? `${s.latency_ms} ms`
                                : s.failures != null
                                  ? `${s.failures} failures in period`
                                  : "Not measured"}
                            </td>
                            <td>
                              {s.details || "No recent failures recorded."}
                            </td>
                            <td>
                              {s.name === "NVIDIA API" ? (
                                <button
                                  className="secondary small"
                                  disabled={busy}
                                  onClick={() =>
                                    run(
                                      () =>
                                        adminApi("/admin/ai/verify", {
                                          method: "POST",
                                        }).then(setVerify),
                                      "Controlled NVIDIA connectivity check completed.",
                                    )
                                  }
                                >
                                  Run verification
                                </button>
                              ) : s.name === "Database" ? (
                                <span>Health check on refresh</span>
                              ) : (
                                <span>Telemetry view</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <h3 className="subsection-title">Recent incidents</h3>
                  {ops.monitoring.incidents.length ? (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>TIME</th>
                            <th>SERVICE</th>
                            <th>SEVERITY</th>
                            <th>SUMMARY</th>
                            <th>STATUS</th>
                          </tr>
                        </thead>
                        <tbody>
                          {ops.monitoring.incidents.map((i, n) => (
                            <tr key={`${i.service}-${i.timestamp}-${n}`}>
                              <td>{new Date(i.timestamp).toLocaleString()}</td>
                              <td>{i.service}</td>
                              <td>{i.severity}</td>
                              <td>{i.summary}</td>
                              <td>{i.status}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="empty-state">
                      No recorded failures in the selected period.
                    </p>
                  )}
                  {verify && (
                    <div className="admin-detail">
                      <b>Controlled NVIDIA connectivity check</b>
                      <p>
                        Checked{" "}
                        {verify.checked_at
                          ? new Date(verify.checked_at).toLocaleString()
                          : "time not recorded"}{" "}
                        ? Chat inference:{" "}
                        {verify.inference_ok ? "Passed" : "Failed"} ?
                        Embeddings: {verify.embedding_ok ? "Passed" : "Failed"}{" "}
                        ? Model listed:{" "}
                        {verify.model_listed === null
                          ? "Not confirmed"
                          : verify.model_listed
                            ? "Yes"
                            : "No"}
                      </p>
                    </div>
                  )}
                </>
              ) : (
                <p>
                  {busy ? "Checking services?" : "Monitoring data unavailable."}
                </p>
              )}
            </section>
          )}
          {tab === "notifications" && (
            <section className="panel admin-ops">
              <div className="section-heading">
                <div>
                  <p>
                    Persistent operational events. Removing an alert does not
                    remove its source audit or business record.
                  </p>
                </div>
                <div className="inline-actions">
                  <span className="unread-count">
                    {ops.notifications?.unread_count || 0} unread
                  </span>
                  <button
                    className="secondary"
                    disabled={!ops.notifications?.unread_count || busy}
                    onClick={() =>
                      run(
                        () =>
                          adminApi("/admin/notifications/read-all", {
                            method: "POST",
                          }),
                        "All alerts marked read.",
                      )
                    }
                  >
                    Mark all as read
                  </button>
                </div>
              </div>
              <div className="toolbar notification-filters">
                <label className="search-field">
                  <Search size={15} />
                  <input
                    aria-label="Search notifications"
                    placeholder="Search alerts"
                    value={noticeQuery}
                    onChange={(e) => {
                      setNoticeOffset(0);
                      setNoticeQuery(e.target.value);
                    }}
                  />
                </label>
                <select
                  aria-label="Category filter"
                  value={noticeFilter}
                  onChange={(e) => {
                    setNoticeOffset(0);
                    setNoticeFilter(e.target.value);
                  }}
                >
                  <option value="all">All categories</option>
                  <option value="BANK">Bank</option>
                  <option value="AI">AI</option>
                  <option value="SECURITY">Security</option>
                </select>
                <select
                  aria-label="Severity filter"
                  value={noticeSeverity}
                  onChange={(e) => {
                    setNoticeOffset(0);
                    setNoticeSeverity(e.target.value);
                  }}
                >
                  <option value="all">All severities</option>
                  <option value="HIGH">High</option>
                  <option value="MEDIUM">Medium</option>
                  <option value="INFO">Information</option>
                </select>
                <select
                  aria-label="Read status filter"
                  value={noticeRead}
                  onChange={(e) => {
                    setNoticeOffset(0);
                    setNoticeRead(e.target.value);
                  }}
                >
                  <option value="all">Read and unread</option>
                  <option value="unread">Unread</option>
                  <option value="read">Read</option>
                </select>
                <label className="date-filter">
                  From{" "}
                  <input
                    type="date"
                    value={noticeDates.start}
                    onChange={(e) => {
                      setNoticeOffset(0);
                      setNoticeDates({ ...noticeDates, start: e.target.value });
                    }}
                  />
                </label>
                <label className="date-filter">
                  To{" "}
                  <input
                    type="date"
                    value={noticeDates.end}
                    onChange={(e) => {
                      setNoticeOffset(0);
                      setNoticeDates({ ...noticeDates, end: e.target.value });
                    }}
                  />
                </label>
                <button
                  className="secondary small"
                  onClick={() => {
                    setNoticeOffset(0);
                    setNoticeQuery("");
                    setNoticeFilter("all");
                    setNoticeSeverity("all");
                    setNoticeRead("all");
                    setNoticeDates({ start: "", end: "" });
                  }}
                >
                  Clear filters
                </button>
              </div>
              {(ops.notifications?.items || []).map((n) => (
                <article
                  className={`admin-notice ${n.read ? "is-read" : "is-unread"}`}
                  key={n.id}
                >
                  <div className="notice-copy">
                    <div className="notice-title-row">
                      <b>{n.title}</b>
                      <span
                        className={`admin-status-badge severity-${n.severity.toLowerCase()}`}
                      >
                        {n.severity}
                      </span>
                      <span className="notice-category">{n.category}</span>
                      <span className="notice-read-state">
                        {n.read ? "Read" : "Unread"}
                      </span>
                    </div>
                    <p>{n.message}</p>
                    <small>{new Date(n.created_at).toLocaleString()}</small>
                  </div>
                  <div className="notice-actions">
                    {n.resource_type === "bank" ? (
                      <button
                        className="secondary small"
                        onClick={() => setTab("banks")}
                      >
                        Open bank register
                      </button>
                    ) : n.category === "AI" ? (
                      <button
                        className="secondary small"
                        onClick={() => setTab("monitoring")}
                      >
                        Open monitoring
                      </button>
                    ) : n.category === "SECURITY" ? (
                      <button
                        className="secondary small"
                        onClick={() => setTab("audit")}
                      >
                        Open audit log
                      </button>
                    ) : null}
                    <button
                      className="secondary small"
                      onClick={() =>
                        run(
                          () =>
                            adminApi(`/admin/notifications/${n.id}/read`, {
                              method: "PATCH",
                              body: JSON.stringify({ read: !n.read }),
                            }),
                          n.read
                            ? "Alert marked unread."
                            : "Alert marked read.",
                        )
                      }
                    >
                      {n.read ? "Mark unread" : "Mark read"}
                    </button>
                    <button
                      className="icon-button danger-icon"
                      aria-label={`Delete ${n.title}`}
                      title="Delete notification"
                      onClick={() => {
                        if (
                          window.confirm(
                            "Delete this notification? The underlying audit and business records will be retained.",
                          )
                        )
                          run(
                            () =>
                              adminApi(`/admin/notifications/${n.id}`, {
                                method: "DELETE",
                              }),
                            "Notification deleted.",
                          );
                      }}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </article>
              ))}
              {!ops.notifications?.items?.length && (
                <p className="empty-state">
                  {busy
                    ? "Loading alerts?"
                    : noticeQuery ||
                        noticeFilter !== "all" ||
                        noticeSeverity !== "all" ||
                        noticeRead !== "all" ||
                        noticeDates.start ||
                        noticeDates.end
                      ? "No alerts match the selected filters."
                      : "No operational alerts have been recorded."}
                </p>
              )}
              <div className="pagination">
                <span>
                  {ops.notifications?.total || 0} alerts ?{" "}
                  {ops.notifications?.unread_count || 0} unread
                </span>
                <button
                  className="secondary small"
                  disabled={!noticeOffset}
                  onClick={() =>
                    setNoticeOffset(Math.max(0, noticeOffset - 25))
                  }
                >
                  Previous
                </button>
                <span>
                  Page {Math.floor(noticeOffset / 25) + 1} of{" "}
                  {Math.max(1, Math.ceil((ops.notifications?.total || 0) / 25))}
                </span>
                <button
                  className="secondary small"
                  disabled={
                    noticeOffset + 25 >= (ops.notifications?.total || 0)
                  }
                  onClick={() => setNoticeOffset(noticeOffset + 25)}
                >
                  Next
                </button>
              </div>
            </section>
          )}
          {tab === "audit" && (
            <section className="panel admin-ops">
              <div className="section-heading">
                <div>
                  <p>
                    Review a traceable history of administrative and
                    security-sensitive actions. Audit records are read-only and
                    cannot be edited or deleted through this console.
                  </p>
                </div>
                <button
                  className="secondary"
                  onClick={() => {
                    const params = new URLSearchParams(
                      Object.entries(auditFilters).filter(([, v]) => v),
                    );
                    run(
                      () => downloadAdminCsv(`/admin/audit-logs.csv?${params}`),
                      "Filtered audit CSV exported.",
                    );
                  }}
                >
                  Export filtered CSV
                </button>
              </div>
              <div className="toolbar audit-filters">
                {[
                  ["actor", "Actor"],
                  ["action", "Action"],
                  ["resource_type", "Resource type"],
                ].map(([k, label]) => (
                  <input
                    key={k}
                    aria-label={label}
                    placeholder={label}
                    value={auditFilters[k]}
                    onChange={(e) => {
                      setAuditOffset(0);
                      setAuditFilters({ ...auditFilters, [k]: e.target.value });
                    }}
                  />
                ))}
                <select
                  aria-label="Outcome filter"
                  value={auditFilters.outcome}
                  onChange={(e) => {
                    setAuditOffset(0);
                    setAuditFilters({
                      ...auditFilters,
                      outcome: e.target.value,
                    });
                  }}
                >
                  <option value="">All outcomes</option>
                  <option value="success">Success</option>
                  <option value="failure">Failure</option>
                  <option value="recorded">Recorded</option>
                </select>
                <select
                  aria-label="Audit severity"
                  value={auditFilters.severity}
                  onChange={(e) => {
                    setAuditOffset(0);
                    setAuditFilters({
                      ...auditFilters,
                      severity: e.target.value,
                    });
                  }}
                >
                  <option value="">All severities</option>
                  <option value="high">High</option>
                  <option value="info">Informational</option>
                </select>
                <select
                  aria-label="Audit category"
                  value={auditFilters.category}
                  onChange={(e) => {
                    setAuditOffset(0);
                    setAuditFilters({
                      ...auditFilters,
                      category: e.target.value,
                    });
                  }}
                >
                  <option value="">All categories</option>
                  <option value="security">Security</option>
                  <option value="administration">Administration</option>
                </select>
                <label className="date-filter">
                  From{" "}
                  <input
                    type="date"
                    value={auditFilters.start}
                    onChange={(e) => {
                      setAuditOffset(0);
                      setAuditFilters({
                        ...auditFilters,
                        start: e.target.value,
                      });
                    }}
                  />
                </label>
                <label className="date-filter">
                  To{" "}
                  <input
                    type="date"
                    value={auditFilters.end}
                    onChange={(e) => {
                      setAuditOffset(0);
                      setAuditFilters({ ...auditFilters, end: e.target.value });
                    }}
                  />
                </label>
                <button
                  className="secondary small"
                  onClick={() => {
                    setAuditOffset(0);
                    setAuditFilters({
                      actor: "",
                      action: "",
                      resource_type: "",
                      outcome: "",
                      severity: "",
                      category: "",
                      start: "",
                      end: "",
                    });
                  }}
                >
                  Clear filters
                </button>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>DATE & TIME</th>
                      <th>ACTOR</th>
                      <th>ROLE</th>
                      <th>ACTION</th>
                      <th>TARGET</th>
                      <th>OUTCOME</th>
                      <th>DETAILS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logs.map((x) => (
                      <tr key={x.id}>
                        <td>{new Date(x.created_at).toLocaleString()}</td>
                        <td>{x.actor_email}</td>
                        <td>{x.actor_role.replaceAll("_", " ")}</td>
                        <td>{x.action_label || x.action}</td>
                        <td>
                          {x.resource_type} {x.resource_id}
                        </td>
                        <td>
                          <span
                            className={`admin-status-badge severity-${x.severity.toLowerCase()}`}
                          >
                            {x.outcome}
                          </span>
                        </td>
                        <td>
                          <details className="audit-detail">
                            <summary>View details</summary>
                            <dl>
                              <dt>Event code</dt>
                              <dd>{x.action}</dd>
                              <dt>Target ID</dt>
                              <dd>{x.resource_id || "Not recorded"}</dd>
                              <dt>Reason / context</dt>
                              <dd>
                                {x.detail || "No additional details recorded."}
                              </dd>
                              <dt>Request ID</dt>
                              <dd>{x.request_id || "Not recorded"}</dd>
                            </dl>
                          </details>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!logs.length && (
                <p className="empty-state">
                  {busy
                    ? "Loading audit events?"
                    : "No audit records match the selected filters."}
                </p>
              )}
              <div className="pagination">
                <span>{ops.auditTotal || 0} records</span>
                <button
                  className="secondary small"
                  disabled={!auditOffset}
                  onClick={() => setAuditOffset(Math.max(0, auditOffset - 50))}
                >
                  Previous
                </button>
                <span>
                  Page {Math.floor(auditOffset / 50) + 1} of{" "}
                  {Math.max(1, Math.ceil((ops.auditTotal || 0) / 50))}
                </span>
                <button
                  className="secondary small"
                  disabled={auditOffset + 50 >= (ops.auditTotal || 0)}
                  onClick={() => setAuditOffset(auditOffset + 50)}
                >
                  Next
                </button>
              </div>
            </section>
          )}
          {tab === "reports" && (
            <section className="panel admin-ops">
              <div className="section-heading">
                <div>
                  <p>
                    Review platform activity for a selected period and export
                    authorized aggregate reports.
                  </p>
                </div>
                <button
                  className="primary"
                  disabled={busy || Boolean(reportDateError)}
                  onClick={() => {
                    if (
                      reportPeriod.start &&
                      reportPeriod.end &&
                      reportPeriod.start > reportPeriod.end
                    ) {
                      setReportDateError(
                        "Start date must be on or before end date.",
                      );
                      return;
                    }
                    setReportDateError("");
                    setAppliedReportPeriod({ ...reportPeriod });
                  }}
                >
                  Apply filters
                </button>
              </div>
              <div className="toolbar report-filters">
                <label className="date-filter">
                  Start date{" "}
                  <input
                    type="date"
                    value={reportPeriod.start}
                    onChange={(e) => {
                      setReportPeriod({
                        ...reportPeriod,
                        start: e.target.value,
                      });
                      setReportDateError("");
                    }}
                  />
                </label>
                <label className="date-filter">
                  End date{" "}
                  <input
                    type="date"
                    value={reportPeriod.end}
                    onChange={(e) => {
                      setReportPeriod({ ...reportPeriod, end: e.target.value });
                      setReportDateError("");
                    }}
                  />
                </label>
                <span className="period-label">
                  Reporting period:{" "}
                  {ops.reports?.period?.start || "All available"} to{" "}
                  {ops.reports?.period?.end || "present"}
                </span>
                <button
                  className="secondary small"
                  onClick={() => {
                    setReportPeriod({ start: "", end: "" });
                    setAppliedReportPeriod({ start: "", end: "" });
                    setReportDateError("");
                  }}
                >
                  Reset
                </button>
                <button
                  className="secondary"
                  disabled={!ops.reports || busy}
                  onClick={() => {
                    const params = new URLSearchParams(
                      Object.entries(appliedReportPeriod).filter(([, v]) => v),
                    );
                    run(
                      () => downloadAdminCsv(`/admin/reports.csv?${params}`),
                      "Filtered operational report exported.",
                    );
                  }}
                >
                  Export CSV
                </button>
              </div>
              {reportDateError && (
                <p className="field-error" role="alert">
                  {reportDateError}
                </p>
              )}
              {ops.reports ? (
                <>
                  <div className="report-summary">
                    <b>{ops.reports.period.start || "All available data"}</b>
                    <span>through</span>
                    <b>{ops.reports.period.end || "present"}</b>
                  </div>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>REPORT CATEGORY</th>
                          <th>STATUS / EVENT</th>
                          <th>COUNT</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[
                          ["Bank registrations", ops.reports.banks_by_status],
                          [
                            "Customer accounts",
                            ops.reports.customers_by_status,
                          ],
                          [
                            "Customer verification",
                            ops.reports.customers_by_verification,
                          ],
                          [
                            "Mortgage applications",
                            ops.reports.applications_by_status,
                          ],
                          ["AI analysis", ops.reports.analysis_by_status],
                          [
                            "Document extraction",
                            ops.reports.document_extraction_by_status,
                          ],
                          [
                            "Administrative / security events",
                            ops.reports.audit_by_action,
                          ],
                        ].flatMap(([group, values]) =>
                          Object.keys(values || {}).length
                            ? Object.entries(values).map(([name, count]) => (
                                <tr key={`${group}-${name}`}>
                                  <td>{group}</td>
                                  <td>{name}</td>
                                  <td>{count}</td>
                                </tr>
                              ))
                            : [
                                <tr key={`${group}-empty`}>
                                  <td>{group}</td>
                                  <td colSpan="2" className="supporting">
                                    No data for the selected period.
                                  </td>
                                </tr>,
                              ],
                        )}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <p className="empty-state">
                  {busy
                    ? "Loading operational report?"
                    : "Report data is unavailable."}
                </p>
              )}
            </section>
          )}
          {tab === "settings" && (
            <section className="panel admin-ops settings-page">
              {!config ? (
                <p>
                  {busy
                    ? "Loading supported settings?"
                    : "Configuration unavailable."}
                </p>
              ) : (
                <>
                  <div className="section-heading">
                    <div>
                      <p>
                        Read-only runtime configuration from the backend. Secret
                        values and connection strings are never shown.
                      </p>
                    </div>
                    <button className="secondary" onClick={load}>
                      <RefreshCw size={15} /> Refresh status
                    </button>
                  </div>
                  <section className="setting-section">
                    <h3>Platform Information</h3>
                    <p>Application identity and deployment environment.</p>
                    <div className="settings-grid">
                      <Config
                        label="Application name"
                        value={config.app_name}
                      />
                      <Config label="Environment" value={config.environment} />
                      <Config
                        label="Frontend origin"
                        value={config.frontend_origin}
                      />
                      <Config
                        label="Backend/API health"
                        value={config.backend_health}
                      />
                      <Config
                        label="Maximum upload size"
                        value={`${config.max_upload_mb} MB`}
                      />
                      <Config
                        label="Runtime version"
                        value={config.runtime_version}
                      />
                    </div>
                  </section>
                  <section className="setting-section">
                    <h3>AI Services</h3>
                    <p>
                      Provider connectivity is based only on an explicit recent
                      check; configuration alone is not a health signal.
                    </p>
                    <div className="settings-grid">
                      <Config label="Provider" value={config.nvidia.provider} />
                      <Config
                        label="API connectivity"
                        value={config.nvidia.status}
                      />
                      <Config
                        label="Nemotron model"
                        value={config.nvidia.model}
                      />
                      <Config
                        label="Embedding model"
                        value={config.nvidia.embedding_model}
                      />
                      <Config
                        label="API key"
                        value={config.nvidia.api_key_masked}
                      />
                      <Config
                        label="Last verification"
                        value={
                          config.nvidia.last_verification
                            ? new Date(
                                config.nvidia.last_verification,
                              ).toLocaleString()
                            : "No check recorded"
                        }
                      />
                      <Config
                        label="Analysis timeout"
                        value={`${config.nvidia.timeout_seconds} seconds`}
                      />
                      <Config
                        label="Last check result"
                        value={
                          config.nvidia.last_error ||
                          "No recent failure reported"
                        }
                      />
                    </div>
                  </section>
                  <section className="setting-section">
                    <h3>Authentication & Security</h3>
                    <p>
                      Platform Admin access continues to require email
                      verification by OTP.
                    </p>
                    <div className="settings-grid">
                      <Config
                        label="Platform Admin sign-in"
                        value={config.authentication.platform_admin}
                      />
                      <Config
                        label="OTP expiry"
                        value={`${config.authentication.otp_expiry_minutes} minutes`}
                      />
                      <Config
                        label="Resend cooldown"
                        value={`${config.authentication.resend_cooldown_seconds} seconds`}
                      />
                      <Config
                        label="Login lockout"
                        value={`${config.authentication.login_max_failures} failures ? ${config.authentication.login_lockout_minutes} minutes`}
                      />
                      <Config
                        label="SMTP"
                        value={
                          config.authentication.smtp_configured
                            ? "Configured"
                            : "Not configured"
                        }
                      />
                      <Config
                        label="Email delivery test"
                        value={config.authentication.email_delivery_test}
                      />
                    </div>
                  </section>
                  <section className="setting-section">
                    <h3>Document Processing</h3>
                    <p>Processing summaries use persisted document records.</p>
                    <div className="settings-grid">
                      <Config
                        label="OCR engine"
                        value={config.documents.ocr_engine}
                      />
                      <Config
                        label="OCR configuration"
                        value={config.documents.ocr_status}
                      />
                      <Config
                        label="OCR page limit"
                        value={`${config.documents.ocr_page_limit} pages`}
                      />
                      <Config
                        label="Recorded analysis failures"
                        value={config.documents.analysis_failures}
                      />
                      <Config
                        label="Recorded extraction failures"
                        value={config.documents.extraction_failures}
                      />
                      <Config
                        label="Guardrails package"
                        value={config.documents.guardrails_runtime}
                      />
                    </div>
                  </section>
                  <section className="setting-section">
                    <h3>Operational Information</h3>
                    <p>
                      Runtime settings are read-only and require a controlled
                      environment update and service restart.
                    </p>
                    <div className="settings-grid">
                      <Config
                        label="Database connection"
                        value={config.database_status}
                      />
                      <Config
                        label="Assignment retry interval"
                        value={`${config.assignment_retry_interval_seconds} seconds`}
                      />
                      <Config
                        label="Last health check"
                        value={
                          config.health_checked_at
                            ? new Date(
                                config.health_checked_at,
                              ).toLocaleString()
                            : "Unavailable"
                        }
                      />
                    </div>
                  </section>
                </>
              )}
            </section>
          )}
          {tab === "audit-old" && (
            <section className="panel">
              <h2>Audit trail</h2>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>TIME</th>
                      <th>ACTOR</th>
                      <th>ACTION</th>
                      <th>RESOURCE</th>
                      <th>DETAIL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logs.map((x) => (
                      <tr key={x.id}>
                        <td>{new Date(x.created_at).toLocaleString()}</td>
                        <td>
                          {x.actor_email}
                          <small>{x.actor_role}</small>
                        </td>
                        <td>{x.action}</td>
                        <td>
                          {x.resource_type} {x.resource_id}
                        </td>
                        <td>{x.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          <div className="admin-foot">
            <CheckCircle2 size={16} /> Admin actions are API-authorized and
            audited where implemented. Review all access controls before
            production use.
          </div>
        </section>
      </main>
    </div>
  );
}
function Field({
  label,
  value,
  set,
  type = "text",
  visible,
  onToggleVisibility,
  ...props
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {onToggleVisibility ? (
        <div className="password-control">
          <input
            type={visible ? "text" : type}
            value={value ?? ""}
            onChange={(e) => set(e.target.value)}
            {...props}
          />
          <button
            type="button"
            onClick={onToggleVisibility}
            aria-label={visible ? "Hide password" : "Show password"}
          >
            {visible ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
      ) : (
        <input
          type={type}
          value={value ?? ""}
          onChange={(e) => set(e.target.value)}
          {...props}
        />
      )}
    </label>
  );
}
function Stat({ title, value, icon: Icon }) {
  return (
    <div className="stat">
      <div className="stat-label">
        <small>{title}</small>
        {Icon && <Icon size={16} />}
      </div>
      <strong>{value ?? 0}</strong>
    </div>
  );
}
function BankAdminActions({ row, banks, run }) {
  const [dialog, setDialog] = useState("");
  const [form, setForm] = useState({
    full_name: row.full_name,
    email: row.email,
    bank_id: String(row.bank_id),
  });
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState("");
  const accepted = row.kind === "account";
  const names = {
    suspend: row.active ? "Suspend Bank Admin" : "Reactivate Bank Admin",
    resend: "Resend Invitation",
    revoke: "Revoke Invitation",
    delete: "Delete Invitation",
  };
  function edit(e) {
    e.preventDefault();
    setProblem("");
    if (
      form.full_name.trim().length < 2 ||
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())
    )
      return setProblem("Enter a valid name and email address.");
    if (
      !accepted &&
      !banks.some(
        (b) => String(b.id) === form.bank_id && b.status === "APPROVED",
      )
    )
      return setProblem("Select an approved bank.");
    if (reason.trim().length < 8)
      return setProblem("Enter a reason of at least 8 characters.");
    const url = accepted
      ? `/admin/bank-admins/${row.id}`
      : `/admin/bank-invitations/${row.id}`;
    run(
      async () => {
        await adminApi(url, {
          method: "PATCH",
          body: JSON.stringify({
            full_name: form.full_name.trim(),
            email: form.email.trim(),
            reason: reason.trim(),
            ...(accepted ? {} : { bank_id: Number(form.bank_id) }),
          }),
        });
        setDialog("");
      },
      accepted
        ? "Bank Admin details updated."
        : "Invitation updated and email delivery confirmed.",
    );
  }
  function action(e) {
    e.preventDefault();
    if (reason.trim().length < 8)
      return setProblem("Enter a reason of at least 8 characters.");
    const opts = accepted
      ? {
          method: "PATCH",
          body: JSON.stringify({ active: !row.active, reason: reason.trim() }),
        }
      : dialog === "resend"
        ? { method: "POST", body: JSON.stringify({ reason: reason.trim() }) }
        : dialog === "revoke"
          ? {
              method: "POST",
              body: JSON.stringify({ active: false, reason: reason.trim() }),
            }
          : {
              method: "DELETE",
              body: JSON.stringify({ reason: reason.trim() }),
            };
    const base = accepted
      ? `/admin/bank-admins/${row.id}/status`
      : `/admin/bank-invitations/${row.id}`;
    const url =
      dialog === "resend"
        ? base + "/resend"
        : dialog === "revoke"
          ? base + "/revoke"
          : base;
    run(
      async () => {
        await adminApi(url, opts);
        setDialog("");
      },
      dialog === "resend"
        ? "Invitation resent; email delivery confirmed."
        : dialog === "revoke"
          ? "Invitation revoked."
          : dialog === "delete"
            ? "Invitation deleted."
            : row.active
              ? "Bank Admin suspended."
              : "Bank Admin reactivated.",
    );
  }
  function open(which) {
    setReason("");
    setProblem("");
    setForm({
      full_name: row.full_name,
      email: row.email,
      bank_id: String(row.bank_id),
    });
    setDialog(which);
  }
  return (
    <>
      <div className="bank-admin-actions">
        <button className="secondary small" onClick={() => open("edit")}>
          Edit
        </button>
        {accepted ? (
          <button className="secondary small" onClick={() => open("suspend")}>
            {row.active ? "Suspend" : "Reactivate"}
          </button>
        ) : (
          <>
            {row.invitation_status !== "revoked" && (
              <button
                className="secondary small"
                onClick={() => open("resend")}
              >
                Resend Invitation
              </button>
            )}
            {row.invitation_status === "pending" && (
              <button
                className="secondary small"
                onClick={() => open("revoke")}
              >
                Revoke Invitation
              </button>
            )}
            <button
              className="secondary small danger-action"
              onClick={() => open("delete")}
            >
              Delete
            </button>
          </>
        )}
      </div>
      {dialog && (
        <div
          className="admin-dialog-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setDialog("");
          }}
        >
          <section
            className="admin-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby={"dialog-" + row.kind + row.id}
          >
            <div className="admin-dialog-head">
              <h2 id={"dialog-" + row.kind + row.id}>
                {dialog === "edit" ? "Edit Bank Admin" : names[dialog]}
              </h2>
              <button
                type="button"
                className="dialog-close"
                onClick={() => setDialog("")}
                aria-label="Close"
              >
                Close
              </button>
            </div>
            <p className="dialog-target">
              <b>{row.full_name}</b>
              <span>{row.email}</span>
              <small>
                {row.bank_name} | {row.invitation_status}
              </small>
            </p>
            {dialog === "edit" ? (
              <form className="admin-dialog-form" onSubmit={edit}>
                <label className="field">
                  <span>Full name</span>
                  <input
                    value={form.full_name}
                    onChange={(e) =>
                      setForm({ ...form, full_name: e.target.value })
                    }
                    required
                    minLength={2}
                  />
                </label>
                <label className="field">
                  <span>Official email</span>
                  <input
                    type="email"
                    value={form.email}
                    onChange={(e) =>
                      setForm({ ...form, email: e.target.value })
                    }
                    required
                  />
                </label>
                <label className="field">
                  <span>
                    Associated bank{accepted ? " (ownership fixed)" : ""}
                  </span>
                  {accepted ? (
                    <input value={row.bank_name} disabled />
                  ) : (
                    <select
                      value={form.bank_id}
                      onChange={(e) =>
                        setForm({ ...form, bank_id: e.target.value })
                      }
                      required
                    >
                      <option value="">Select approved bank</option>
                      {banks
                        .filter((b) => b.status === "APPROVED")
                        .map((b) => (
                          <option key={b.id} value={b.id}>
                            {b.name}
                          </option>
                        ))}
                    </select>
                  )}
                </label>
                <label className="field">
                  <span>Reason</span>
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    minLength={8}
                    required
                  />
                </label>
                {problem && <p className="field-error">{problem}</p>}
                <div className="dialog-actions">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setDialog("")}
                  >
                    Cancel
                  </button>
                  <button className="primary">
                    {accepted ? "Save changes" : "Save & resend invitation"}
                  </button>
                </div>
              </form>
            ) : (
              <form className="admin-dialog-form" onSubmit={action}>
                <p>
                  Confirm <b>{names[dialog]}</b> for <b>{row.full_name}</b> (
                  {row.email})?
                </p>
                {dialog !== "resend" && (
                  <p>This action will be recorded in the audit history.</p>
                )}
                <label className="field">
                  <span>Reason</span>
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    minLength={8}
                    required
                  />
                </label>
                {problem && <p className="field-error">{problem}</p>}
                <div className="dialog-actions">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setDialog("")}
                  >
                    Cancel
                  </button>
                  <button
                    className={
                      dialog === "delete" ? "danger-button" : "primary"
                    }
                  >
                    {names[dialog]}
                  </button>
                </div>
              </form>
            )}
          </section>
        </div>
      )}
    </>
  );
}

function Config({ label, value }) {
  return (
    <div className="config-item">
      <small>{label}</small>
      <b>{String(value ?? "—")}</b>
    </div>
  );
}
