"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ChartRenderer, { parseChartSpec } from "./ChartRenderer";
import { useTheme, type ThemeSetting } from "./ThemeProvider";

type Message = { role: "user" | "assistant"; content: string };

const COLORS = {
  bg: "var(--bg)",
  bubble: "var(--bubble)",
  border: "var(--border)",
  text: "var(--text)",
  muted: "var(--muted)",
  accent: "var(--accent)",
};

const THEME_OPTIONS: { value: ThemeSetting; label: string }[] = [
  { value: "system", label: "시스템" },
  { value: "light", label: "밝게" },
  { value: "dark", label: "어둡게" },
];

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <div
      style={{
        display: "flex",
        gap: 2,
        background: COLORS.bubble,
        border: `1px solid ${COLORS.border}`,
        borderRadius: 20,
        padding: 3,
      }}
    >
      {THEME_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          onClick={() => setTheme(opt.value)}
          style={{
            border: "none",
            borderRadius: 16,
            padding: "5px 12px",
            fontSize: 13,
            cursor: "pointer",
            background: theme === opt.value ? COLORS.accent : "transparent",
            color: theme === opt.value ? "#fff" : COLORS.muted,
          }}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, loading]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;

    const next = [...messages, { role: "user" as const, content: text }];
    setMessages(next);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: next }),
      });
      const data = await res.json();
      setMessages([...next, { role: "assistant", content: data.reply }]);
    } catch {
      setMessages([
        ...next,
        { role: "assistant", content: "요청 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0, background: COLORS.bg }}>
      <style>{`
        .chat-bubble table { border-collapse: collapse; margin: 12px 0; font-size: 14px; width: 100%; }
        .chat-bubble th, .chat-bubble td { border: 1px solid ${COLORS.border}; padding: 6px 10px; }
        .chat-bubble th { background: ${COLORS.bubble}; }
        .chat-bubble p { margin: 8px 0; line-height: 1.6; }
        .chat-bubble code { background: ${COLORS.bubble}; padding: 1px 5px; border-radius: 4px; font-size: 13px; }
        .chat-input::placeholder { color: ${COLORS.muted}; }
      `}</style>

      <div style={{ flex: "0 0 auto", display: "flex", justifyContent: "flex-end", padding: "12px 16px 0" }}>
        <ThemeToggle />
      </div>

      <div style={{ flex: "1 1 auto", minHeight: 0, overflowY: "auto", padding: "24px 0" }}>
        <div style={{ maxWidth: 720, margin: "0 auto", padding: "0 16px" }}>
          {messages.length === 0 && (
            <div style={{ color: COLORS.muted, fontSize: 15, textAlign: "center", marginTop: "20vh" }}>
              매출 데이터에 대해 질문해 보세요.
            </div>
          )}

          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} style={{ display: "flex", justifyContent: "flex-end", marginBottom: 20 }}>
                <div
                  style={{
                    maxWidth: "75%",
                    padding: "10px 16px",
                    borderRadius: 18,
                    background: COLORS.bubble,
                    color: COLORS.text,
                    fontSize: 15,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {m.content}
                </div>
              </div>
            ) : (
              <div key={i} style={{ marginBottom: 28 }}>
                <div className="chat-bubble" style={{ color: COLORS.text, fontSize: 15 }}>
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      code(props) {
                        const { className, children, ...rest } = props;
                        const isChart = /language-chart/.test(className || "");
                        if (isChart) {
                          const spec = parseChartSpec(String(children).trim());
                          if (spec) return <ChartRenderer spec={spec} />;
                        }
                        return (
                          <code className={className} {...rest}>
                            {children}
                          </code>
                        );
                      },
                    }}
                  >
                    {m.content}
                  </ReactMarkdown>
                </div>
              </div>
            )
          )}

          {loading && <div style={{ color: COLORS.muted, fontSize: 14 }}>분석 중...</div>}
          <div ref={endRef} />
        </div>
      </div>

      <div style={{ flex: "0 0 auto", padding: "8px 16px 24px" }}>
        <div
          style={{
            maxWidth: 720,
            margin: "0 auto",
            background: COLORS.bubble,
            border: `1px solid ${COLORS.border}`,
            borderRadius: 26,
            padding: "10px 12px 10px 18px",
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <input
            className="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="메시지를 입력하세요..."
            style={{
              background: "none",
              border: "none",
              outline: "none",
              color: COLORS.text,
              fontSize: 15,
              padding: "4px 4px",
            }}
          />
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <button
              title="추가"
              style={{
                width: 30,
                height: 30,
                borderRadius: "50%",
                border: `1px solid ${COLORS.border}`,
                background: "none",
                color: COLORS.text,
                fontSize: 18,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              +
            </button>
            <button
              onClick={send}
              disabled={loading || !input.trim()}
              title="보내기"
              style={{
                width: 32,
                height: 32,
                borderRadius: "50%",
                border: "none",
                background: input.trim() && !loading ? COLORS.accent : COLORS.border,
                color: "#fff",
                cursor: loading || !input.trim() ? "not-allowed" : "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="12" y1="19" x2="12" y2="5" />
                <polyline points="5 12 12 5 19 12" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
