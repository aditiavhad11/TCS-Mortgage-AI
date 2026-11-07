import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import {
  BadgeCheck,
  Bot,
  BookOpen,
  ChevronDown,
  FileText,
  LoaderCircle,
  MessageCircle,
  RotateCcw,
  Send,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import {
  policyQuestionPayload,
  policyDescription,
  initialPolicySelection,
} from "./utils/policyAssistant.js";

const SUGGESTIONS = [
  "What documents are required for a home loan?",
  "Explain the income eligibility requirements.",
  "What charges are mentioned in the policy?",
  "What happens if a required document is missing?",
];

export function PolicySelector({
  policies = [],
  selectedPolicyId = "",
  loading = false,
  error = "",
  onSelect = () => {},
  onRetry = () => {},
}) {
  return (
    <section
      className="policy-discovery"
      aria-labelledby="policy-discovery-title"
    >
      <div className="policy-discovery-heading">
        <div>
          <span className="section-kicker">CUSTOMER APPROVED SOURCES</span>
          <h2 id="policy-discovery-title">Choose a policy scope</h2>
          <p>
            Only active policies with customer-approved content available for
            retrieval are shown.
          </p>
        </div>
        <BookOpen size={19} />
      </div>
      {loading ? (
        <div className="policy-discovery-state" role="status">
          <LoaderCircle className="policy-spinner" size={17} /> Loading
          available policies…
        </div>
      ) : error ? (
        <div className="policy-discovery-state is-error" role="alert">
          <span>{error}</span>
          <button
            type="button"
            className="btn btn-secondary btn-small"
            onClick={onRetry}
          >
            <RotateCcw size={13} /> Retry
          </button>
        </div>
      ) : !policies.length ? (
        <div className="policy-discovery-state">
          No customer-visible policies are currently available for this scope.
          Please check again later.
        </div>
      ) : (
        <div className="policy-discovery-grid">
          <button
            type="button"
            className={`policy-discovery-card policy-discovery-all ${selectedPolicyId === "" ? "is-selected" : ""}`}
            aria-pressed={selectedPolicyId === ""}
            onClick={() => onSelect("")}
          >
            <span className="policy-discovery-icon">
              <BookOpen size={17} />
            </span>
            <span className="policy-discovery-card-copy">
              <b>All available policies</b>
              <small>Search all approved policies in this scope</small>
            </span>
            {selectedPolicyId === "" && (
              <BadgeCheck className="policy-discovery-check" size={17} />
            )}
          </button>
          {policies.map((policy) => (
            <button
              type="button"
              key={policy.id}
              className={`policy-discovery-card ${String(selectedPolicyId) === String(policy.id) ? "is-selected" : ""}`}
              aria-pressed={String(selectedPolicyId) === String(policy.id)}
              onClick={() => onSelect(String(policy.id))}
            >
              <span className="policy-discovery-icon">
                <FileText size={17} />
              </span>
              <span className="policy-discovery-card-copy">
                <b>{String(policy.title || "").trim() || "Untitled policy"}</b>
                <small className="policy-discovery-meta">
                  {[
                    policy.category,
                    policy.version ? `v${policy.version}` : null,
                    policy.status,
                    policy.bank_name,
                  ]
                    .filter(Boolean)
                    .join(" | ")}
                </small>
                {policyDescription(policy.description) && (
                  <small>{policyDescription(policy.description)}</small>
                )}
                {policy.source_filename && (
                  <small className="policy-discovery-filename">
                    PDF: {policy.source_filename}
                  </small>
                )}
              </span>
              {String(selectedPolicyId) === String(policy.id) && (
                <BadgeCheck className="policy-discovery-check" size={17} />
              )}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

export default function CustomerPolicyAssistant() {
  const [policies, setPolicies] = useState([]);
  const [selectedPolicyId, setSelectedPolicyId] = useState("");
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [catalogRetry, setCatalogRetry] = useState(0);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const listRef = useRef(null);
  const selectedPolicy = policies.find(
    (policy) => String(policy.id) === String(selectedPolicyId),
  );
  const scopeTitle =
    selectedPolicy?.title?.trim() ||
    (selectedPolicy ? "Untitled policy" : "All available policies");

  useEffect(() => {
    let cancelled = false;
    setCatalogLoading(true);
    setCatalogError("");
    setPolicies([]);
    setSelectedPolicyId("");
    api("/ai/policy-catalog")
      .then((result) => {
        if (!cancelled) {
          const available = Array.isArray(result?.policies)
            ? result.policies.filter(
                (item) => item && Number.isInteger(item.id),
              )
            : [];
          setPolicies(available);
          setSelectedPolicyId(initialPolicySelection(available));
        }
      })
      .catch((error) => {
        if (!cancelled)
          setCatalogError(
            error?.message || "Available policies could not be loaded.",
          );
      })
      .finally(() => {
        if (!cancelled) setCatalogLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [catalogRetry]);

  useEffect(() => {
    listRef.current?.scrollTo({
      top: listRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, busy]);

  async function ask(rawQuestion, { appendUser = true } = {}) {
    const question = String(rawQuestion || "").trim();
    if (!question || busy || catalogLoading || catalogError || !policies.length)
      return;
    const current = messages;
    const priorUserQuestions = current
      .filter((item) => item.role === "user")
      .map((item) => item.content);
    const recentQuestions = (
      appendUser ? priorUserQuestions : priorUserQuestions.slice(0, -1)
    ).slice(-3);
    if (appendUser)
      setMessages((previous) => [
        ...previous,
        { role: "user", content: question, scopeTitle },
      ]);
    setDraft("");
    setBusy(true);
    try {
      const result = await api("/ai/policy-qa", {
        method: "POST",
        body: JSON.stringify(
          policyQuestionPayload({
            question,
            applicationId: selectedPolicy?.application_id || "",
            policyId: selectedPolicyId,
            recentQuestions,
          }),
        ),
      });
      setMessages((previous) => [
        ...previous,
        { role: "assistant", content: result.answer, scopeTitle, ...result },
      ]);
    } catch (requestError) {
      const message =
        requestError?.message ||
        "Policy Assistant is unavailable. Please retry.";
      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: message,
          scopeTitle,
          requestError: true,
          retryQuestion: question,
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function newConversation() {
    if (busy) return;
    setMessages([]);
    setDraft("");
  }
  function changePolicy(value) {
    setSelectedPolicyId(value);
    setMessages([]);
  }
  function submit(event) {
    event.preventDefault();
    ask(draft);
  }

  return (
    <section className="surface-card customer-policy-assistant">
      <div className="policy-assistant-heading">
        <div className="policy-assistant-mark">
          <MessageCircle size={19} />
        </div>
        <div>
          <span className="section-kicker">CUSTOMER POLICY SUPPORT</span>
          <h1>Policy Assistant</h1>
          <p>
            Ask about the customer-visible mortgage policies available to you.
            Answers include source references when policy evidence is found.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary btn-small"
          onClick={newConversation}
          disabled={busy}
        >
          <RotateCcw size={14} /> New conversation
        </button>
      </div>

      <div className="policy-assistant-scope">
        <ShieldCheck size={16} />
        <span>
          Answers use active policies and bank-approved customer summaries only.
          The assistant cannot approve a loan or replace advice from your bank.
        </span>
        <span className="policy-assistant-catalog-scope">
          Policies available through your approved mortgage relationships
        </span>
      </div>

      <PolicySelector
        policies={policies}
        selectedPolicyId={selectedPolicyId}
        loading={catalogLoading}
        error={catalogError}
        onSelect={changePolicy}
        onRetry={() => setCatalogRetry((value) => value + 1)}
      />

      <div
        className={`policy-chat-log ${messages.length ? "has-messages" : ""}`}
        ref={listRef}
        role="log"
        aria-live="polite"
        aria-label="Policy Assistant conversation"
      >
        {!messages.length && (
          <div className="policy-chat-welcome">
            <span>
              <Bot size={23} />
            </span>
            <h2>How can I help with your policy questions?</h2>
            <p>
              I’ll look for relevant information in eligible policies and show
              you where it came from.
            </p>
            <div className="policy-suggestions">
              {SUGGESTIONS.map((question) => (
                <button
                  key={question}
                  type="button"
                  className="policy-suggestion"
                  disabled={
                    busy || catalogLoading || !!catalogError || !policies.length
                  }
                  onClick={() => ask(question)}
                >
                  {question}
                  <Send size={13} />
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((message, index) => (
          <article
            className={`policy-chat-message ${message.role === "user" ? "is-customer" : "is-assistant"}`}
            key={`${message.role}-${index}`}
          >
            <span className="policy-chat-avatar">
              {message.role === "user" ? (
                <UserRound size={15} />
              ) : (
                <Bot size={15} />
              )}
            </span>
            <div className="policy-chat-body">
              <span className="policy-chat-name">
                {message.role === "user" ? "You" : "Policy Assistant"}
                {message.scopeTitle && (
                  <small className="policy-message-scope">
                    {" "}
                    · {message.scopeTitle}
                  </small>
                )}
              </span>
              <div
                className={`policy-chat-bubble ${message.requestError ? "has-error" : ""}`}
                role={message.requestError ? "alert" : undefined}
              >
                {message.requestError ? (
                  <>
                    <p>{message.content}</p>
                    <button
                      type="button"
                      className="btn btn-secondary btn-small"
                      disabled={busy}
                      onClick={() =>
                        ask(message.retryQuestion, { appendUser: false })
                      }
                    >
                      <RotateCcw size={13} /> Retry
                    </button>
                  </>
                ) : (
                  <p>{message.content}</p>
                )}
                {message.role === "assistant" &&
                  message.insufficient_evidence &&
                  !message.requestError && (
                    <small className="policy-no-evidence">
                      {message.retrieval_status === "OUT_OF_SCOPE"
                        ? "This assistant answers questions about mortgage policies."
                        : "The selected policy scope did not provide enough evidence for a policy answer."}
                    </small>
                  )}
              </div>
              {message.role === "assistant" &&
                message.citations?.length > 0 && (
                  <details className="policy-chat-sources">
                    <summary>
                      <span>Sources ({message.citations.length})</span>
                      <ChevronDown size={14} />
                    </summary>
                    <div>
                      {message.citations.map((citation) => (
                        <article
                          className="policy-chat-source"
                          key={`${citation.policy_id}-${citation.source_id}`}
                        >
                          <b>
                            {String(citation.title || "").trim() ||
                              "Untitled policy"}
                            {citation.version ? ` · v${citation.version}` : ""}
                          </b>
                          <small>
                            {[
                              citation.category,
                              citation.page_number
                                ? `Page ${citation.page_number}`
                                : null,
                              citation.chunk_index != null
                                ? `Reference ${citation.chunk_index + 1}`
                                : null,
                              citation.source_filename
                                ? `PDF: ${citation.source_filename}`
                                : null,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </small>
                          <p>{citation.excerpt}</p>
                        </article>
                      ))}
                    </div>
                  </details>
                )}
              {message.role === "assistant" &&
                message.follow_up_questions?.length > 0 &&
                !message.requestError && (
                  <div
                    className="policy-followups"
                    aria-label="Suggested follow-up questions"
                  >
                    {message.follow_up_questions
                      .slice(0, 3)
                      .map((question, i) => (
                        <button
                          type="button"
                          key={`${question}-${i}`}
                          disabled={busy}
                          onClick={() => ask(question)}
                        >
                          {question}
                        </button>
                      ))}
                  </div>
                )}
            </div>
          </article>
        ))}
        {busy && (
          <div className="policy-chat-message is-assistant">
            <span className="policy-chat-avatar">
              <Bot size={15} />
            </span>
            <div className="policy-chat-body">
              <span className="policy-chat-name">
                Policy Assistant · {scopeTitle}
              </span>
              <div className="policy-chat-bubble policy-typing" role="status">
                <LoaderCircle size={15} /> Checking eligible policy sources and
                preparing an answer…
              </div>
            </div>
          </div>
        )}
      </div>
      <div className="policy-composer-scope" aria-live="polite">
        <BookOpen size={13} /> Question scope: <b>{scopeTitle}</b>
      </div>
      <form className="policy-chat-composer" onSubmit={submit}>
        <label className="visually-hidden" htmlFor="policy-question">
          Ask a mortgage policy question
        </label>
        <textarea
          id="policy-question"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit(event);
            }
          }}
          placeholder="Ask a question about mortgage policies…"
          maxLength={2000}
          rows={2}
          disabled={
            busy || catalogLoading || !!catalogError || !policies.length
          }
        />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={
            busy ||
            catalogLoading ||
            !!catalogError ||
            !policies.length ||
            !draft.trim()
          }
          aria-label="Send question"
        >
          {busy ? (
            <LoaderCircle size={17} className="policy-spinner" />
          ) : (
            <Send size={16} />
          )}
          <span>Send</span>
        </button>
      </form>
      <small className="policy-assistant-footnote">
        Policy explanations are informational. Confirm current requirements with
        your bank before taking action.
      </small>
    </section>
  );
}
