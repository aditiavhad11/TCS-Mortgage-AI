import "./admin.css";
import { useEffect, useState } from "react";
import BankRegistration from "./BankRegistration";
import BankOverview from "./BankOverview";
import PasswordRecoveryForm from "./PasswordRecoveryForm";
import {
  Building2,
  ClipboardList,
  Users,
  LogOut,
  RefreshCw,
  ShieldCheck,
  Eye,
  EyeOff,
} from "lucide-react";
import { notifyError, notifySuccess } from "./ToastProvider";
const API = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1"
).replace(/\/$/, "");
async function call(path, opts = {}) {
  const h = new Headers(opts.headers || {});
  const t = localStorage.getItem("mortgage_bank_admin_token");
  if (t) h.set("Authorization", `Bearer ${t}`);
  if (opts.body && !(opts.body instanceof FormData))
    h.set("Content-Type", "application/json");
  const r = await fetch(`${API}${path}`, { ...opts, headers: h });
  const b = await r.json().catch(() => ({ detail: "Invalid server response" }));
  if (!r.ok) {
    const detail = b.detail || `Request failed (${r.status})`;
    if (
      t &&
      (r.status === 401 ||
        (r.status === 403 &&
          [
            "Bank Admin role required.",
            "Your bank is not approved or is inactive.",
          ].includes(detail)))
    ) {
      localStorage.removeItem("mortgage_bank_admin_token");
      localStorage.removeItem("mortgage_bank_admin");
      window.dispatchEvent(
        new CustomEvent("bank-admin-auth-failure", { detail }),
      );
    }
    throw Error(detail);
  }
  return b;
}

function uploadPolicyPdf(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);
    xhr.open("POST", `${API}/bank-admin/policies/extract`);
    const token = localStorage.getItem("mortgage_bank_admin_token");
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable)
        onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onerror = () =>
      reject(Error("PDF upload failed. Check your connection and retry."));
    xhr.onload = () => {
      let body = {};
      try {
        body = JSON.parse(xhr.responseText || "{}");
      } catch {}
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else
        reject(Error(body.detail || `PDF extraction failed (${xhr.status}).`));
    };
    xhr.send(form);
  });
}

async function downloadPolicyPdf(policy) {
  const token = localStorage.getItem("mortgage_bank_admin_token");
  const response = await fetch(`${API}/bank-admin/policies/${policy.id}/file`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw Error(body.detail || `Download failed (${response.status})`);
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = policy.source_filename || "policy.pdf";
  link.click();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 2000);
}

function BankReviewerDirectory({
  rows,
  busy,
  onRefresh,
  onView,
  summary,
  summaryError,
}) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [specialisation, setSpecialisation] = useState("all");
  const [availability, setAvailability] = useState("all");
  const [sort, setSort] = useState("name");
  const [page, setPage] = useState(0);
  const size = 10;
  const specs = [...new Set(rows.map((r) => r.specialisation).filter(Boolean))];
  const filtered = rows.filter(
    (r) =>
      (!q ||
        `${r.full_name} ${r.email}`
          .toLowerCase()
          .includes(q.trim().toLowerCase())) &&
      (status === "all" || status === r.account_status) &&
      (specialisation === "all" || r.specialisation === specialisation) &&
      (availability === "all" ||
        (availability === "eligible" && r.eligible) ||
        (availability === "ineligible" && !r.eligible)),
  );
  const sorted = [...filtered].sort((a, b) =>
    sort === "workload"
      ? b.active_assignments / (b.max_active_assignments || 1) -
        a.active_assignments / (a.max_active_assignments || 1)
      : sort === "created"
        ? new Date(b.created_at || 0) - new Date(a.created_at || 0)
        : a.full_name.localeCompare(b.full_name),
  );
  const pages = Math.max(1, Math.ceil(sorted.length / size));
  const showing = sorted.slice(page * size, (page + 1) * size);
  const title = (s) =>
    s
      .replaceAll("_", " ")
      .toLowerCase()
      .replace(/\b\w/g, (c) => c.toUpperCase());
  return (
    <div className="reviewer-operations">
      {summaryError ? (
        <section className="reviewer-summary-error" role="alert">
          Reviewer metrics could not be loaded. Refresh the page to retry.
        </section>
      ) : summary ? (
        <div className="reviewer-metrics">
          <article>
            <small>Total reviewers</small>
            <b>{summary.total_reviewers}</b>
            <span>Activated accounts; pending invitations excluded</span>
          </article>
          <article>
            <small>Available assignment capacity</small>
            <b>{summary.available_assignment_capacity}</b>
            <span>Open slots across eligible reviewers</span>
          </article>
          <article>
            <small>Pending invitations</small>
            <b>{summary.pending_invitations}</b>
            <span>Valid, unused invitations</span>
          </article>
          <article>
            <small>Unavailable reviewers</small>
            <b>{summary.unavailable_reviewers}</b>
            <span>Deactivated, unavailable or at capacity</span>
          </article>
        </div>
      ) : (
        <div className="reviewer-metrics-loading">
          {busy
            ? "Loading reviewer metrics…"
            : "Reviewer metrics are unavailable."}
        </div>
      )}
      <section className="panel bank-reviewer-directory">
        <div className="bank-section-head">
          <div>
            <h2>Reviewer directory</h2>
            <p>
              Search and manage reviewers and their current assignment
              eligibility.
            </p>
          </div>
          <span className="bank-count">
            {sorted.length} of {rows.length} reviewers
          </span>
        </div>
        <div className="bank-toolbar reviewer-directory-toolbar">
          <input
            aria-label="Search reviewers"
            placeholder="Search by reviewer name or official email"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(0);
            }}
          />
          <select
            aria-label="Filter reviewer account status"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(0);
            }}
          >
            <option value="all">All account statuses</option>
            {[
              "ACTIVE",
              "DEACTIVATED",
              "INVITATION_PENDING",
              "INVITATION_EXPIRED",
              "INVITATION_REVOKED",
            ].map((x) => (
              <option key={x} value={x}>
                {title(x)}
              </option>
            ))}
          </select>
          <select
            aria-label="Filter specialization"
            value={specialisation}
            onChange={(e) => {
              setSpecialisation(e.target.value);
              setPage(0);
            }}
          >
            <option value="all">All specializations</option>
            {specs.map((x) => (
              <option key={x} value={x}>
                {title(x)}
              </option>
            ))}
          </select>
          <select
            aria-label="Filter assignment eligibility"
            value={availability}
            onChange={(e) => {
              setAvailability(e.target.value);
              setPage(0);
            }}
          >
            <option value="all">All workload states</option>
            <option value="eligible">Eligible for assignment</option>
            <option value="ineligible">Not currently eligible</option>
          </select>
          <select
            aria-label="Sort reviewers"
            value={sort}
            onChange={(e) => {
              setSort(e.target.value);
              setPage(0);
            }}
          >
            <option value="name">Sort by name</option>
            <option value="workload">Sort by workload</option>
            <option value="created">Sort by created date</option>
          </select>
          <button
            className="secondary small"
            onClick={() => {
              setQ("");
              setStatus("all");
              setSpecialisation("all");
              setAvailability("all");
              setSort("name");
              setPage(0);
            }}
          >
            Reset
          </button>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>REVIEWER</th>
                <th>OFFICIAL EMAIL</th>
                <th>SPECIALIZATION</th>
                <th>ACCOUNT STATUS</th>
                <th>ACTIVE / CAPACITY</th>
                <th>REMAINING</th>
                <th>ELIGIBILITY</th>
                <th>ACTIONS</th>
              </tr>
            </thead>
            <tbody>
              {showing.map((r) => (
                <tr key={r.id}>
                  <td>
                    <button
                      className="reviewer-name-link"
                      onClick={() => onView(r)}
                    >
                      <span className="reviewer-avatar">
                        {r.full_name
                          .split(/\s+/)
                          .map((x) => x[0])
                          .slice(0, 2)
                          .join("")
                          .toUpperCase()}
                      </span>
                      {r.full_name}
                    </button>
                  </td>
                  <td>{r.email}</td>
                  <td>{title(r.specialisation)}</td>
                  <td>
                    <span
                      className={`reviewer-account-badge status-${r.account_status.toLowerCase()}`}
                    >
                      {title(r.account_status)}
                    </span>
                  </td>
                  <td>
                    {r.active_assignments} / {r.max_active_assignments}
                  </td>
                  <td>{r.remaining_capacity}</td>
                  <td>
                    <span
                      className={`reviewer-eligibility ${r.eligible ? "is-eligible" : "is-ineligible"}`}
                    >
                      {r.eligibility_reason}
                    </span>
                    <div className="reviewer-workload-track">
                      <i
                        style={{
                          width: `${Math.min(100, r.max_active_assignments ? (100 * r.active_assignments) / r.max_active_assignments : 0)}%`,
                        }}
                      />
                    </div>
                  </td>
                  <td>
                    <BankReviewerActions
                      row={r}
                      onRefresh={onRefresh}
                      busy={busy}
                    />
                  </td>
                </tr>
              ))}
              {!showing.length && (
                <tr>
                  <td colSpan="8" className="bank-empty">
                    {busy
                      ? "Loading reviewers…"
                      : rows.length
                        ? "No reviewers match these filters."
                        : "No reviewers are registered yet. Use Invite Reviewer to securely provision a bank reviewer."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="bank-pagination">
          <span>
            Page {page + 1} of {pages}
          </span>
          <button
            className="secondary small"
            disabled={!page}
            onClick={() => setPage(page - 1)}
          >
            Previous
          </button>
          <button
            className="secondary small"
            disabled={page + 1 >= pages}
            onClick={() => setPage(page + 1)}
          >
            Next
          </button>
        </div>
      </section>
    </div>
  );
}
function BankReviewerActions({ row, onRefresh, busy }) {
  const [mode, setMode] = useState("");
  const [form, setForm] = useState({
    full_name: row.full_name,
    email: row.email,
    specialisation: row.specialisation,
    max_active_assignments: row.max_active_assignments,
    reason: "",
  });
  const [err, setErr] = useState("");
  async function save(e) {
    e.preventDefault();
    setErr("");
    if (form.reason.trim().length < 8)
      return setErr("Enter a reason with at least 8 characters.");
    try {
      await call(`/bank-admin/reviewers/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          ...form,
          full_name: form.full_name.trim(),
          email: form.email.trim(),
          reason: form.reason.trim(),
        }),
      });
      setMode("");
      await onRefresh("Reviewer details updated.");
    } catch {
      notifyError();
    }
  }
  async function toggle() {
    setErr("");
    if (form.reason.trim().length < 8)
      return setErr("Enter a reason with at least 8 characters.");
    try {
      await call(
        `/bank-admin/reviewers/${row.id}/active?active=${!row.is_active}&reason=${encodeURIComponent(form.reason.trim())}`,
        { method: "PATCH" },
      );
      setMode("");
      await onRefresh(
        row.is_active
          ? "Reviewer deactivated. Open assignments were released for automatic reassignment."
          : "Reviewer reactivated. Waiting applications were retried.",
      );
    } catch {
      notifyError();
    }
  }
  async function invitation(action) {
    setErr("");
    if (
      !window.confirm(
        `${action === "resend" ? "Resend" : "Revoke"} the invitation for ${row.email}?`,
      )
    )
      return;
    try {
      const result = await call(
        `/bank-admin/reviewers/${row.id}/${action}-invitation`,
        { method: "POST" },
      );
      setMode("");
      await onRefresh(
        action === "resend"
          ? `Invitation sent to ${row.email}. It expires ${new Date(result.invitation_expires_at).toLocaleString()}.`
          : "Invitation revoked. The reviewer cannot activate this account.",
      );
    } catch {
      notifyError();
    }
  }
  return (
    <>
      <div className="bank-reviewer-actions">
        <button
          className="secondary small"
          onClick={() => {
            setErr("");
            setMode("view");
          }}
        >
          View
        </button>
        <button
          className="secondary small"
          onClick={() => {
            setForm({
              full_name: row.full_name,
              email: row.email,
              specialisation: row.specialisation,
              max_active_assignments: row.max_active_assignments,
              reason: "",
            });
            setMode("edit");
          }}
        >
          Edit
        </button>
        {[
          "INVITATION_PENDING",
          "INVITATION_EXPIRED",
          "INVITATION_REVOKED",
        ].includes(row.account_status) && (
          <button
            className="secondary small"
            disabled={busy}
            onClick={() => invitation("resend")}
          >
            Resend invite
          </button>
        )}
        {["INVITATION_PENDING", "INVITATION_EXPIRED"].includes(
          row.account_status,
        ) && (
          <button
            className="secondary small danger-action"
            disabled={busy}
            onClick={() => invitation("revoke")}
          >
            Revoke
          </button>
        )}
        {["ACTIVE", "DEACTIVATED"].includes(row.account_status) && (
          <button
            className="secondary small"
            disabled={busy}
            onClick={() => {
              setErr("");
              setForm({ ...form, reason: "" });
              setMode("toggle");
            }}
          >
            {row.is_active ? "Deactivate" : "Reactivate"}
          </button>
        )}
      </div>
      {mode && mode !== "view" && (
        <div
          className="bank-modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setMode("");
          }}
        >
          <section
            className="bank-modal reviewer-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby={`reviewer-dialog-${row.id}`}
          >
            <div className="bank-section-head">
              <div>
                <h2 id={`reviewer-dialog-${row.id}`}>
                  {mode === "edit"
                    ? "Edit reviewer"
                    : mode === "toggle"
                      ? "Confirm reviewer status change"
                      : "Confirm reviewer action"}
                </h2>
                <p>
                  {row.full_name} · {row.email}
                </p>
              </div>
              <button className="secondary small" onClick={() => setMode("")}>
                Close
              </button>
            </div>
            {mode === "edit" ? (
              <form className="fields" onSubmit={save}>
                <label className="field">
                  <span>Full name</span>
                  <input
                    placeholder="Enter reviewer full name"
                    required
                    minLength="2"
                    maxLength="160"
                    value={form.full_name}
                    onChange={(e) =>
                      setForm({ ...form, full_name: e.target.value })
                    }
                  />
                </label>
                <label className="field">
                  <span>Official email</span>
                  <input
                    type="email"
                    placeholder="reviewer@yourbank.com"
                    required
                    value={form.email}
                    onChange={(e) =>
                      setForm({ ...form, email: e.target.value })
                    }
                  />
                </label>
                <label className="field">
                  <span>Specialization</span>
                  <select
                    value={form.specialisation}
                    onChange={(e) =>
                      setForm({ ...form, specialisation: e.target.value })
                    }
                  >
                    <option value="GENERAL_MORTGAGE_REVIEW">
                      General Mortgage Review
                    </option>
                    <option value="INCOME_TAX">Income &amp; Tax</option>
                    <option value="PROPERTY_VALUATION">
                      Property Valuation
                    </option>
                    <option value="TERMS_CONDITIONS">
                      Terms &amp; Conditions
                    </option>
                  </select>
                </label>
                <label className="field">
                  <span>
                    Maximum active assignments (current {row.active_assignments}
                    )
                  </span>
                  <input
                    type="number"
                    placeholder="Enter assignment limit"
                    min={Math.max(1, row.active_assignments)}
                    max="100"
                    required
                    value={form.max_active_assignments}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        max_active_assignments: Number(e.target.value),
                      })
                    }
                  />
                </label>
                <label className="field full">
                  <span>Reason for change</span>
                  <textarea
                    placeholder="Explain why this reviewer change is needed"
                    required
                    minLength="8"
                    value={form.reason}
                    onChange={(e) =>
                      setForm({ ...form, reason: e.target.value })
                    }
                  />
                </label>
                {err && <p className="inline-error">{err}</p>}
                <button className="primary" disabled={busy}>
                  Save reviewer
                </button>
              </form>
            ) : (
              <div className="reviewer-confirm">
                <p>
                  {row.is_active
                    ? "Open assignments will be released for automatic reassignment."
                    : "Activation is allowed only for a previously activated reviewer."}
                </p>
                <label className="field">
                  <span>
                    Reason <b className="required-mark">*</b>
                  </span>
                  <textarea
                    placeholder="Enter a reason for this status change"
                    minLength="8"
                    required
                    value={form.reason}
                    onChange={(e) =>
                      setForm({ ...form, reason: e.target.value })
                    }
                  />
                </label>
                {err && <p className="inline-error">{err}</p>}
                <div className="dialog-actions">
                  <button className="secondary" onClick={() => setMode("")}>
                    Cancel
                  </button>
                  <button className="primary" disabled={busy} onClick={toggle}>
                    Confirm
                  </button>
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}
function BankReviewerProfile({ reviewer, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  useEffect(() => {
    let live = true;
    call(`/bank-admin/reviewers/${reviewer.id}`)
      .then((r) => {
        if (live) setData(r);
      })
      .catch(() => {
        if (live) notifyError();
      })
      .finally(() => {
        if (live) setBusy(false);
      });
    return () => {
      live = false;
    };
  }, [reviewer.id]);
  if (!reviewer) return null;
  return (
    <div
      className="bank-modal-backdrop reviewer-profile-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className="bank-modal reviewer-profile-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="reviewer-profile-heading"
      >
        <div className="bank-section-head">
          <div>
            <h2 id="reviewer-profile-heading">Reviewer profile</h2>
            <p>
              {reviewer.full_name} · {reviewer.email}
            </p>
          </div>
          <button className="secondary small" onClick={onClose}>
            Close
          </button>
        </div>
        {busy ? (
          <p className="bank-empty">Loading reviewer profile…</p>
        ) : error ? (
          <p className="inline-error" role="alert">
            {error}
          </p>
        ) : (
          data && (
            <>
              <div className="reviewer-profile-sections">
                <section>
                  <h3>Profile</h3>
                  <dl>
                    <dt>Bank</dt>
                    <dd>
                      {data.profile.bank_name} ({data.profile.bank_code})
                    </dd>
                    <dt>Specialization</dt>
                    <dd>{data.profile.specialisation.replaceAll("_", " ")}</dd>
                    <dt>Account status</dt>
                    <dd>{data.profile.account_status.replaceAll("_", " ")}</dd>
                    <dt>Eligibility</dt>
                    <dd>{data.profile.eligibility_reason}</dd>
                    <dt>Invited</dt>
                    <dd>
                      {data.profile.invited_at
                        ? new Date(data.profile.invited_at).toLocaleString()
                        : "Not recorded"}
                    </dd>
                    <dt>Activated</dt>
                    <dd>
                      {data.profile.activated_at
                        ? new Date(data.profile.activated_at).toLocaleString()
                        : "Not activated"}
                    </dd>
                  </dl>
                </section>
                <section>
                  <h3>Workload and capacity</h3>
                  <div className="reviewer-capacity">
                    <b>
                      {data.workload.active_assignments} /{" "}
                      {data.workload.max_active_assignments}
                    </b>
                    <span>
                      {data.workload.remaining_capacity} remaining slots
                    </span>
                    <div className="reviewer-workload-track">
                      <i
                        style={{
                          width: `${Math.min(100, data.workload.max_active_assignments ? (100 * data.workload.active_assignments) / data.workload.max_active_assignments : 0)}%`,
                        }}
                      />
                    </div>
                  </div>
                  <h3>Review activity</h3>
                  <p className="reviewer-analytics-note">
                    {data.analytics.note}
                  </p>
                  <div className="reviewer-activity-count">
                    <b>{data.analytics.completed_reviews}</b>
                    <span>Recorded completed reviews</span>
                  </div>
                </section>
              </div>
              <section className="reviewer-profile-list">
                <h3>Assigned applications</h3>
                {data.assigned_applications.length ? (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>REFERENCE</th>
                          <th>PRODUCT</th>
                          <th>STATUS</th>
                          <th>ASSIGNED</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.assigned_applications.map((a) => (
                          <tr key={a.id}>
                            <td>{a.reference}</td>
                            <td>{a.product_name || "Not provided"}</td>
                            <td>{a.status}</td>
                            <td>
                              {a.assigned_at
                                ? new Date(a.assigned_at).toLocaleString()
                                : "Unavailable"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="bank-empty">
                    No current applications are assigned.
                  </p>
                )}
              </section>
              <section className="reviewer-profile-list">
                <h3>Review history</h3>
                {data.review_history.length ? (
                  <div className="reviewer-profile-events">
                    {data.review_history.map((e) => (
                      <article key={e.id}>
                        <b>{e.event_type.replaceAll("_", " ")}</b>
                        <span>
                          {e.application_reference} · {e.application_status}
                        </span>
                        <small>{new Date(e.created_at).toLocaleString()}</small>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="bank-empty">
                    Not enough historical review activity is recorded.
                  </p>
                )}
              </section>
              <section className="reviewer-profile-list">
                <h3>Administrative activity</h3>
                {data.administrative_activity.length ? (
                  <div className="reviewer-profile-events">
                    {data.administrative_activity.map((e, i) => (
                      <article key={`${e.action}-${i}`}>
                        <b>{e.action.replaceAll("_", " ")}</b>
                        <span>{e.detail}</span>
                        <small>
                          {e.actor} · {new Date(e.created_at).toLocaleString()}
                        </small>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="bank-empty">
                    No reviewer administration events have been recorded.
                  </p>
                )}
              </section>
            </>
          )
        )}
      </section>
    </div>
  );
}
function BankApplications({ apps, onRefresh }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [reviewer, setReviewer] = useState("all");
  const [archiveView, setArchiveView] = useState("active");
  const [archiveReason, setArchiveReason] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState(null);
  const [events, setEvents] = useState([]);
  const size = 10;
  const terminal = [
    "APPROVED",
    "CANCELLED",
    "CLOSED",
    "COMPLETED",
    "DECLINED",
    "REJECTED",
    "WITHDRAWN",
  ];
  const reviewerList = [
    ...new Set(apps.map((a) => a.reviewer_name).filter(Boolean)),
  ];
  const filtered = apps
    .filter(
      (a) =>
        (!q ||
          [a.reference, a.customer_name, a.product_name, a.lender_name].some(
            (v) =>
              String(v || "")
                .toLowerCase()
                .includes(q.trim().toLowerCase()),
          )) &&
        (status === "all" || a.status === status) &&
        (reviewer === "all" || a.reviewer_name === reviewer) &&
        (archiveView === "all" ||
          (archiveView === "archived" ? !!a.archived_at : !a.archived_at)) &&
        (!from ||
          String(a.submitted_at || a.created_at || "").slice(0, 10) >= from) &&
        (!to ||
          String(a.submitted_at || a.created_at || "").slice(0, 10) <= to),
    )
    .sort(
      (a, b) =>
        new Date(b.submitted_at || b.created_at) -
        new Date(a.submitted_at || a.created_at),
    );
  const pages = Math.max(1, Math.ceil(filtered.length / size));
  async function show(a) {
    setSelected(a);
    setArchiveReason("");
    setActionError("");
    setEvents([]);
    try {
      setEvents(
        await call(
          `/bank-admin/assignment-history?application_id=${a.id}&limit=50`,
        ),
      );
    } catch {
      setEvents([]);
    }
  }
  async function archive(restore = false) {
    if (!selected) return;
    if (archiveReason.trim().length < 8) {
      setActionError("Enter a reason of at least 8 characters.");
      return;
    }
    const action = restore ? "restore" : "archive";
    if (
      !window.confirm(
        `${restore ? "Restore" : "Archive"} application ${selected.reference}? The record, documents and assignment history will be retained.`,
      )
    )
      return;
    setActionBusy(true);
    setActionError("");
    try {
      await call(`/bank-admin/applications/${selected.id}/${action}`, {
        method: "POST",
        body: JSON.stringify({ reason: archiveReason.trim() }),
      });
      await onRefresh();
      setSelected(null);
    } catch {
      notifyError();
    } finally {
      setActionBusy(false);
    }
  }
  return (
    <section className="panel bank-ops">
      <div className="bank-section-head">
        <div>
          <h2>Applications for your bank</h2>
          <p>
            Submitted applications remain in the system for customer, regulatory
            and audit traceability.
          </p>
        </div>
      </div>
      <div className="bank-toolbar">
        <input
          aria-label="Search applications"
          placeholder="Search reference, customer or product"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(0);
          }}
        />
        <select
          aria-label="Filter application status"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(0);
          }}
        >
          <option value="all">All statuses</option>
          {[...new Set(apps.map((a) => a.status))].map((x) => (
            <option key={x} value={x}>
              {x === "PENDING_ASSIGNMENT"
                ? "Awaiting reviewer assignment"
                : x.replaceAll("_", " ")}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter reviewer"
          value={reviewer}
          onChange={(e) => {
            setReviewer(e.target.value);
            setPage(0);
          }}
        >
          <option value="all">All reviewers</option>
          {reviewerList.map((x) => (
            <option key={x}>{x}</option>
          ))}
        </select>
        <select
          aria-label="Filter archive state"
          value={archiveView}
          onChange={(e) => {
            setArchiveView(e.target.value);
            setPage(0);
          }}
        >
          <option value="active">Active records</option>
          <option value="archived">Archived records</option>
          <option value="all">All records</option>
        </select>
        <label className="bank-date-filter">
          Submitted from
          <input
            aria-label="Submitted from"
            type="date"
            value={from}
            onChange={(e) => {
              setFrom(e.target.value);
              setPage(0);
            }}
          />
        </label>
        <label className="bank-date-filter">
          Submitted to
          <input
            aria-label="Submitted to"
            type="date"
            value={to}
            onChange={(e) => {
              setTo(e.target.value);
              setPage(0);
            }}
          />
        </label>
        <span>{filtered.length} applications</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>REFERENCE</th>
              <th>CUSTOMER</th>
              <th>PRODUCT</th>
              <th>REQUESTED LOAN</th>
              <th>STATUS</th>
              <th>REVIEWER</th>
              <th>SUBMITTED</th>
              <th>UPDATED</th>
              <th>PENDING ACTION</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(page * size, (page + 1) * size).map((a) => (
              <tr key={a.id}>
                <td>
                  <b>{a.reference}</b>
                </td>
                <td>{a.customer_name}</td>
                <td>{a.product_name || "?"}</td>
                <td>
                  {new Intl.NumberFormat("en-IN", {
                    style: "currency",
                    currency: "INR",
                    maximumFractionDigits: 0,
                  }).format(a.requested_loan || 0)}
                </td>
                <td>
                  <span className="bank-state">
                    {a.archived_at ? "Archived ? " : ""}
                    {a.status_label || a.status.replaceAll("_", " ")}
                  </span>
                </td>
                <td>{a.reviewer_name || "Awaiting assignment"}</td>
                <td>
                  {a.submitted_at
                    ? new Date(a.submitted_at).toLocaleDateString()
                    : "?"}
                </td>
                <td>
                  {a.updated_at
                    ? new Date(a.updated_at).toLocaleDateString()
                    : "?"}
                </td>
                <td>
                  {a.outstanding_action === "?" ? "?" : a.outstanding_action}
                </td>
                <td>
                  <button className="secondary small" onClick={() => show(a)}>
                    View details
                  </button>
                </td>
              </tr>
            ))}
            {!filtered.length && (
              <tr>
                <td colSpan="10" className="bank-empty">
                  {apps.length
                    ? "No applications match the selected filters."
                    : "No bank applications found."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="bank-pagination">
        <span>
          Page {page + 1} of {pages}
        </span>
        <button
          className="secondary small"
          disabled={page === 0}
          onClick={() => setPage(page - 1)}
        >
          Previous
        </button>
        <button
          className="secondary small"
          disabled={page + 1 >= pages}
          onClick={() => setPage(page + 1)}
        >
          Next
        </button>
      </div>
      {selected && (
        <div
          className="bank-modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setSelected(null);
          }}
        >
          <section
            className="bank-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="application-dialog-title"
          >
            <div className="bank-section-head">
              <div>
                <h2 id="application-dialog-title">
                  Application {selected.reference}
                </h2>
                <p>Details are read-only in the bank operations workspace.</p>
              </div>
              <button
                className="secondary small"
                onClick={() => setSelected(null)}
              >
                Close
              </button>
            </div>
            <div className="bank-detail-grid">
              <div>
                <small>Customer</small>
                <b>{selected.customer_name}</b>
              </div>
              <div>
                <small>Product</small>
                <b>{selected.product_name || "Not provided"}</b>
              </div>
              <div>
                <small>Requested loan</small>
                <b>
                  {new Intl.NumberFormat("en-IN", {
                    style: "currency",
                    currency: "INR",
                    maximumFractionDigits: 0,
                  }).format(selected.requested_loan || 0)}
                </b>
              </div>
              <div>
                <small>Property value</small>
                <b>
                  {new Intl.NumberFormat("en-IN", {
                    style: "currency",
                    currency: "INR",
                    maximumFractionDigits: 0,
                  }).format(selected.property_value || 0)}
                </b>
              </div>
              <div>
                <small>Status</small>
                <b>{selected.status_label || selected.status}</b>
              </div>
              <div>
                <small>Pending action</small>
                <b>{selected.outstanding_action || "?"}</b>
              </div>
              <div>
                <small>Submitted</small>
                <b>
                  {selected.submitted_at
                    ? new Date(selected.submitted_at).toLocaleString()
                    : "Unavailable"}
                </b>
              </div>
              <div>
                <small>Last updated</small>
                <b>
                  {selected.updated_at
                    ? new Date(selected.updated_at).toLocaleString()
                    : "Unavailable"}
                </b>
              </div>
              <div>
                <small>Assigned reviewer</small>
                <b>
                  {selected.reviewer_name || "Awaiting automatic assignment"}
                </b>
              </div>
              <div>
                <small>Assignment attempts</small>
                <b>{selected.assignment_attempts}</b>
              </div>
            </div>
            <h3>Document inventory and processing</h3>
            {selected.document_summary?.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>DOCUMENT</th>
                      <th>FILE</th>
                      <th>OCR</th>
                      <th>VERIFICATION</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selected.document_summary.map((d, i) => (
                      <tr key={`${d.category}-${i}`}>
                        <td>{d.category}</td>
                        <td>{d.filename}</td>
                        <td>{d.extraction_status}</td>
                        <td>{d.verification_status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="bank-empty">No document records are attached.</p>
            )}
            <h3>Assignment history</h3>
            {events.length ? (
              <div className="bank-event-list">
                {events.map((e) => (
                  <p key={e.id}>
                    <b>{e.event_type.replaceAll("_", " ").toLowerCase()}</b>
                    <span>
                      {e.reference} ? {new Date(e.created_at).toLocaleString()}
                    </span>
                    <small>{e.reason}</small>
                  </p>
                ))}
              </div>
            ) : (
              <p className="bank-empty">
                No assignment events recorded for this application.
              </p>
            )}
            <p className="bank-workflow-note">
              Submitted applications are retained. Only terminal applications
              without an active reviewer assignment can be archived; this
              preserves linked records and audit history.
            </p>
            {selected.archived_at ||
            (terminal.includes(selected.status) &&
              !selected.has_active_assignment) ? (
              <>
                <label className="field archive-reason-field">
                  <span>
                    {selected.archived_at
                      ? "Reason for restoring"
                      : "Reason for archiving"}{" "}
                    <b className="required-mark">*</b>
                  </span>
                  <textarea
                    placeholder="Explain why this terminal application should be archived"
                    minLength={8}
                    value={archiveReason}
                    onChange={(e) => setArchiveReason(e.target.value)}
                  />
                </label>
                {actionError && <p className="inline-error">{actionError}</p>}
                <button
                  className="secondary small"
                  disabled={actionBusy}
                  onClick={() => archive(!!selected.archived_at)}
                >
                  {actionBusy
                    ? "Saving..."
                    : selected.archived_at
                      ? "Restore application"
                      : "Archive application"}
                </button>
              </>
            ) : (
              <p className="bank-workflow-note">
                Archiving requires a terminal workflow status and no active
                reviewer assignment.
              </p>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
function BankHistory({ rows }) {
  const [q, setQ] = useState("");
  const [type, setType] = useState("all");
  const [reviewer, setReviewer] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(0);
  const size = 15;
  const types = [...new Set(rows.map((x) => x.event_type))];
  const reviewers = [
    ...new Set(rows.map((x) => x.reviewer_name).filter(Boolean)),
  ];
  const filtered = rows.filter(
    (x) =>
      (type === "all" || type === x.event_type) &&
      (reviewer === "all" || reviewer === x.reviewer_name) &&
      (!from || String(x.created_at || "").slice(0, 10) >= from) &&
      (!to || String(x.created_at || "").slice(0, 10) <= to) &&
      (!q ||
        `${x.reference || ""} ${x.reason || ""} ${x.reviewer_name || ""}`
          .toLowerCase()
          .includes(q.trim().toLowerCase())),
  );
  const pages = Math.max(1, Math.ceil(filtered.length / size));
  function exportCsv() {
    const headers = [
      "timestamp",
      "application_reference",
      "event_type",
      "reviewer",
      "detail",
    ];
    const escape = (value) => {
      let cell = String(value ?? "");
      if (/^[=+@\-\t\r]/.test(cell)) cell = "'" + cell;
      return '"' + cell.replaceAll('"', '""') + '"';
    };
    const content = [
      headers,
      ...filtered.map((x) => [
        x.created_at,
        x.reference,
        x.event_type,
        x.reviewer_name,
        x.reason,
      ]),
    ]
      .map((row) => row.map(escape).join(","))
      .join("\n");
    const url = URL.createObjectURL(
      new Blob([content], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "bank-assignment-history.csv";
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <section className="panel bank-ops">
      <div className="bank-section-head">
        <div>
          <h2>Assignment history</h2>
          <p>
            Immutable automatic assignment, retry and reassignment events for
            this bank.
          </p>
        </div>
      </div>
      <div className="bank-toolbar">
        <input
          aria-label="Search assignment history"
          placeholder="Search application, reviewer or detail"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(0);
          }}
        />
        <select
          value={type}
          onChange={(e) => {
            setType(e.target.value);
            setPage(0);
          }}
        >
          <option value="all">All event types</option>
          {types.map((x) => (
            <option key={x} value={x}>
              {x.replaceAll("_", " ").toLowerCase()}
            </option>
          ))}
        </select>
        <select
          value={reviewer}
          onChange={(e) => {
            setReviewer(e.target.value);
            setPage(0);
          }}
        >
          <option value="all">All reviewers</option>
          {reviewers.map((x) => (
            <option key={x}>{x}</option>
          ))}
        </select>
        <label className="bank-date-filter">
          From
          <input
            aria-label="Assignment event from"
            type="date"
            value={from}
            onChange={(e) => {
              setFrom(e.target.value);
              setPage(0);
            }}
          />
        </label>
        <label className="bank-date-filter">
          To
          <input
            aria-label="Assignment event to"
            type="date"
            value={to}
            onChange={(e) => {
              setTo(e.target.value);
              setPage(0);
            }}
          />
        </label>
        <span>{filtered.length} events</span>
        <button
          className="secondary small"
          onClick={exportCsv}
          disabled={!filtered.length}
        >
          Export CSV
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>TIME</th>
              <th>APPLICATION</th>
              <th>EVENT</th>
              <th>REVIEWER</th>
              <th>DETAIL</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(page * size, (page + 1) * size).map((e) => (
              <tr key={e.id}>
                <td>{new Date(e.created_at).toLocaleString()}</td>
                <td>{e.reference || "Unavailable"}</td>
                <td>
                  <span className="bank-state">
                    {e.event_type.replaceAll("_", " ").toLowerCase()}
                  </span>
                </td>
                <td>{e.reviewer_name || "?"}</td>
                <td>{e.reason || "No additional detail"}</td>
              </tr>
            ))}
            {!filtered.length && (
              <tr>
                <td colSpan="5" className="bank-empty">
                  {rows.length
                    ? "No events match these filters."
                    : "No assignment history recorded."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="bank-pagination">
        <span>
          Page {page + 1} of {pages}
        </span>
        <button
          className="secondary small"
          disabled={page === 0}
          onClick={() => setPage(page - 1)}
        >
          Previous
        </button>
        <button
          className="secondary small"
          disabled={page + 1 >= pages}
          onClick={() => setPage(page + 1)}
        >
          Next
        </button>
      </div>
      <p className="bank-workflow-note">
        Underlying assignment events are retained; this page does not offer
        deletion or a user-specific archive.
      </p>
    </section>
  );
}

export default function BankAdminPortal() {
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("mortgage_bank_admin") || "null");
    } catch {
      return null;
    }
  });
  const [form, setForm] = useState({ email: "", password: "" });
  const [authMode, setAuthMode] = useState(() =>
    new URLSearchParams(window.location.search).has("invite")
      ? "invite"
      : "login",
  );
  const [invite, setInvite] = useState({
    token: new URLSearchParams(window.location.search).get("invite") || "",
    password: "",
  });
  const [showPassword, setShowPassword] = useState(false);
  const [showInvitePassword, setShowInvitePassword] = useState(false);
  const [dash, setDash] = useState(null);
  const [apps, setApps] = useState([]);
  const [reviewers, setReviewers] = useState([]);
  const [reviewerSummary, setReviewerSummary] = useState(null);
  const [selectedReviewer, setSelectedReviewer] = useState(null);
  const [tab, setTab] = useState("overview");
  const [newReviewer, setNewReviewer] = useState({
    full_name: "",
    email: "",
    specialisation: "GENERAL_MORTGAGE_REVIEW",
    max_active_assignments: 10,
  });
  const [policies, setPolicies] = useState([]);
  const [policy, setPolicy] = useState({
    title: "",
    policy_version: "1.0",
    category: "Mortgage",
    content: "",
    active: true,
    customer_visible: false,
    customer_summary: "",
  });
  const [policyPdf, setPolicyPdf] = useState(null);
  const [policyExtraction, setPolicyExtraction] = useState(null);
  const [policyUploadProgress, setPolicyUploadProgress] = useState(0);
  const [policyUploading, setPolicyUploading] = useState(false);
  const [policyExtractError, setPolicyExtractError] = useState("");
  const [history, setHistory] = useState([]);
  const [notifications, setNotifications] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    setBusy(true);
    setError("");
    try {
      if (tab === "overview") setDash(await call("/bank-admin/dashboard"));
      if (tab === "applications")
        setApps(await call("/bank-admin/applications?include_archived=true"));
      if (tab === "reviewers") {
        const [reviewerRows, reviewerStats] = await Promise.all([
          call("/bank-admin/reviewers"),
          call("/bank-admin/reviewers/summary"),
        ]);
        setReviewers(reviewerRows);
        setReviewerSummary(reviewerStats);
      }
      if (tab === "history")
        setHistory(await call("/bank-admin/assignment-history?limit=500"));
      if (tab === "policies") setPolicies(await call("/bank-admin/policies"));
      if (tab === "notifications")
        setNotifications(await call("/bank-admin/notifications?limit=100"));
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }

  async function extractPolicyPdf(file, preserveContent = false) {
    if (!file) return;
    setPolicyPdf(file);
    setPolicyExtraction(null);
    setPolicyExtractError("");
    setPolicyUploadProgress(0);
    if (!preserveContent) setPolicy((prev) => ({ ...prev, content: "" }));
    setPolicyUploading(true);
    try {
      const result = await uploadPolicyPdf(file, setPolicyUploadProgress);
      setPolicyExtraction(result);
      if (result.extracted_text)
        setPolicy((prev) => ({
          ...prev,
          content:
            preserveContent && prev.content.trim()
              ? prev.content
              : result.extracted_text,
        }));
      if (result.extraction_status === "FAILED")
        setPolicyExtractError(
          result.extraction_message ||
            "Text extraction failed. Retry or enter policy text manually.",
        );
    } catch (e) {
      setPolicyExtractError(
        e.message || "PDF extraction failed. Retry the upload.",
      );
    } finally {
      setPolicyUploading(false);
    }
  }
  async function savePolicy(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (policyPdf && !policyExtraction?.extraction_digest)
        throw Error(
          "Complete PDF extraction or remove the selected PDF before saving.",
        );
      if (policyPdf && policyExtraction?.extraction_digest) {
        const formData = new FormData();
        for (const [key, value] of Object.entries(policy))
          formData.append(key, String(value));
        formData.append(
          "extraction_digest",
          policyExtraction.extraction_digest,
        );
        formData.append("file", policyPdf);
        await call("/bank-admin/policies/from-pdf", {
          method: "POST",
          body: formData,
        });
      } else {
        await call("/bank-admin/policies", {
          method: "POST",
          body: JSON.stringify(policy),
        });
      }
      setPolicy({
        title: "",
        policy_version: "1.0",
        category: "Mortgage",
        content: "",
        active: true,
        customer_visible: false,
        customer_summary: "",
      });
      setPolicyPdf(null);
      setPolicyExtraction(null);
      setPolicyUploadProgress(0);
      setPolicyExtractError("");
      notifySuccess("Bank policy saved.");
      await load();
    } catch (e) {
      setError(e.message || "Bank policy could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (user && localStorage.getItem("mortgage_bank_admin_token")) load();
  }, [user, tab]);
  useEffect(() => {
    if (
      !user ||
      !["overview", "applications", "history", "notifications"].includes(tab)
    )
      return;
    const id = setInterval(() => {
      if (!busy) load();
    }, 15000);
    return () => clearInterval(id);
  }, [user, tab, busy]);
  useEffect(() => {
    const onAuthFailure = () => setUser(null);
    window.addEventListener("bank-admin-auth-failure", onAuthFailure);
    return () =>
      window.removeEventListener("bank-admin-auth-failure", onAuthFailure);
  }, []);
  async function signIn(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (authMode === "invite") {
        const accepted = await call("/bank-admin/accept-invitation", {
          method: "POST",
          body: JSON.stringify(invite),
        });
        notifySuccess(
          "Invitation accepted. Sign in with your invited email and the password you just created.",
        );
        setAuthMode("login");
        setShowInvitePassword(false);
        setForm({
          email: accepted.email || form.email,
          password: invite.password,
        });
        window.history.replaceState({}, "", window.location.pathname);
        return;
      }
      const r = await call("/bank-admin/login", {
        method: "POST",
        body: JSON.stringify(form),
      });
      localStorage.setItem("mortgage_bank_admin_token", r.access_token);
      localStorage.setItem("mortgage_bank_admin", JSON.stringify(r.bank_admin));
      setUser(r.bank_admin);
      notifySuccess("Signed in successfully.");
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }
  function logout() {
    localStorage.removeItem("mortgage_bank_admin_token");
    localStorage.removeItem("mortgage_bank_admin");
    setUser(null);
  }
  async function createReviewer(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await call("/bank-admin/reviewers", {
        method: "POST",
        body: JSON.stringify(newReviewer),
      });
      setNewReviewer({
        full_name: "",
        email: "",
        specialisation: "GENERAL_MORTGAGE_REVIEW",
        max_active_assignments: 10,
      });
      notifySuccess("Reviewer invitation email sent.");
      await load();
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }
  const resetToken =
    new URLSearchParams(window.location.search).get("reset_token") || "";
  if (resetToken)
    return (
      <div className="password-recovery-page">
        <PasswordRecoveryForm
          accountType="BANK_ADMIN"
          title="Bank Admin password recovery"
          className="auth-form"
          initialToken={resetToken}
          onBack={() => {
            localStorage.removeItem("mortgage_bank_admin_token");
            localStorage.removeItem("mortgage_bank_admin");
            setUser(null);
            window.history.replaceState({}, "", window.location.pathname);
          }}
        />
      </div>
    );
  if (!user)
    return (
      <div className="auth">
        <div className="auth-side">
          <div className="brand">
            <span className="mark">M</span>
            <div>
              <b>Mortgage AI</b>
              <small>Bank administration</small>
            </div>
          </div>
          <div className="hero">
            <small>BANK OPERATIONS</small>
            <h1>
              Your bank.
              <br />
              Your team.
              <br />
              Your portfolio.
            </h1>
            <p>
              Manage reviewers and monitor applications scoped to your approved
              bank.
            </p>
            <div className="hero-point">
              <ShieldCheck /> Bank-scoped access
            </div>
          </div>
          <small className="side-foot">
            TCS Mortgage AI - Bank Admin portal
          </small>
        </div>
        {authMode === "register" ? (
          <BankRegistration onBack={() => setAuthMode("login")} />
        ) : authMode === "forgot" || resetToken ? (
          <PasswordRecoveryForm
            accountType="BANK_ADMIN"
            title="Bank Admin password recovery"
            className="auth-form"
            email={form.email}
            initialToken={resetToken}
            onBack={() => {
              setAuthMode("login");
              window.history.replaceState({}, "", window.location.pathname);
            }}
          />
        ) : (
          <form className="auth-form" onSubmit={signIn}>
            <small className="eyebrow">BANK ADMIN</small>
            <h2>
              {authMode === "invite"
                ? "Accept invitation"
                : "Bank Admin sign in"}
            </h2>
            <p className="sub">
              {authMode === "invite"
                ? "Set a strong password to activate your one-time invitation."
                : "Use the account activated from your Platform Admin invitation."}
            </p>
            {authMode === "invite" ? (
              <>
                <label className="field">
                  <span>One-time invitation token</span>
                  <textarea
                    placeholder="Paste the one-time invitation token"
                    required
                    minLength="32"
                    value={invite.token}
                    onChange={(e) =>
                      setInvite({ ...invite, token: e.target.value })
                    }
                  />
                </label>
                <label className="field">
                  <span>Create password (8+ characters)</span>
                  <div className="password-control">
                    <input
                      type={showInvitePassword ? "text" : "password"}
                      placeholder="Create a password (8+ characters)"
                      minLength="8"
                      required
                      value={invite.password}
                      onChange={(e) =>
                        setInvite({ ...invite, password: e.target.value })
                      }
                    />
                    <button
                      type="button"
                      onClick={() => setShowInvitePassword((v) => !v)}
                      aria-label={
                        showInvitePassword ? "Hide password" : "Show password"
                      }
                    >
                      {showInvitePassword ? (
                        <EyeOff size={16} />
                      ) : (
                        <Eye size={16} />
                      )}
                    </button>
                  </div>
                </label>
                <button className="primary wide" disabled={busy}>
                  {busy ? "Activating..." : "Accept invitation"}
                </button>
                <button
                  type="button"
                  className="secondary wide"
                  onClick={() => setAuthMode("login")}
                >
                  Back to sign in
                </button>
              </>
            ) : (
              <>
                <label className="field">
                  <span>Email</span>
                  <input
                    type="email"
                    placeholder="reviewer@yourbank.com"
                    required
                    value={form.email}
                    onChange={(e) =>
                      setForm({ ...form, email: e.target.value })
                    }
                  />
                </label>
                <label className="field">
                  <span>Password</span>
                  <div className="password-control">
                    <input
                      type={showPassword ? "text" : "password"}
                      placeholder="Enter your password"
                      required
                      value={form.password}
                      onChange={(e) =>
                        setForm({ ...form, password: e.target.value })
                      }
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
                </label>
                <button
                  type="button"
                  className="recovery-link"
                  onClick={() => setAuthMode("forgot")}
                >
                  Forgot password?
                </button>
                <button className="primary wide" disabled={busy}>
                  {busy ? "Signing in..." : "Sign In"}
                </button>
                <button
                  type="button"
                  className="secondary wide"
                  onClick={() => setAuthMode("invite")}
                >
                  Accept invitation token
                </button>
                <button
                  type="button"
                  className="secondary wide"
                  onClick={() => setAuthMode("register")}
                >
                  Register Your Bank
                </button>
              </>
            )}
          </form>
        )}
      </div>
    );
  return (
    <div className="layout admin-layout bank-admin-layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="mark">M</span>
          <div>
            <b>Mortgage AI</b>
            <small>Bank workspace</small>
          </div>
        </div>
        <div className="bank-identity">
          <span className="bank-identity-mark">
            <Building2 size={17} />
          </span>
          <div className="bank-identity-copy">
            <b title={user.bank?.name}>{user.bank?.name || "Approved bank"}</b>
            <small>{user.bank?.code || "Bank account"}</small>
          </div>
        </div>
        {[
          ["overview", "Overview", Building2],
          ["applications", "Applications", ClipboardList],
          ["reviewers", "Reviewers", Users],
          ["history", "Assignment history", RefreshCw],
          ["policies", "Bank policies", ShieldCheck],
          ["notifications", "Notifications", RefreshCw],
        ].map(([key, label, Icon]) => (
          <button
            key={key}
            className={`nav ${tab === key ? "active" : ""}`}
            onClick={() => setTab(key)}
          >
            <Icon />
            <span>{label}</span>
          </button>
        ))}
        <div className="side-bottom">
          <button className="nav" onClick={logout}>
            <LogOut />
            <span>Sign out</span>
          </button>
        </div>
      </aside>
      <main>
        <header>
          <div className="breadcrumb">
            Bank administration <span>/</span> {tab}
          </div>
          <div className="profile">
            <span className="avatar">{user.full_name?.[0] || "B"}</span>
            <div>
              <b>{user.full_name}</b>
              <small>Bank Admin</small>
            </div>
          </div>
        </header>
        <section className="content">
          <div className="heading">
            <div>
              <small className="eyebrow">BANK OPERATIONS</small>
              <h1>
                {tab === "overview"
                  ? "Overview"
                  : tab === "applications"
                    ? "Applications"
                    : tab === "reviewers"
                      ? "Reviewer management"
                      : tab === "history"
                        ? "Assignment history"
                        : tab === "notifications"
                          ? "Notifications & alerts"
                          : tab === "policies"
                            ? "Policies & Compliance"
                            : "Bank policies"}
              </h1>
              <p>
                {tab === "policies"
                  ? "Manage bank lending policy documentation and customer-safe summaries."
                  : `Access is restricted to ${user.bank?.name}.`}
              </p>
            </div>
            <div className="bank-page-actions">
              {tab === "policies" && (
                <button
                  className="primary"
                  onClick={() =>
                    document
                      .getElementById("bank-policy-editor")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" })
                  }
                >
                  Add New Policy
                </button>
              )}
              {tab === "reviewers" && (
                <button
                  className="primary"
                  onClick={() =>
                    document
                      .getElementById("bank-reviewer-invite")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" })
                  }
                >
                  Invite Reviewer
                </button>
              )}
              <button className="secondary" onClick={load} disabled={busy}>
                <RefreshCw size={16} /> Refresh
              </button>
            </div>
          </div>
          {tab === "overview" && <BankOverview dashboard={dash} busy={busy} />}
          {tab === "applications" && (
            <BankApplications
              apps={apps}
              onRefresh={async () => {
                await load();
                notifySuccess("Application records refreshed.");
              }}
            />
          )}
          {tab === "notifications" && (
            <BankNotifications
              data={notifications}
              onRefresh={async (text) => {
                notifySuccess(text);
                await load();
              }}
            />
          )}
          {tab === "history" && <BankHistory rows={history} />}
          {tab === "policies" && (
            <div className="bank-policy-page">
              <div className="bank-policy-summary">
                <article>
                  <small>Total policies</small>
                  <b>{policies.length}</b>
                  <span>Saved policy versions</span>
                </article>
                <article>
                  <small>Active policies</small>
                  <b>{policies.filter((p) => p.active).length}</b>
                  <span>Currently available to retrieval</span>
                </article>
                <article>
                  <small>Archived versions</small>
                  <b>{policies.filter((p) => !p.active).length}</b>
                  <span>Retained for reference</span>
                </article>
              </div>
              <section
                className="panel bank-policy-editor"
                id="bank-policy-editor"
              >
                <div className="bank-section-head">
                  <div>
                    <h2>Add new policy</h2>
                    <p>
                      Manage policy documentation and optional customer-safe
                      retrieval summaries.
                    </p>
                  </div>
                </div>
                <div className="bank-policy-note">
                  Free-text policy content is documentation. The current system
                  does not execute policy rules or support approval and
                  effective-date lifecycles.
                </div>
                <form className="fields bank-policy-form" onSubmit={savePolicy}>
                  <label className="field">
                    <span>Title</span>
                    <input
                      placeholder="e.g. Residential mortgage eligibility"
                      required
                      minLength="3"
                      value={policy.title}
                      onChange={(e) =>
                        setPolicy({ ...policy, title: e.target.value })
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Version</span>
                    <input
                      placeholder="e.g. 1.0"
                      required
                      value={policy.policy_version}
                      onChange={(e) =>
                        setPolicy({ ...policy, policy_version: e.target.value })
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Category</span>
                    <input
                      placeholder="e.g. Mortgage underwriting"
                      required
                      minLength="2"
                      value={policy.category}
                      onChange={(e) =>
                        setPolicy({ ...policy, category: e.target.value })
                      }
                    />
                  </label>
                  <label className="field full">
                    <span>Upload policy PDF (optional)</span>
                    <input
                      type="file"
                      accept="application/pdf,.pdf"
                      disabled={busy || policyUploading}
                      onChange={(e) =>
                        extractPolicyPdf(e.target.files?.[0] || null)
                      }
                    />
                    {policyPdf && (
                      <button
                        type="button"
                        className="secondary small"
                        disabled={busy || policyUploading}
                        onClick={() => {
                          setPolicyPdf(null);
                          setPolicyExtraction(null);
                          setPolicyExtractError("");
                        }}
                      >
                        Remove selected PDF
                      </button>
                    )}
                    <small>
                      Select a text-based or scanned PDF. Text extraction
                      preserves page markers when available.
                    </small>
                  </label>
                  {policyUploading && (
                    <div
                      className="field full bank-policy-extraction-status"
                      role="status"
                    >
                      <progress max="100" value={policyUploadProgress} />
                      <small>
                        {policyUploadProgress < 100
                          ? `Uploading PDF? ${policyUploadProgress}%`
                          : "PDF uploaded. Extracting embedded text and scanned pages?"}
                      </small>
                    </div>
                  )}
                  {policyExtraction && (
                    <div
                      className={`field full bank-policy-extraction-status ${policyExtraction.extraction_status === "COMPLETED" ? "is-complete" : "needs-review"}`}
                      role="status"
                    >
                      <b>Extraction: {policyExtraction.extraction_status}</b>
                      <small>
                        {policyExtraction.extraction_message}{" "}
                        {policyExtraction.page_count
                          ? `${policyExtraction.page_count} page(s) processed.`
                          : ""}
                      </small>
                    </div>
                  )}
                  {policyExtractError && (
                    <div
                      className="field full bank-policy-extraction-error"
                      role="alert"
                    >
                      <span>{policyExtractError}</span>
                      <button
                        type="button"
                        className="secondary small"
                        disabled={busy || policyUploading || !policyPdf}
                        onClick={() => extractPolicyPdf(policyPdf, true)}
                      >
                        Retry extraction
                      </button>
                    </div>
                  )}
                  {policyPdf &&
                    policyExtraction &&
                    policyExtraction.extraction_status !== "COMPLETED" &&
                    !policyExtractError && (
                      <button
                        type="button"
                        className="secondary small"
                        disabled={busy || policyUploading}
                        onClick={() => extractPolicyPdf(policyPdf, true)}
                      >
                        Retry extraction
                      </button>
                    )}
                  <label className="field full">
                    <span>Policy text (editable extracted-text preview)</span>
                    <textarea
                      placeholder="Upload a PDF to extract policy text, or enter the policy text manually."
                      required
                      minLength="20"
                      maxLength="1000000"
                      rows="7"
                      value={policy.content}
                      onChange={(e) =>
                        setPolicy({ ...policy, content: e.target.value })
                      }
                    />
                  </label>
                  <div className="field full bank-policy-consent-field">
                    <label className="bank-policy-consent">
                      <input
                        type="checkbox"
                        checked={policy.customer_visible}
                        onChange={(e) =>
                          setPolicy({
                            ...policy,
                            customer_visible: e.target.checked,
                          })
                        }
                      />
                      <span>
                        Allow customer-facing AI to retrieve the customer-safe
                        summary
                      </span>
                    </label>
                    <small>
                      Leave unchecked for confidential policies. Only the
                      summary below is indexed for customer queries.
                    </small>
                  </div>
                  {policy.customer_visible && (
                    <label className="field full">
                      <span>
                        Customer-safe policy summary (minimum 20 characters)
                      </span>
                      <textarea
                        placeholder="Summarize the customer-facing requirement without internal notes."
                        required
                        minLength="20"
                        maxLength="20000"
                        rows="4"
                        value={policy.customer_summary}
                        onChange={(e) =>
                          setPolicy({
                            ...policy,
                            customer_summary: e.target.value,
                          })
                        }
                      />
                    </label>
                  )}
                  {error && (
                    <div
                      className="field full bank-policy-extraction-error"
                      role="alert"
                    >
                      {error}
                    </div>
                  )}
                  <button
                    className="primary"
                    disabled={busy || policyUploading}
                  >
                    {busy ? "Saving policy?" : "Save bank policy"}
                  </button>
                </form>
              </section>
              <BankPolicyDirectory
                policies={policies}
                onRefresh={async (text) => {
                  notifySuccess(text);
                  await load();
                }}
              />
            </div>
          )}
          {tab === "reviewers" && (
            <>
              <BankReviewerDirectory
                rows={reviewers}
                busy={busy}
                summary={reviewerSummary}
                summaryError={!!error}
                onView={setSelectedReviewer}
                onRefresh={async (text) => {
                  notifySuccess(text);
                  await load();
                }}
              />
              {selectedReviewer && (
                <BankReviewerProfile
                  reviewer={selectedReviewer}
                  onClose={() => setSelectedReviewer(null)}
                />
              )}
              <section
                className="panel bank-onboarding"
                id="bank-reviewer-invite"
              >
                <div className="bank-section-head">
                  <div>
                    <h2>Invite Reviewer</h2>
                    <p>
                      Send a secure, expiring activation link. Reviewers choose
                      their own password.
                    </p>
                  </div>
                </div>
                <form
                  className="reviewer-onboarding-form"
                  onSubmit={createReviewer}
                >
                  <div className="reviewer-onboarding-grid">
                    <div className="reviewer-form-section">
                      <h3>Identity and account</h3>
                      <div className="reviewer-form-grid">
                        <label className="field">
                          <span>
                            Full legal name <b className="required-mark">*</b>
                          </span>
                          <input
                            placeholder="Reviewer full name"
                            required
                            minLength="2"
                            maxLength="160"
                            value={newReviewer.full_name}
                            onChange={(e) =>
                              setNewReviewer({
                                ...newReviewer,
                                full_name: e.target.value,
                              })
                            }
                          />
                        </label>
                        <label className="field">
                          <span>
                            Official work email{" "}
                            <b className="required-mark">*</b>
                          </span>
                          <input
                            type="email"
                            placeholder="name@yourbank.com"
                            required
                            value={newReviewer.email}
                            onChange={(e) =>
                              setNewReviewer({
                                ...newReviewer,
                                email: e.target.value,
                              })
                            }
                          />
                        </label>
                        <div className="reviewer-security-note">
                          <ShieldCheck size={16} />
                          <span>
                            The invitation is single-use and expires in 48
                            hours. The reviewer sets their own password before
                            the account becomes active.
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="reviewer-form-section">
                      <h3>Expertise and capacity</h3>
                      <div className="reviewer-form-grid">
                        <label className="field">
                          <span>
                            Primary specialization{" "}
                            <b className="required-mark">*</b>
                          </span>
                          <select
                            value={newReviewer.specialisation}
                            onChange={(e) =>
                              setNewReviewer({
                                ...newReviewer,
                                specialisation: e.target.value,
                              })
                            }
                          >
                            <option value="GENERAL_MORTGAGE_REVIEW">
                              General Mortgage Review
                            </option>
                            <option value="INCOME_TAX">Income & Tax</option>
                            <option value="PROPERTY_VALUATION">
                              Property Valuation
                            </option>
                            <option value="TERMS_CONDITIONS">
                              Terms & Conditions
                            </option>
                          </select>
                        </label>
                        <label className="field">
                          <span>
                            Maximum active assignments{" "}
                            <b className="required-mark">*</b>
                          </span>
                          <input
                            type="number"
                            placeholder="e.g. 10"
                            min="1"
                            max="100"
                            required
                            value={newReviewer.max_active_assignments}
                            onChange={(e) =>
                              setNewReviewer({
                                ...newReviewer,
                                max_active_assignments: Number(e.target.value),
                              })
                            }
                          />
                          <small>
                            Capacity must be between 1 and 100. Current load is
                            derived after creation.
                          </small>
                        </label>
                      </div>
                    </div>
                  </div>
                  <div className="reviewer-create-summary">
                    <b>Assignment method</b>
                    <span>
                      Automatic, same-bank routing based on eligibility,
                      availability, specialization and workload. No manual
                      assignment control is provided.
                    </span>
                  </div>
                  <button className="primary" disabled={busy}>
                    {busy ? "Creating reviewer..." : "Create Reviewer"}
                  </button>
                </form>
              </section>
            </>
          )}
        </section>
      </main>
    </div>
  );
}

function BankNotifications({ data, onRefresh }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [readStatus, setReadStatus] = useState("all");
  const [archived, setArchived] = useState(false);
  const [archivedRows, setArchivedRows] = useState([]);
  const [page, setPage] = useState(0);
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");
  const pageSize = 10;
  useEffect(() => {
    let live = true;
    if (archived) {
      call("/bank-admin/notifications?archived=true&limit=100")
        .then((result) => {
          if (live) setArchivedRows(result.items || []);
        })
        .catch(() => {
          if (live) notifyError();
        });
    }
    return () => {
      live = false;
    };
  }, [archived]);
  const rows = archived ? archivedRows : data?.items || [];
  const filtered = rows.filter(
    (row) =>
      (!query ||
        `${row.title} ${row.message} ${row.resource_id}`
          .toLowerCase()
          .includes(query.trim().toLowerCase())) &&
      (category === "all" || row.category === category) &&
      (severity === "all" || row.severity === severity) &&
      (readStatus === "all" ||
        (readStatus === "read" && row.read) ||
        (readStatus === "unread" && !row.read)),
  );
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  async function update(row, action) {
    setBusyId(row.id);
    setError("");
    try {
      if (action === "archive")
        await call(`/bank-admin/notifications/${row.id}`, { method: "DELETE" });
      else
        await call(`/bank-admin/notifications/${row.id}/read`, {
          method: "PATCH",
          body: JSON.stringify({ read: !row.read }),
        });
      await onRefresh(
        action === "archive"
          ? "Notification archived; assignment history is retained."
          : `Notification marked ${row.read ? "unread" : "read"}.`,
      );
      if (archived)
        setArchivedRows(
          (await call("/bank-admin/notifications?archived=true&limit=100"))
            .items || [],
        );
    } catch {
      notifyError();
    } finally {
      setBusyId(null);
    }
  }
  return (
    <section className="panel bank-ops">
      <div className="bank-section-head">
        <div>
          <h2>Bank notifications</h2>
          <p>Review and manage alerts generated from assignment activity.</p>
        </div>
        <span className="bank-unread-count">
          {data?.unread_count ?? 0} unread
        </span>
      </div>
      <div className="bank-toolbar">
        <input
          aria-label="Search notifications"
          placeholder="Search notifications"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(0);
          }}
        />
        <select
          aria-label="Filter notification category"
          value={category}
          onChange={(e) => {
            setCategory(e.target.value);
            setPage(0);
          }}
        >
          <option value="all">All categories</option>
          <option value="ASSIGNMENT">Assignment</option>
        </select>
        <select
          aria-label="Filter notification severity"
          value={severity}
          onChange={(e) => {
            setSeverity(e.target.value);
            setPage(0);
          }}
        >
          <option value="all">All severity levels</option>
          {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter notification read status"
          value={readStatus}
          onChange={(e) => {
            setReadStatus(e.target.value);
            setPage(0);
          }}
        >
          <option value="all">All read states</option>
          <option value="unread">Unread</option>
          <option value="read">Read</option>
        </select>
        <label className="bank-checkbox">
          <input
            type="checkbox"
            checked={archived}
            onChange={(e) => {
              setArchived(e.target.checked);
              setPage(0);
              setError("");
            }}
          />
          Show archived
        </label>
        <button
          className="secondary small"
          onClick={() => onRefresh("Notifications refreshed.")}
        >
          Refresh
        </button>
      </div>
      <div className="bank-notification-list">
        {filtered.slice(page * pageSize, (page + 1) * pageSize).map((row) => (
          <article
            className={`bank-notification ${row.read ? "is-read" : "is-unread"} ${row.archived ? "is-archived" : ""}`}
            key={row.id}
          >
            <span
              className={`notification-severity severity-${row.severity.toLowerCase()}`}
            >
              {row.severity}
            </span>
            <div className="bank-notification-body">
              <b>{row.title}</b>
              <p>{row.message}</p>
              <small>
                {row.category.replaceAll("_", " ")} ·{" "}
                {new Date(row.created_at).toLocaleString()}
              </small>
            </div>
            <div className="bank-notification-actions">
              <button
                className="secondary small"
                disabled={busyId === row.id}
                onClick={() => update(row, "read")}
              >
                {row.read ? "Mark unread" : "Mark read"}
              </button>
              {!archived && (
                <button
                  className="secondary small"
                  disabled={busyId === row.id}
                  onClick={() => update(row, "archive")}
                >
                  Archive
                </button>
              )}
            </div>
          </article>
        ))}
        {!filtered.length && (
          <p className="bank-empty">
            {archived
              ? "No archived notifications match these filters."
              : data
                ? "No notifications match these filters."
                : "Loading notifications…"}
          </p>
        )}
      </div>
      <div className="bank-pagination">
        <span>
          {filtered.length} notifications · Page {page + 1} of {pages}
        </span>
        <button
          className="secondary small"
          disabled={!page}
          onClick={() => setPage(page - 1)}
        >
          Previous
        </button>
        <button
          className="secondary small"
          disabled={page + 1 >= pages}
          onClick={() => setPage(page + 1)}
        >
          Next
        </button>
      </div>
    </section>
  );
}

export function BankPolicyDirectory({ policies, onRefresh }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");
  const [publishing, setPublishing] = useState(null);
  const [publishForm, setPublishForm] = useState({
    title: "",
    policy_version: "",
    category: "",
    customer_summary: "",
  });
  const [publishBusy, setPublishBusy] = useState(false);
  const [publishError, setPublishError] = useState("");
  const rows = policies.filter(
    (policy) =>
      (!query ||
        `${policy.title} ${policy.category} ${policy.policy_version}`
          .toLowerCase()
          .includes(query.trim().toLowerCase())) &&
      (status === "all" ||
        (status === "active" && policy.active) ||
        (status === "archived" && !policy.active)),
  );
  async function toggle(policy) {
    if (
      !window.confirm(
        `${policy.active ? "Archive" : "Activate"} policy ?${policy.title}? version ${policy.policy_version}?`,
      )
    )
      return;
    setBusyId(policy.id);
    setError("");
    try {
      await call(
        `/bank-admin/policies/${policy.id}/active?active=${!policy.active}`,
        { method: "PATCH" },
      );
      await onRefresh(`Policy ${policy.active ? "archived" : "activated"}.`);
    } catch (e) {
      setError(e.message || "Policy status could not be changed.");
    } finally {
      setBusyId(null);
    }
  }
  async function reindex(policy) {
    setBusyId(policy.id);
    setError("");
    try {
      const result = await call(`/bank-admin/policies/${policy.id}/reindex`, {
        method: "POST",
      });
      await onRefresh(
        result.indexing?.error
          ? "Policy text index rebuilt; embedding retry failed, so lexical retrieval remains available."
          : "Policy retrieval index rebuilt.",
      );
    } catch (e) {
      setError(e.message || "Policy indexing could not be rebuilt.");
    } finally {
      setBusyId(null);
    }
  }
  function beginPublish(policy) {
    setPublishing(policy);
    setPublishForm({
      title:
        String(policy.title || "")
          .trim()
          .toLowerCase() === "policy"
          ? ""
          : String(policy.title || ""),
      policy_version: "",
      category: policy.category || "",
      customer_summary: "",
    });
    setPublishError("");
  }
  async function publishVersion(event) {
    event.preventDefault();
    if (!publishing || publishBusy) return;
    if (
      !window.confirm(
        `Publish ${publishForm.title.trim()} version ${publishForm.policy_version.trim()} for customer-facing policy retrieval?`,
      )
    )
      return;
    setPublishBusy(true);
    setPublishError("");
    try {
      const result = await call(
        `/bank-admin/policies/${publishing.id}/customer-versions`,
        {
          method: "POST",
          body: JSON.stringify({
            ...publishForm,
            title: publishForm.title.trim(),
            policy_version: publishForm.policy_version.trim(),
            category: publishForm.category.trim(),
            customer_summary: publishForm.customer_summary.trim(),
          }),
        },
      );
      setPublishing(null);
      await onRefresh(
        result.indexing?.error
          ? "Customer-safe version published; NVIDIA embeddings were unavailable, and the saved lexical index is in use."
          : "Customer-safe policy version published and indexed.",
      );
    } catch (e) {
      setPublishError(
        e.message || "The customer-safe policy version could not be published.",
      );
    } finally {
      setPublishBusy(false);
    }
  }
  return (
    <section className="panel bank-policy-directory">
      <div className="bank-section-head">
        <div>
          <h2>Policy directory</h2>
          <p>
            Bank-specific policy versions and their customer-facing
            availability.
          </p>
        </div>
        <span>
          {rows.length} of {policies.length} policies
        </span>
      </div>
      <div className="bank-toolbar">
        <input
          aria-label="Search policies"
          placeholder="Search title, category or version"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          aria-label="Filter policy status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="all">All policy states</option>
          <option value="active">Active</option>
          <option value="archived">Archived</option>
        </select>
      </div>
      {error && (
        <p className="policy-directory-error" role="alert">
          {error}
        </p>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>POLICY</th>
              <th>CATEGORY</th>
              <th>VERSION</th>
              <th>STATUS</th>
              <th>CUSTOMER VISIBILITY</th>
              <th>CONTENT</th>
              <th>ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((policy) => (
              <tr key={policy.id}>
                <td>
                  <b>{policy.title}</b>
                  <small>
                    {new Date(policy.created_at).toLocaleDateString()}
                  </small>
                  {String(policy.title || "")
                    .trim()
                    .toLowerCase() === "policy" && (
                    <small>
                      Generic title: choose an accurate customer-safe title
                      before publishing.
                    </small>
                  )}
                  {policy.has_source_pdf && (
                    <button
                      type="button"
                      className="policy-source-download"
                      disabled={busyId === policy.id}
                      onClick={async () => {
                        setBusyId(policy.id);
                        try {
                          await downloadPolicyPdf(policy);
                        } catch (e) {
                          setError(
                            e.message || "Policy PDF could not be downloaded.",
                          );
                        } finally {
                          setBusyId(null);
                        }
                      }}
                    >
                      Download source PDF
                    </button>
                  )}
                </td>
                <td>{policy.category}</td>
                <td>{policy.policy_version}</td>
                <td>
                  <span
                    className={`bank-state ${policy.active ? "status-good" : ""}`}
                  >
                    {policy.active ? "Active" : "Archived"}
                  </span>
                </td>
                <td>
                  <span>
                    {policy.customer_visible
                      ? "Customer summary enabled"
                      : "Internal only"}
                  </span>
                  <small>
                    Text:{" "}
                    {policy.text_status === "TEXT_SAVED"
                      ? "Saved"
                      : "Unavailable"}
                  </small>
                  <small>
                    Indexing:{" "}
                    {policy.indexing_status === "COMPLETED"
                      ? "Completed"
                      : policy.indexing_status === "ARCHIVED"
                        ? "Inactive"
                        : policy.indexing_status === "NOT_SEARCHABLE"
                          ? "No usable text"
                          : policy.indexing_status === "INCOMPLETE"
                            ? "Incomplete"
                            : "Unavailable"}{" "}
                    ({policy.indexed_chunks || 0}/{policy.expected_chunks || 0}{" "}
                    chunks)
                  </small>
                  <small>
                    Embeddings:{" "}
                    {policy.embedding_status === "COMPLETED"
                      ? "Completed"
                      : policy.embedding_status === "NOT_CONFIGURED"
                        ? "Not configured"
                        : policy.embedding_status === "NOT_APPLICABLE"
                          ? "Not applicable"
                          : policy.embedding_status === "PARTIAL"
                            ? "Partial"
                            : "Unavailable"}
                  </small>
                  <small>
                    Customer Assistant:{" "}
                    {policy.customer_availability === "AVAILABLE"
                      ? "Available"
                      : policy.customer_availability === "INTERNAL_ONLY"
                        ? "Unavailable - internal only"
                        : policy.customer_availability === "INACTIVE"
                          ? "Unavailable - inactive"
                          : policy.customer_availability === "SUMMARY_MISSING"
                            ? "Unavailable - customer-safe summary missing"
                            : "Unavailable - customer indexing incomplete"}
                  </small>
                  {policy.customer_availability === "INTERNAL_ONLY" && (
                    <small>
                      Publish a customer-safe version below to keep this
                      internal version private.
                    </small>
                  )}
                </td>
                <td>
                  <details>
                    <summary>View content</summary>
                    <p className="policy-content-preview">{policy.content}</p>
                    {policy.customer_visible && (
                      <p className="policy-content-preview">
                        <b>Customer-safe summary:</b> {policy.customer_summary}
                      </p>
                    )}
                  </details>
                </td>
                <td className="bank-policy-actions">
                  <button
                    className="secondary small"
                    disabled={busyId === policy.id}
                    onClick={() => toggle(policy)}
                  >
                    {policy.active ? "Archive" : "Activate"}
                  </button>
                  {policy.active &&
                    (policy.indexing_status !== "COMPLETED" ||
                      policy.embedding_status === "UNAVAILABLE" ||
                      policy.embedding_status === "PARTIAL") && (
                      <button
                        className="secondary small"
                        disabled={busyId === policy.id}
                        onClick={() => reindex(policy)}
                      >
                        Retry indexing
                      </button>
                    )}
                  {policy.active && policy.text_status === "TEXT_SAVED" && (
                    <button
                      className="secondary small"
                      disabled={busyId === policy.id || publishBusy}
                      onClick={() => beginPublish(policy)}
                    >
                      {policy.customer_visible
                        ? "Create customer-safe version"
                        : "Publish customer-safe version"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan="7" className="bank-empty">
                  {policies.length
                    ? "No policies match these filters."
                    : "No bank policies have been added yet."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {publishing && (
        <div className="policy-publish-backdrop">
          <section
            className="policy-publish-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="policy-publish-title"
          >
            <div className="bank-section-head">
              <div>
                <span className="section-kicker">
                  EXPLICIT CUSTOMER PUBLICATION
                </span>
                <h2 id="policy-publish-title">Publish customer-safe version</h2>
                <p>
                  Source: {publishing.title} | v{publishing.policy_version}
                  {publishing.source_filename
                    ? ` | ${publishing.source_filename}`
                    : ""}
                </p>
              </div>
              <button
                type="button"
                className="secondary small"
                disabled={publishBusy}
                onClick={() => setPublishing(null)}
              >
                Close
              </button>
            </div>
            <p className="policy-publish-explanation">
              This creates a new active policy version using the saved extracted
              text and existing private PDF. Only the customer-approved summary
              below is indexed for Customer Assistant. The source version and
              file are retained.
            </p>
            {publishError && (
              <p className="policy-directory-error" role="alert">
                {publishError}
              </p>
            )}
            <form
              className="fields policy-publish-form"
              onSubmit={publishVersion}
            >
              <label className="field">
                <span>Customer-facing policy title</span>
                <input
                  required
                  minLength="3"
                  maxLength="200"
                  value={publishForm.title}
                  onChange={(e) =>
                    setPublishForm({ ...publishForm, title: e.target.value })
                  }
                  placeholder="Enter the accurate policy title"
                />
              </label>
              <label className="field">
                <span>New version</span>
                <input
                  required
                  minLength="1"
                  maxLength="80"
                  value={publishForm.policy_version}
                  onChange={(e) =>
                    setPublishForm({
                      ...publishForm,
                      policy_version: e.target.value,
                    })
                  }
                  placeholder="Enter the version to publish"
                />
              </label>
              <label className="field">
                <span>Category</span>
                <input
                  required
                  minLength="2"
                  maxLength="100"
                  value={publishForm.category}
                  onChange={(e) =>
                    setPublishForm({ ...publishForm, category: e.target.value })
                  }
                />
              </label>
              <label className="field full">
                <span>
                  Approved customer-safe summary (minimum 20 characters)
                </span>
                <textarea
                  required
                  minLength="20"
                  maxLength="20000"
                  rows="5"
                  value={publishForm.customer_summary}
                  onChange={(e) =>
                    setPublishForm({
                      ...publishForm,
                      customer_summary: e.target.value,
                    })
                  }
                  placeholder="Enter only information approved for customer-facing policy answers."
                />
              </label>
              <div className="policy-publish-actions">
                <button
                  type="button"
                  className="secondary"
                  disabled={publishBusy}
                  onClick={() => setPublishing(null)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="primary"
                  disabled={publishBusy}
                >
                  {publishBusy
                    ? "Publishing..."
                    : "Publish customer-visible version"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </section>
  );
}
