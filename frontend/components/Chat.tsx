"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ChartRenderer, { parseChartSpec } from "./ChartRenderer";

type Message = { role: "user" | "assistant"; content: string };

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

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
    <div style={{ display: "flex", flexDirection: "column", height: "70vh" }}>
      <style>{`
        .chat-bubble table { border-collapse: collapse; margin: 8px 0; font-size: 13px; }
        .chat-bubble th, .chat-bubble td { border: 1px solid #d0d3d8; padding: 4px 8px; }
        .chat-bubble th { background: #e9ecef; }
        .chat-bubble p { margin: 4px 0; }
        .chat-bubble code { background: #e9ecef; padding: 1px 4px; border-radius: 4px; }
      `}</style>
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          border: "1px solid #e0e0e0",
          borderRadius: 8,
          padding: 16,
          background: "#fff",
        }}
      >
        {messages.length === 0 && (
          <div style={{ color: "#999", fontSize: 14 }}>매출 데이터에 대해 질문해 보세요.</div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              justifyContent: m.role === "user" ? "flex-end" : "flex-start",
              marginBottom: 12,
            }}
          >
            <div
              className="chat-bubble"
              style={{
                maxWidth: "80%",
                padding: "8px 12px",
                borderRadius: 10,
                background: m.role === "user" ? "#2563eb" : "#f1f3f5",
                color: m.role === "user" ? "#fff" : "#111",
                fontSize: 14,
              }}
            >
              {m.role === "assistant" ? (
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
              ) : (
                <span style={{ whiteSpace: "pre-wrap" }}>{m.content}</span>
              )}
            </div>
          </div>
        ))}
        {loading && <div style={{ color: "#999", fontSize: 14 }}>분석 중...</div>}
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="예) 이번 분기 제품별 매출 순위 알려줘"
          style={{
            flex: 1,
            padding: "10px 12px",
            borderRadius: 8,
            border: "1px solid #ccc",
            fontSize: 14,
          }}
        />
        <button
          onClick={send}
          disabled={loading}
          style={{
            padding: "10px 18px",
            borderRadius: 8,
            border: "none",
            background: "#2563eb",
            color: "#fff",
            fontSize: 14,
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          전송
        </button>
      </div>
    </div>
  );
}
