import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function newThreadId() {
  return crypto.randomUUID();
}

const ALL_CLEAR_IDS = new Set(["SOP-013", "SOP-014", "SOP-015"]);

function statusPill(msg) {
  if (msg.error_stage) return { label: "Data unavailable", tone: "warn" };
  if (msg.matched_sop_id) {
    if (msg.matched_sop_id === "SOP-007") {
      return { label: `${msg.matched_sop_id} · Critical override`, tone: "critical" };
    }
    if (ALL_CLEAR_IDS.has(msg.matched_sop_id)) {
      return { label: `${msg.matched_sop_id} · All clear`, tone: "clear" };
    }
    return { label: `Policy ${msg.matched_sop_id}`, tone: "risk" };
  }
  if (msg.final_answer && msg.final_answer.includes("No written policy")) {
    return { label: "No policy match", tone: "neutral" };
  }
  return null;
}

const SAMPLE_QUESTIONS = [
  "Is it safe to bike to work today in Bhopal?",
  "Taking my toddler to the park in Chennai at noon, is that okay?",
  "Is today a good day for a picnic in Bangalore?",
  "Thinking about walking my dog in Mumbai this evening",
];

export default function App() {
  const [threadId, setThreadId] = useState(newThreadId);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  async function sendMessage(text) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, message: trimmed }),
      });
      if (!res.ok) throw new Error(`Backend returned ${res.status}`);
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.final_answer,
          matched_sop_id: data.matched_sop_id,
          error_stage: data.error_stage,
        },
      ]);
    } catch (err) {
      setError(
        `Couldn't reach the backend at ${API_URL}. Is it running? (uvicorn app.api:app --port 8000) — ${err.message}`
      );
      setMessages((prev) => prev.slice(0, -1));
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    sendMessage(input);
  }

  function handleNewSession() {
    setThreadId(newThreadId());
    setMessages([]);
    setError(null);
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-icon" aria-hidden>
            ⛅
          </span>
          <div>
            <h1>Weather-Advisory Bot</h1>
            <p className="tagline">Policy-grounded outdoor safety answers</p>
          </div>
        </div>

        <button className="new-session-btn" onClick={handleNewSession}>
          + New session
        </button>

        <div className="sidebar-section">
          <h2>Try asking</h2>
          <ul className="sample-list">
            {SAMPLE_QUESTIONS.map((q) => (
              <li key={q}>
                <button className="sample-btn" onClick={() => sendMessage(q)} disabled={loading}>
                  {q}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="sidebar-section footer-note">
          <p>
            Every answer is grounded in live Open-Meteo data and cites a specific SOP from{" "}
            <code>sops.yaml</code>. If nothing applies, it says so instead of guessing.
          </p>
          <p className="thread-id">session: {threadId.slice(0, 8)}</p>
        </div>
      </aside>

      <main className="chat-panel">
        <div className="messages" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="empty-state">
              <p>Ask about outdoor activity safety — cycling, picnics, travel, walking a pet.</p>
              <p className="empty-sub">Answers are traceable to a written policy, or say plainly that none applies.</p>
            </div>
          )}

          {messages.map((msg, i) => {
            if (msg.role === "user") {
              return (
                <div key={i} className="message-row user">
                  <div className="bubble user-bubble">{msg.content}</div>
                </div>
              );
            }
            const pill = statusPill(msg);
            return (
              <div key={i} className="message-row assistant">
                <div className="bubble assistant-bubble">
                  {pill && <span className={`pill pill-${pill.tone}`}>{pill.label}</span>}
                  <div className="markdown">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  </div>
                </div>
              </div>
            );
          })}

          {loading && (
            <div className="message-row assistant">
              <div className="bubble assistant-bubble typing">
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
              </div>
            </div>
          )}
        </div>

        {error && <div className="error-banner">{error}</div>}

        <form className="composer" onSubmit={handleSubmit}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="e.g. Is it safe to bike to work today in Bhopal?"
            disabled={loading}
            autoFocus
          />
          <button type="submit" disabled={loading || !input.trim()}>
            Send
          </button>
        </form>
      </main>
    </div>
  );
}
