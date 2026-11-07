import { useCallback, useEffect, useState } from "react";
import {
  Bell,
  ClipboardCheck,
  Eye,
  EyeOff,
  LogOut,
  RefreshCw,
  UserRound,
} from "lucide-react";
import ReviewerReviewWorkspace from "./ReviewerReviewWorkspace";
import PasswordRecoveryForm from "./PasswordRecoveryForm";
import { money } from "./utils/format";
import { notifyError, notifySuccess } from "./ToastProvider";

const API = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1"
).replace(/\/$/, "");

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

function dateTime(value) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not recorded" : date.toLocaleString();
}

function ReviewerActivationPage({ inviteToken }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [activated, setActivated] = useState(false);

  async function activate(event) {
    event.preventDefault();
    setError("");
    setActivated(false);
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      const result = await request("/reviewer/accept-invitation", "", {
        method: "POST",
        body: JSON.stringify({ token: inviteToken, password }),
      });
      setPassword("");
      setConfirm("");
      setActivated(true);
      notifySuccess("Your reviewer account is active. Sign in to continue.");
    } catch (activationError) {
      notifyError();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="review-shell">
      <form className="review-login" onSubmit={activate}>
        <div className="review-brand">
          M<span>Mortgage Operations</span>
        </div>
        <p className="review-kicker">SECURE STAFF ACCESS</p>
        <h1>Activate reviewer account</h1>
        <p>
          Set your password to activate the reviewer account invited by your
          bank.
        </p>
        {error && (
          <div className="review-error" role="alert">
            {error}
          </div>
        )}
        {activated ? (
          <>
            <a href="/reviewer">Go to reviewer sign in</a>
          </>
        ) : (
          <>
            <label>
              New password
              <div className="password-control">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  minLength="8"
                  maxLength="128"
                  autoComplete="new-password"
                  placeholder="Create a password (8+ characters)"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>
            <label>
              Confirm password
              <div className="password-control">
                <input
                  type={showConfirm ? "text" : "password"}
                  value={confirm}
                  onChange={(event) => setConfirm(event.target.value)}
                  required
                  minLength="8"
                  maxLength="128"
                  autoComplete="new-password"
                  placeholder="Enter the password again"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm((value) => !value)}
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
            <button disabled={busy}>
              {busy ? "Activating…" : "Activate account"}
            </button>
            <small>
              The secure invitation can be used once and expires after 48 hours.
            </small>
          </>
        )}
        <a href="/reviewer">Reviewer sign in</a>
      </form>
    </div>
  );
}

function ReviewerLogin({
  busy,
  error,
  onSubmit,
  onForgotPassword,
  email,
  setEmail,
  password,
  setPassword,
}) {
  const [showPassword, setShowPassword] = useState(false);
  return (
    <div className="review-shell">
      <form className="review-login" onSubmit={onSubmit}>
        <div className="review-brand">
          M<span>Mortgage Operations</span>
        </div>
        <p className="review-kicker">SECURE STAFF ACCESS</p>
        <h1>Reviewer sign in</h1>
        <p>Access only applications assigned to your reviewer account.</p>
        {error && (
          <div className="review-error" role="alert">
            {error}
          </div>
        )}
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            autoComplete="username"
          />
        </label>
        <label>
          Password
          <div className="password-control">
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              autoComplete="current-password"
            />
            <button
              type="button"
              onClick={() => setShowPassword((value) => !value)}
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </label>
        <button
          type="button"
          className="recovery-link"
          onClick={onForgotPassword}
        >
          Forgot password?
        </button>
        <button disabled={busy}>
          {busy ? "Signing in…" : "Sign in securely"}
        </button>
        <small>
          Reviewer accounts are provisioned by an authorized operator. Public
          reviewer registration is disabled.
        </small>
        <a href="/">← Customer portal</a>
      </form>
    </div>
  );
}

function ReviewerQueue({ rows, filter, setFilter, busy, onRefresh, onOpen }) {
  const shown = rows.filter((row) => !filter || row.status === filter);
  const counts = {
    assigned: rows.filter((row) =>
      ["ASSIGNED", "SUBMITTED"].includes(row.status),
    ).length,
    pending: rows.filter((row) =>
      ["DOCUMENTS_REQUESTED", "ADDITIONAL_INFORMATION_REQUIRED"].includes(
        row.status,
      ),
    ).length,
    active: rows.filter((row) =>
      ["IN_REVIEW", "RECOMMEND_APPROVE", "RECOMMEND_DECLINE"].includes(
        row.status,
      ),
    ).length,
    escalated: rows.filter((row) => row.status === "ESCALATED").length,
    done: rows.filter((row) => row.status === "COMPLETED").length,
  };

  return (
    <>
      <div className="review-heading">
        <div>
          <p className="review-kicker">UNDERWRITING OPERATIONS</p>
          <h1>Assigned applications</h1>
          <p>
            Review evidence, record findings and submit a human recommendation.
          </p>
        </div>
        <button className="review-refresh" onClick={onRefresh} disabled={busy}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>
      <div className="review-stats">
        <article>
          <small>Assigned</small>
          <strong>{counts.assigned}</strong>
        </article>
        <article>
          <small>Awaiting review</small>
          <strong>{counts.pending}</strong>
        </article>
        <article>
          <small>In review</small>
          <strong>{counts.active}</strong>
        </article>
        <article>
          <small>Escalated</small>
          <strong>{counts.escalated}</strong>
        </article>
        <article>
          <small>Completed</small>
          <strong>{counts.done}</strong>
        </article>
      </div>
      <section className="review-card">
        <div className="review-list-head">
          <div>
            <h2>Review queue</h2>
            <p>Applications assigned to you only</p>
          </div>
          <select
            aria-label="Filter applications by status"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          >
            <option value="">All statuses</option>
            {[
              "ASSIGNED",
              "SUBMITTED",
              "IN_REVIEW",
              "DOCUMENTS_REQUESTED",
              "ADDITIONAL_INFORMATION_REQUIRED",
              "ESCALATED",
              "RECOMMEND_APPROVE",
              "RECOMMEND_DECLINE",
              "COMPLETED",
            ].map((status) => (
              <option key={status}>{status}</option>
            ))}
          </select>
        </div>
        {shown.length ? (
          <div className="review-table-wrap">
            <table className="review-table">
              <thead>
                <tr>
                  <th>APPLICATION / BORROWER</th>
                  <th>REQUESTED LOAN</th>
                  <th>PROPERTY VALUE</th>
                  <th>ASSIGNMENT / SUBMISSION</th>
                  <th>DOCUMENTS / OCR</th>
                  <th>STATUS</th>
                  <th>ACTION</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((application) => {
                  const documents = application.documents || [];
                  const ocrStatuses = [
                    ...new Set(
                      documents.map(
                        (document) => document.extraction_status || "UNKNOWN",
                      ),
                    ),
                  ];
                  return (
                    <tr key={application.id}>
                      <td>
                        <b>{application.reference}</b>
                        <small>
                          {application.customer?.full_name ||
                            "Borrower unavailable"}{" "}
                          · {application.lender_name}
                        </small>
                      </td>
                      <td>{money(application.requested_loan)}</td>
                      <td>{money(application.property_value)}</td>
                      <td>
                        <small>
                          Assigned: {dateTime(application.assigned_at)}
                        </small>
                        <small>
                          Submitted: {dateTime(application.submitted_at)}
                        </small>
                      </td>
                      <td>
                        <small>
                          {documents.length}{" "}
                          {documents.length === 1 ? "document" : "documents"}
                        </small>
                        <small>
                          {documents.length
                            ? `OCR: ${ocrStatuses.join(", ")}`
                            : "No documents uploaded"}
                        </small>
                      </td>
                      <td>
                        <span className="review-badge">
                          {application.status.replaceAll("_", " ")}
                        </span>
                      </td>
                      <td>
                        <button
                          className="review-open"
                          disabled={busy}
                          onClick={() => onOpen(application.id)}
                        >
                          Open Review →
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="review-empty">
            <ClipboardCheck size={28} />
            <h3>
              {rows.length
                ? "No applications match this status"
                : "No assigned applications"}
            </h3>
            <p>
              {rows.length
                ? "Choose another status filter or refresh your queue."
                : "The reviewer API returned no active assignments for your account. Submitted applications are assigned automatically to eligible reviewers in their bank; no applications are displayed until an assignment exists."}
            </p>
          </div>
        )}
      </section>
    </>
  );
}

function ReviewerSignedInPortal() {
  const [token, setToken] = useState(
    localStorage.getItem("mortgage_reviewer_token") || "",
  );
  const [me, setMe] = useState(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState(null);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recovering, setRecovering] = useState(false);
  const [notes, setNotes] = useState([]);
  const [showNotes, setShowNotes] = useState(false);

  const load = useCallback(
    async (currentToken = token, { quiet = false } = {}) => {
      if (!currentToken) return;
      setBusy(true);
      try {
        const [reviewer, queue, notifications] = await Promise.all([
          request("/reviewer/me", currentToken),
          request("/reviewer/applications", currentToken),
          request("/reviewer/notifications", currentToken),
        ]);
        setMe(reviewer);
        setRows(queue);
        setNotes(notifications);
        setError("");
      } catch (loadError) {
        if (quiet)
          setError(
            "Unable to load reviewer workspace. Refresh the page to try again.",
          );
        else notifyError();
      } finally {
        setBusy(false);
      }
    },
    [token],
  );

  useEffect(() => {
    if (token) load(token, { quiet: true });
  }, [token, load]);

  useEffect(() => {
    if (!token || selected) return undefined;
    const interval = setInterval(() => load(token, { quiet: true }), 15000);
    return () => clearInterval(interval);
  }, [token, selected, load]);

  async function login(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await request("/reviewer/login", "", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      localStorage.setItem("mortgage_reviewer_token", result.access_token);
      setToken(result.access_token);
      setMe(result.reviewer);
      setPassword("");
      notifySuccess("Signed in successfully.");
    } catch (loginError) {
      notifyError("Sign in failed. Check your credentials and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleAvailability() {
    if (!me) return;
    setBusy(true);
    try {
      const result = await request(
        `/reviewer/availability?available=${me.is_available === false}`,
        token,
        { method: "PATCH" },
      );
      const confirmation = result.is_available
        ? result.newly_assigned
          ? `You are available. ${result.newly_assigned} waiting application(s) were assigned to your bank's reviewers.`
          : "You are available for new automatic assignments."
        : "You are unavailable. No new applications will be assigned to you.";
      notifySuccess(confirmation);
      await load();
    } catch (availabilityError) {
      notifyError();
    } finally {
      setBusy(false);
    }
  }

  async function openApplication(applicationId) {
    setBusy(true);
    setError("");
    try {
      const detail = await request(
        `/reviewer/applications/${applicationId}`,
        token,
      );
      setSelected(detail);
    } catch (openError) {
      notifyError();
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function openNotification(notification) {
    try {
      if (!notification.read) {
        await request(
          `/reviewer/notifications/${notification.id}/read`,
          token,
          { method: "POST" },
        );
        notifySuccess("Notification marked as read.");
      }
      setShowNotes(false);
      if (notification.application_id)
        await openApplication(notification.application_id);
      await load();
    } catch (notificationError) {
      notifyError();
    }
  }

  async function readAllNotifications() {
    try {
      await request("/reviewer/notifications/read-all", token, {
        method: "POST",
      });
      await load();
      notifySuccess("All notifications marked as read.");
    } catch (notificationError) {
      notifyError();
    }
  }

  function logout() {
    localStorage.removeItem("mortgage_reviewer_token");
    setToken("");
    setMe(null);
    setRows([]);
    setNotes([]);
    setSelected(null);
  }

  if (!token || !me) {
    if (recovering)
      return (
        <div className="review-shell">
          <PasswordRecoveryForm
            accountType="REVIEWER"
            email={email}
            className="review-login"
            onBack={() => setRecovering(false)}
          />
        </div>
      );
    return (
      <ReviewerLogin
        busy={busy}
        error={error}
        onSubmit={login}
        onForgotPassword={() => setRecovering(true)}
        email={email}
        setEmail={setEmail}
        password={password}
        setPassword={setPassword}
      />
    );
  }

  return (
    <div className="review-shell">
      <header className="review-top">
        <div className="review-brand">
          M
          <span>
            Mortgage Operations <small>REVIEW WORKSPACE</small>
          </span>
        </div>
        <div className="review-user">
          <button
            onClick={toggleAvailability}
            disabled={busy}
            title="Unavailable reviewers receive no new automatic assignments"
          >
            {me.is_available === false
              ? "Unavailable — go available"
              : "Available — set unavailable"}
          </button>
          <button
            onClick={() => setShowNotes((value) => !value)}
            aria-label="Notifications"
          >
            <Bell size={15} /> {notes.filter((note) => !note.read).length || ""}
          </button>
          <UserRound size={17} />
          <span>
            {me.full_name}
            <small>{me.bank_code}</small>
          </span>
          <button onClick={logout}>
            <LogOut size={15} /> Sign out
          </button>
        </div>
      </header>
      <main className="review-main">
        {error && (
          <div className="review-error" role="alert">
            {error}
            <button onClick={() => setError("")}>Dismiss</button>
          </div>
        )}
        {showNotes && (
          <section className="review-card">
            <div className="review-list-head">
              <div>
                <h2>Notifications</h2>
                <p>New assignments appear here automatically</p>
              </div>
              <button className="review-refresh" onClick={readAllNotifications}>
                Mark all read
              </button>
            </div>
            {!notes.length ? (
              <div className="review-empty">
                <p>No notifications yet.</p>
              </div>
            ) : (
              <ul>
                {notes.map((notification) => (
                  <li
                    key={notification.id}
                    style={{
                      padding: "8px 0",
                      fontWeight: notification.read ? 400 : 700,
                      cursor: "pointer",
                    }}
                    onClick={() => openNotification(notification)}
                  >
                    {notification.title} — {notification.message}{" "}
                    <small>{dateTime(notification.created_at)}</small>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
        {selected ? (
          <ReviewerReviewWorkspace
            initial={selected}
            token={token}
            onBack={() => setSelected(null)}
            onRefresh={load}
          />
        ) : (
          <ReviewerQueue
            rows={rows}
            filter={filter}
            setFilter={setFilter}
            busy={busy}
            onRefresh={() => load()}
            onOpen={openApplication}
          />
        )}
      </main>
    </div>
  );
}

export default function ReviewerPortal() {
  const [activationToken] = useState(
    () => new URLSearchParams(window.location.search).get("activate") || "",
  );
  const [resetToken, setResetToken] = useState(
    () => new URLSearchParams(window.location.search).get("reset_token") || "",
  );
  useEffect(() => {
    const url = new URL(window.location.href);
    if (
      url.searchParams.has("activate") ||
      url.searchParams.has("reset_token")
    ) {
      url.searchParams.delete("activate");
      url.searchParams.delete("reset_token");
      window.history.replaceState(
        {},
        "",
        `${url.pathname}${url.search}${url.hash}`,
      );
    }
  }, []);
  if (resetToken)
    return (
      <div className="review-shell">
        <PasswordRecoveryForm
          accountType="REVIEWER"
          initialToken={resetToken}
          className="review-login"
          onBack={() => setResetToken("")}
        />
      </div>
    );
  return activationToken ? (
    <ReviewerActivationPage inviteToken={activationToken} />
  ) : (
    <ReviewerSignedInPortal />
  );
}
