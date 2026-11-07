import { useEffect, useState } from "react";
import { Eye, EyeOff, KeyRound } from "lucide-react";
import { notifyError, notifyInfo, notifySuccess } from "./ToastProvider";

const API = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1"
).replace(/\/$/, "");

export default function PasswordRecoveryForm({
  accountType,
  title,
  description,
  className = "",
  initialToken = "",
  email = "",
  onBack,
}) {
  const [resetToken, setResetToken] = useState(
    () =>
      initialToken ||
      new URLSearchParams(window.location.search).get("reset_token") ||
      "",
  );
  const [emailAddress, setEmailAddress] = useState(email);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [requested, setRequested] = useState(false);
  const [validationError, setValidationError] = useState("");
  const [busy, setBusy] = useState(false);

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

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    if (resetToken && password !== confirmPassword) {
      setValidationError("Passwords do not match.");
      return;
    }
    setValidationError("");
    setBusy(true);
    try {
      const isReset = Boolean(resetToken);
      const response = await fetch(
        `${API}/auth/password-reset/${isReset ? "complete" : "request"}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            isReset
              ? {
                  token: resetToken,
                  password,
                  confirm_password: confirmPassword,
                }
              : { email: emailAddress.trim(), account_type: accountType },
          ),
        },
      );
      const result = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(result.detail || "Password recovery is unavailable.");

      if (isReset) {
        setPassword("");
        setConfirmPassword("");
        setResetToken("");
        if (accountType === "CUSTOMER") {
          localStorage.removeItem("mortgage_access_token");
          localStorage.removeItem("mortgage_customer");
        } else if (accountType === "REVIEWER") {
          localStorage.removeItem("mortgage_reviewer_token");
        } else if (accountType === "BANK_ADMIN") {
          localStorage.removeItem("mortgage_bank_admin_token");
          localStorage.removeItem("mortgage_bank_admin");
        }
        notifySuccess(
          "Your password has been reset. Sign in using your new password.",
        );
        onBack();
      } else {
        setRequested(true);
        notifyInfo(
          result.message ||
            "If an eligible account exists, the recovery request is processed through its registered email address.",
        );
      }
    } catch {
      notifyError(
        resetToken
          ? "This reset link may be invalid or expired. Request a new link and try again."
          : "Password recovery is temporarily unavailable. Please try again later.",
      );
    } finally {
      setBusy(false);
    }
  }

  const isReset = Boolean(resetToken);
  return (
    <form className={`password-recovery-form ${className}`} onSubmit={submit}>
      <span className="recovery-icon" aria-hidden="true">
        <KeyRound size={19} />
      </span>
      <h2>
        {isReset ? "Set a new password" : title || "Forgot your password?"}
      </h2>
      <p className="recovery-description">
        {isReset
          ? "Choose a new password for your account."
          : description ||
            "Enter your account email. If an eligible account exists, we will send a secure reset link."}
      </p>
      {isReset ? (
        <>
          <label className="recovery-field">
            <span>New password</span>
            <div className="password-control">
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setValidationError("");
                }}
                required
                minLength={8}
                maxLength={128}
                autoComplete="new-password"
              />
              <button
                type="button"
                onClick={() => setShowPassword((value) => !value)}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            <small>Use at least 8 characters.</small>
          </label>
          <label className="recovery-field">
            <span>Confirm new password</span>
            <div className="password-control">
              <input
                type={showConfirmPassword ? "text" : "password"}
                value={confirmPassword}
                onChange={(event) => {
                  setConfirmPassword(event.target.value);
                  setValidationError("");
                }}
                required
                minLength={8}
                maxLength={128}
                autoComplete="new-password"
              />
              <button
                type="button"
                onClick={() => setShowConfirmPassword((value) => !value)}
                aria-label={
                  showConfirmPassword
                    ? "Hide confirm password"
                    : "Show confirm password"
                }
              >
                {showConfirmPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </label>
          {validationError && (
            <p className="recovery-validation-error" role="alert">
              {validationError}
            </p>
          )}
        </>
      ) : (
        <>
          <label className="recovery-field">
            <span>Email address</span>
            <input
              type="email"
              value={emailAddress}
              onChange={(event) => setEmailAddress(event.target.value)}
              required
              autoComplete="email"
              maxLength={254}
            />
          </label>
          {requested && (
            <p className="recovery-confirmation" role="status">
              If an eligible account exists, the recovery request is processed
              through its registered email address. Check your email for next
              steps.
            </p>
          )}
        </>
      )}
      <button className="recovery-submit" type="submit" disabled={busy}>
        {busy ? "Please wait…" : isReset ? "Reset password" : "Send reset link"}
      </button>
      <button
        className="recovery-back"
        type="button"
        onClick={onBack}
        disabled={busy}
      >
        Back to sign in
      </button>
    </form>
  );
}
