"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ChartRenderer, { parseChartSpec } from "./ChartRenderer";
import { useTheme, type ThemeSetting } from "./ThemeProvider";

type Message = {
  role: "user" | "assistant";
  content: string;
  // 백엔드 ChatResponse의 옵셔널 힌트 — 표/차트가 있어 PDF로 만들 만한 응답인지.
  reportAvailable?: boolean;
};

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

/** Content-Disposition 헤더에서 파일명을 뽑아낸다. 실패하면 기본값으로 폴백한다. */
function filenameFromDisposition(disposition: string | null): string {
  const fallback = "sales_report.pdf";
  if (!disposition) return fallback;

  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1].trim());
    } catch {
      // 잘못 인코딩된 헤더 — 아래 quoted filename으로 폴백
    }
  }
  const quoted = /filename="([^"]+)"/i.exec(disposition);
  if (quoted) return quoted[1];
  return fallback;
}

/**
 * assistant 메시지 아래에 붙는 "PDF 다운로드" 버튼.
 * 상태(생성 중/에러)는 메시지마다 독립적이므로 Chat 전역이 아니라 이 컴포넌트가 들고 있는다.
 */
function PdfDownloadButton({ content, question }: { content: string; question?: string }) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function download() {
    if (downloading) return;
    setDownloading(true);
    setError(null);

    try {
      const res = await fetch("/api/report/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, question: question ?? null }),
      });

      if (!res.ok) {
        let detail = "";
        try {
          detail = (await res.json())?.detail ?? "";
        } catch {
          // 본문이 JSON이 아니면 일반 메시지를 쓴다.
        }
        throw new Error(detail || "PDF 생성에 실패했습니다.");
      }

      const blob = await res.blob();
      const name = filenameFromDisposition(res.headers?.get?.("Content-Disposition") ?? null);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : "PDF 생성에 실패했습니다.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
      <button
        onClick={download}
        disabled={downloading}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          border: `1px solid ${COLORS.border}`,
          borderRadius: 16,
          padding: "5px 12px",
          fontSize: 13,
          background: COLORS.bubble,
          color: downloading ? COLORS.muted : COLORS.text,
          cursor: downloading ? "wait" : "pointer",
        }}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 3v12" />
          <polyline points="7 11 12 16 17 11" />
          <path d="M5 20h14" />
        </svg>
        {downloading ? "PDF 만드는 중..." : "PDF 다운로드"}
      </button>
      {error && <span style={{ color: "#e5484d", fontSize: 13 }}>{error}</span>}
    </div>
  );
}

/**
 * 프리셋에서 고른 주소 + 직접 입력한 주소(콤마/세미콜론으로 여러 개 가능)를 합쳐
 * 중복을 제거한 최종 수신자 목록을 만든다. 중복 판정은 대소문자를 무시하되
 * 표시는 사용자가 입력/선택한 원본 문자열을 그대로 유지한다.
 */
function mergeRecipients(presetSelection: string[], typed: string): string[] {
  const typedList = typed
    .split(/[,;]/)
    .map((s) => s.trim())
    .filter(Boolean);

  const seen = new Set<string>();
  const out: string[] = [];
  for (const addr of [...presetSelection, ...typedList]) {
    const key = addr.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(addr);
  }
  return out;
}

/**
 * assistant 메시지 아래에 붙는 "이메일로 보내기" 버튼.
 * 클릭하면 인라인 이메일 입력창이 나타난다(모달 아님). PdfDownloadButton과 동일하게
 * 상태(입력창 표시/발송 중/에러/성공)는 메시지마다 독립적으로 이 컴포넌트가 들고 있는다.
 *
 * 확장 시 GET /api/report/email/presets를 호출해 자주 쓰는 수신자 목록을 받아온다.
 * 이 엔드포인트는 이메일 기능이 꺼져 있어도 항상 200 {"presets": []}를 반환하므로
 * 조건 없이 호출해도 안전하며, 프리셋이 0개면 기존처럼 텍스트 입력만 보인다.
 */
function EmailSendButton({ content, question }: { content: string; question?: string }) {
  const [expanded, setExpanded] = useState(false);
  const [email, setEmail] = useState("");
  const [presets, setPresets] = useState<string[]>([]);
  const [selectedPresets, setSelectedPresets] = useState<string[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [sentTo, setSentTo] = useState<string[]>([]);

  useEffect(() => {
    if (!expanded) return;
    let alive = true;

    (async () => {
      try {
        const res = await fetch("/api/report/email/presets");
        if (!res?.ok) return;
        const data = await res.json();
        // 구버전 백엔드나 예상치 못한 형태여도 조용히 빈 목록으로 폴백한다(하위 호환).
        const list = Array.isArray(data?.presets)
          ? data.presets.filter((p: unknown): p is string => typeof p === "string" && !!p.trim())
          : [];
        if (alive) setPresets(list);
      } catch {
        // 프리셋은 편의 기능일 뿐이므로 실패해도 직접 입력으로 계속 진행한다.
      }
    })();

    return () => {
      alive = false;
    };
  }, [expanded]);

  function togglePreset(addr: string) {
    setSelectedPresets((prev) =>
      prev.includes(addr) ? prev.filter((a) => a !== addr) : [...prev, addr]
    );
  }

  async function send() {
    if (sending) return;
    const recipients = mergeRecipients(selectedPresets, email);
    if (recipients.length === 0) {
      setError("받는 사람 이메일을 입력해 주세요.");
      return;
    }
    setSending(true);
    setError(null);

    try {
      const res = await fetch("/api/report/email", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, question: question ?? null, to: recipients }),
      });

      if (!res.ok) {
        let detail = "";
        try {
          detail = (await res.json())?.detail ?? "";
        } catch {
          // 본문이 JSON이 아니면 일반 메시지를 쓴다.
        }
        throw new Error(detail || "이메일 발송에 실패했습니다.");
      }

      setSentTo(recipients);
      setSent(true);
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : "이메일 발송에 실패했습니다.");
    } finally {
      setSending(false);
    }
  }

  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          border: `1px solid ${COLORS.border}`,
          borderRadius: 16,
          padding: "5px 12px",
          fontSize: 13,
          background: COLORS.bubble,
          color: COLORS.text,
          cursor: "pointer",
        }}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M4 4h16v16H4z" />
          <path d="M4 6l8 7 8-7" />
        </svg>
        이메일로 보내기
      </button>
    );
  }

  const pickerLabel =
    selectedPresets.length === 0
      ? "자주 쓰는 수신자"
      : `자주 쓰는 수신자 ${selectedPresets.length}명 선택됨`;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
      {sent ? (
        <span style={{ color: COLORS.text, fontSize: 13 }}>메일 발송됨 ({sentTo.join(", ")})</span>
      ) : (
        <>
          {presets.length > 0 && (
            <div style={{ position: "relative" }}>
              <button
                type="button"
                aria-expanded={pickerOpen}
                onClick={() => setPickerOpen((v) => !v)}
                disabled={sending}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  border: `1px solid ${COLORS.border}`,
                  borderRadius: 16,
                  padding: "5px 12px",
                  fontSize: 13,
                  background: COLORS.bubble,
                  color: sending ? COLORS.muted : COLORS.text,
                  cursor: sending ? "wait" : "pointer",
                }}
              >
                {pickerLabel}
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>
              {pickerOpen && (
                <div
                  role="group"
                  aria-label="자주 쓰는 수신자 목록"
                  style={{
                    position: "absolute",
                    zIndex: 10,
                    top: "calc(100% + 4px)",
                    left: 0,
                    minWidth: 220,
                    maxHeight: 200,
                    overflowY: "auto",
                    background: COLORS.bg,
                    border: `1px solid ${COLORS.border}`,
                    borderRadius: 12,
                    padding: 6,
                    display: "flex",
                    flexDirection: "column",
                    gap: 2,
                  }}
                >
                  {presets.map((addr) => (
                    <label
                      key={addr}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        padding: "5px 8px",
                        borderRadius: 8,
                        fontSize: 13,
                        color: COLORS.text,
                        cursor: "pointer",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={selectedPresets.includes(addr)}
                        onChange={() => togglePreset(addr)}
                        disabled={sending}
                      />
                      {addr}
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="받는 사람 이메일"
            disabled={sending}
            style={{
              border: `1px solid ${COLORS.border}`,
              borderRadius: 16,
              padding: "5px 12px",
              fontSize: 13,
              background: COLORS.bg,
              color: COLORS.text,
              outline: "none",
              minWidth: 200,
            }}
          />
          <button
            onClick={send}
            disabled={sending}
            style={{
              border: `1px solid ${COLORS.border}`,
              borderRadius: 16,
              padding: "5px 12px",
              fontSize: 13,
              background: COLORS.bubble,
              color: sending ? COLORS.muted : COLORS.text,
              cursor: sending ? "wait" : "pointer",
            }}
          >
            {sending ? "보내는 중..." : "발송"}
          </button>
        </>
      )}
      {error && <span style={{ color: "#e5484d", fontSize: 13 }}>{error}</span>}
    </div>
  );
}

/**
 * 하단 메시지 입력창. 입력 중 글자 상태를 이 컴포넌트가 독립적으로 들고 있는다 —
 * Chat 최상위가 들고 있으면 타이핑할 때마다 메시지 목록(마크다운/차트 포함)까지
 * 통째로 리렌더돼 이미 그려진 막대 그래프가 매 키 입력마다 깜박이는 문제가 있었다.
 */
function ChatInputBar({ loading, onSend }: { loading: boolean; onSend: (text: string) => void }) {
  const [input, setInput] = useState("");

  function submit() {
    const text = input.trim();
    if (!text || loading) return;
    onSend(text);
    setInput("");
  }

  return (
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
        onKeyDown={(e) => e.key === "Enter" && submit()}
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
          onClick={submit}
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
  );
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, loading]);

  async function send(text: string) {
    if (!text || loading) return;

    const next = [...messages, { role: "user" as const, content: text }];
    setMessages(next);
    setLoading(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: next }),
      });
      const data = await res.json();
      setMessages([
        ...next,
        {
          role: "assistant",
          content: data.reply,
          // 필드가 없는 이전 백엔드와도 호환되도록 방어적으로 읽는다.
          reportAvailable: data?.report_available ?? false,
        },
      ]);
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
                {m.reportAvailable && (
                  <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <PdfDownloadButton
                      content={m.content}
                      question={
                        messages[i - 1]?.role === "user" ? messages[i - 1].content : undefined
                      }
                    />
                    <EmailSendButton
                      content={m.content}
                      question={
                        messages[i - 1]?.role === "user" ? messages[i - 1].content : undefined
                      }
                    />
                  </div>
                )}
              </div>
            )
          )}

          {loading && <div style={{ color: COLORS.muted, fontSize: 14 }}>분석 중...</div>}
          <div ref={endRef} />
        </div>
      </div>

      <div style={{ flex: "0 0 auto", padding: "8px 16px 24px" }}>
        <ChatInputBar loading={loading} onSend={send} />
      </div>
    </div>
  );
}
