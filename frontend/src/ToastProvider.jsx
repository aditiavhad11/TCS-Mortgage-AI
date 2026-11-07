import { useCallback, useEffect, useRef, useState } from "react";

let publishToast = () => {};

export function notifySuccess(message) {
  publishToast("success", message);
}

export function notifyError(
  message = "Unable to complete the operation. Please try again.",
) {
  publishToast("error", message);
}

export function notifyInfo(message) {
  publishToast("info", message);
}

function Toast({ item, onDismiss }) {
  const timer = useRef(null);
  const remaining = useRef(item.duration);
  const startedAt = useRef(0);
  const hovered = useRef(false);
  const focused = useRef(false);

  const syncTimer = useCallback(() => {
    if (hovered.current || focused.current) {
      if (!timer.current) return;
      window.clearTimeout(timer.current);
      timer.current = null;
      remaining.current = Math.max(
        0,
        remaining.current - (Date.now() - startedAt.current),
      );
      return;
    }
    if (timer.current || remaining.current <= 0) return;
    startedAt.current = Date.now();
    timer.current = window.setTimeout(
      () => onDismiss(item.id),
      remaining.current,
    );
  }, [item.id, onDismiss]);

  useEffect(() => {
    syncTimer();
    return () => window.clearTimeout(timer.current);
  }, [syncTimer]);

  const isError = item.type === "error";
  return (
    <div
      className={`app-toast app-toast--${item.type}`}
      role={isError ? "alert" : "status"}
      aria-live={isError ? "assertive" : "polite"}
      onMouseEnter={() => {
        hovered.current = true;
        syncTimer();
      }}
      onMouseLeave={() => {
        hovered.current = false;
        syncTimer();
      }}
      onFocus={() => {
        focused.current = true;
        syncTimer();
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          focused.current = false;
          syncTimer();
        }
      }}
    >
      <span className="app-toast__message">{item.message}</span>
      <button
        type="button"
        className="app-toast__dismiss"
        onClick={() => onDismiss(item.id)}
        aria-label="Dismiss notification"
      >
        <span aria-hidden="true">×</span>
      </button>
    </div>
  );
}

export default function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const dismiss = useCallback(
    (id) => setItems((current) => current.filter((item) => item.id !== id)),
    [],
  );

  useEffect(() => {
    publishToast = (type, message) => {
      if (typeof message !== "string" || !message.trim()) return;
      const safeMessage = message
        .replace(
          /(?:bearer\s+)?[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}/gi,
          "[redacted]",
        )
        .replace(
          /\b(password|token|secret|authorization)\s*[:=]\s*\S+/gi,
          "$1: [redacted]",
        )
        .slice(0, 240);
      const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setItems((current) => [
        ...current.slice(-3),
        {
          id,
          type: type === "error" || type === "info" ? type : "success",
          message: safeMessage,
          duration: type === "error" ? 7000 : 5000,
        },
      ]);
    };
    return () => {
      publishToast = () => {};
    };
  }, []);

  return (
    <>
      {children}
      <div className="app-toast-region" aria-label="Notifications">
        {items.map((item) => (
          <Toast key={item.id} item={item} onDismiss={dismiss} />
        ))}
      </div>
    </>
  );
}
