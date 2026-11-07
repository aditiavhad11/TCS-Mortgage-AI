import { useEffect, useState } from "react";
import { notifyError, notifySuccess } from "./ToastProvider";

const API = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1"
).replace(/\/$/, "");
const EMPTY = {
  bank_name: "",
  institution_type: "",
  contact_email: "",
  contact_phone: "",
  address: "",
  ifsc_code: "",
  license_number: "",
};

export default function BankRegistration({ onBack }) {
  const [form, setForm] = useState(EMPTY);
  const [pending, setPending] = useState(null);
  const [registrationToken, setRegistrationToken] = useState("");
  const [verifiedEmail, setVerifiedEmail] = useState("");
  const [previousRejection, setPreviousRejection] = useState("");
  const [otp, setOtp] = useState("");
  const [resendIn, setResendIn] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(null);
  const set = (key) => (event) => {
    const value = event.target.value;
    if (
      key === "contact_email" &&
      registrationToken &&
      value.trim().toLowerCase() !== verifiedEmail
    ) {
      setRegistrationToken("");
      setVerifiedEmail("");
      setPreviousRejection("");
    }
    setForm({ ...form, [key]: value });
  };

  useEffect(() => {
    if (!resendIn) return;
    const timer = setTimeout(
      () => setResendIn((value) => Math.max(0, value - 1)),
      1000,
    );
    return () => clearTimeout(timer);
  }, [resendIn]);

  async function requestOtp(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/bank-admin/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          contact_email: form.contact_email.trim(),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok)
        throw Error(
          Array.isArray(body.detail)
            ? body.detail.map((item) => item.msg).join("; ")
            : body.detail || `Request failed (${response.status})`,
        );
      setPending(body);
      setOtp("");
      setResendIn(body.resend_after_seconds || 0);
      notifySuccess("Verification code sent to the registered email.");
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }

  async function verifyOtp(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/bank-admin/register/verify-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contact_email: form.contact_email.trim(),
          code: otp,
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok)
        throw Error(
          Array.isArray(body.detail)
            ? body.detail.map((item) => item.msg).join("; ")
            : body.detail || `Request failed (${response.status})`,
        );
      setPending(null);
      setRegistrationToken(body.registration_token);
      setVerifiedEmail(body.email);
      setPreviousRejection(body.previous_rejection_reason || "");
      notifySuccess("Official email verified.");
    } catch {
      notifyError("Email verification failed. Check the code and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function submitRegistration(event) {
    if (!registrationToken) return requestOtp(event);
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/bank-admin/register/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          contact_email: form.contact_email.trim(),
          registration_token: registrationToken,
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok)
        throw Error(
          Array.isArray(body.detail)
            ? body.detail.map((item) => item.msg).join("; ")
            : body.detail || `Request failed (${response.status})`,
        );
      setDone(body);
      notifySuccess("Bank registration submitted for approval.");
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }

  if (done)
    return (
      <div className="auth-form">
        <small className="eyebrow">BANK REGISTRATION</small>
        <h2>Registration submitted</h2>
        <div className="alert success">
          Your official email is verified. Registration is awaiting Platform
          Admin approval. Bank Admin access is available only after approval.
        </div>
        <button className="secondary wide" onClick={onBack}>
          Back to Sign In
        </button>
      </div>
    );

  if (pending)
    return (
      <form className="auth-form" onSubmit={verifyOtp}>
        <small className="eyebrow">
          BANK REGISTRATION · EMAIL VERIFICATION
        </small>
        <h2>Verify official email</h2>
        <p className="sub">
          Enter the 6-digit code sent to <b>{pending.email}</b>. It expires in{" "}
          {pending.expires_in_minutes} minutes.
        </p>
        {pending.delivery === "console" && (
          <div className="alert">
            Development mode: check the backend terminal for the code.
          </div>
        )}
        {error && <div className="alert error">{error}</div>}
        <label className="field">
          <span>6-digit verification code</span>
          <input
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            maxLength={6}
            required
            autoFocus
            value={otp}
            onChange={(event) => setOtp(event.target.value.replace(/\D/g, ""))}
          />
        </label>
        <button className="primary wide" disabled={busy || otp.length !== 6}>
          {busy ? "Verifying..." : "Verify Official Email"}
        </button>
        <button
          type="button"
          className="secondary wide"
          disabled={busy || resendIn > 0}
          onClick={requestOtp}
        >
          {resendIn > 0
            ? `Resend code in ${resendIn}s`
            : "Resend verification code"}
        </button>
        <button
          type="button"
          className="secondary wide"
          onClick={() => {
            setPending(null);
            setError("");
          }}
        >
          Back to details
        </button>
      </form>
    );

  return (
    <form className="auth-form" onSubmit={submitRegistration}>
      <small className="eyebrow">BANK REGISTRATION</small>
      <h2>
        {registrationToken
          ? "Review institution details"
          : "Register your institution"}
      </h2>
      <p className="sub">
        {registrationToken
          ? "Your official email is verified. Review the details below before submitting for Platform Admin approval."
          : "Provide official institution details. Registration remains pending until Platform Admin approval."}
      </p>
      {previousRejection && registrationToken && (
        <div className="alert error">
          <b>Previous rejection reason</b>
          <br />
          {previousRejection}
          <br />
          Correct the details below before resubmitting.
        </div>
      )}
      {error && <div className="alert error">{error}</div>}
      <label className="field">
        <span>Bank / Financial Institution Name</span>
        <input
          required
          minLength={3}
          maxLength={180}
          value={form.bank_name}
          onChange={set("bank_name")}
        />
      </label>
      <label className="field">
        <span>Institution Type</span>
        <select
          required
          value={form.institution_type}
          onChange={set("institution_type")}
        >
          <option value="">Select institution type</option>
          {[
            "Public Bank",
            "Private Bank",
            "Cooperative Bank",
            "NBFC",
            "Other",
          ].map((type) => (
            <option key={type}>{type}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Official Email Address</span>
        <input
          type="email"
          required
          maxLength={254}
          autoComplete="email"
          value={form.contact_email}
          onChange={set("contact_email")}
        />
      </label>
      <label className="field">
        <span>Official Contact Number</span>
        <input
          type="tel"
          required
          minLength={8}
          maxLength={20}
          pattern="[+()\-\s\d]{8,20}"
          value={form.contact_phone}
          onChange={set("contact_phone")}
        />
      </label>
      <label className="field">
        <span>Registered Office Address</span>
        <textarea
          required
          minLength={10}
          maxLength={1000}
          rows={3}
          value={form.address}
          onChange={set("address")}
        />
      </label>
      <label className="field">
        <span>IFSC Code (optional for institution-level registration)</span>
        <input
          maxLength={11}
          pattern="[A-Za-z]{4}0[A-Za-z0-9]{6}"
          value={form.ifsc_code}
          onChange={set("ifsc_code")}
        />
      </label>
      <label className="field">
        <span>
          RBI Registration / License Number{" "}
          {form.institution_type === "Other" ? "(if applicable)" : "(required)"}
        </span>
        <input
          required={form.institution_type !== "Other"}
          minLength={form.institution_type === "Other" ? undefined : 4}
          maxLength={80}
          value={form.license_number}
          onChange={set("license_number")}
        />
      </label>
      <button className="primary wide" disabled={busy}>
        {busy
          ? registrationToken
            ? "Submitting..."
            : "Sending verification code..."
          : registrationToken
            ? "Submit registration for approval"
            : "Verify Official Email"}
      </button>
      <button type="button" className="secondary wide" onClick={onBack}>
        Back to Sign In
      </button>
    </form>
  );
}
