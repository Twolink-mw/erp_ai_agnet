import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Chat from "../Chat";

vi.mock("../ThemeProvider", () => ({
  useTheme: () => ({ theme: "system", resolvedTheme: "light", setTheme: vi.fn() }),
}));

function mockFetchOnce(reply: string) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      json: async () => ({ reply, tool_calls: [] }),
    })
  );
}

/** /api/chat은 report_available과 함께 응답하고, /api/report/pdf는 pdfResponse로 응답한다. */
function mockChatThenPdf(reply: string, reportAvailable: boolean, pdfResponse?: unknown) {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    if (String(url).includes("/api/report/pdf")) {
      if (pdfResponse instanceof Error) return Promise.reject(pdfResponse);
      return Promise.resolve(pdfResponse);
    }
    return Promise.resolve({
      json: async () => ({ reply, tool_calls: [], report_available: reportAvailable }),
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function okPdfResponse(disposition: string | null = 'attachment; filename="report.pdf"') {
  return {
    ok: true,
    headers: { get: (k: string) => (k.toLowerCase() === "content-disposition" ? disposition : null) },
    blob: async () => new Blob(["%PDF-1.4"], { type: "application/pdf" }),
  };
}

async function sendMessage(text: string) {
  const input = screen.getByPlaceholderText("메시지를 입력하세요...");
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: "Enter" });
}

describe("Chat", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the empty-state prompt when there are no messages", () => {
    mockFetchOnce("");
    render(<Chat />);
    expect(screen.getByText("매출 데이터에 대해 질문해 보세요.")).toBeInTheDocument();
  });

  it("renders a plain-text assistant reply as markdown", async () => {
    mockFetchOnce("안녕하세요, 매출 데이터를 분석해드릴게요.");
    render(<Chat />);

    await sendMessage("이번달 매출 알려줘");

    expect(await screen.findByText("이번달 매출 알려줘")).toBeInTheDocument();
    expect(
      await screen.findByText("안녕하세요, 매출 데이터를 분석해드릴게요.")
    ).toBeInTheDocument();
  });

  it("renders a ```chart block as a ChartRenderer instead of a code block", async () => {
    const chartSpec = {
      type: "bar",
      title: "월별 매출",
      xKey: "month",
      series: [{ key: "amt" }],
      data: [{ month: "1월", amt: 100 }],
    };
    mockFetchOnce("추이입니다.\n\n```chart\n" + JSON.stringify(chartSpec) + "\n```");

    render(<Chat />);
    await sendMessage("매출 추이 보여줘");

    await waitFor(() => {
      expect(screen.getByText("월별 매출")).toBeInTheDocument();
    });
    expect(screen.queryByText(/"type":\s*"bar"/)).not.toBeInTheDocument();
  });

  it("falls back to a plain code block when the chart JSON is invalid", async () => {
    mockFetchOnce("```chart\n{not valid json\n```");

    render(<Chat />);
    await sendMessage("매출 추이 보여줘");

    await waitFor(() => {
      expect(screen.getByText(/not valid json/)).toBeInTheDocument();
    });
  });

  it("renders a non-chart code block as a regular code element", async () => {
    mockFetchOnce("```js\nconsole.log('hi')\n```");

    render(<Chat />);
    await sendMessage("코드 보여줘");

    const code = await screen.findByText("console.log('hi')");
    expect(code.tagName.toLowerCase()).toBe("code");
  });

  it("renders user and assistant messages in order", async () => {
    mockFetchOnce("두번째 응답");

    render(<Chat />);
    await sendMessage("첫번째 질문");

    await screen.findByText("두번째 응답");

    const bubbles = screen.getAllByText(/질문|응답/);
    expect(bubbles[0]).toHaveTextContent("첫번째 질문");
    expect(bubbles[1]).toHaveTextContent("두번째 응답");
  });

  it("shows a loading indicator while the request is in flight and hides it after", async () => {
    let resolveFetch: (value: unknown) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise((resolve) => {
          resolveFetch = resolve;
        })
      )
    );

    render(<Chat />);
    await sendMessage("질문");

    expect(await screen.findByText("분석 중...")).toBeInTheDocument();

    resolveFetch({ json: async () => ({ reply: "답변", tool_calls: [] }) });

    await waitFor(() => {
      expect(screen.queryByText("분석 중...")).not.toBeInTheDocument();
    });
  });

  it("shows an error message when the fetch call rejects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));

    render(<Chat />);
    await sendMessage("질문");

    await waitFor(() => {
      expect(
        screen.getByText("요청 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
      ).toBeInTheDocument();
    });
  });

  it("does not send when the input is empty or only whitespace", () => {
    mockFetchOnce("응답");
    render(<Chat />);

    const input = screen.getByPlaceholderText("메시지를 입력하세요...");
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(global.fetch).not.toHaveBeenCalled();
  });
});

describe("Chat - PDF 다운로드 버튼", () => {
  let createObjectURL: ReturnType<typeof vi.fn>;
  let revokeObjectURL: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.restoreAllMocks();
    createObjectURL = vi.fn(() => "blob:mock");
    revokeObjectURL = vi.fn();
    // jsdom에는 Object URL API가 없다.
    (URL as unknown as Record<string, unknown>).createObjectURL = createObjectURL;
    (URL as unknown as Record<string, unknown>).revokeObjectURL = revokeObjectURL;
    // 실제 파일 다운로드는 jsdom에서 "Not implemented" 에러를 낸다.
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("report_available이 false면 버튼을 노출하지 않는다", async () => {
    mockChatThenPdf("일반 답변입니다.", false);
    render(<Chat />);
    await sendMessage("안녕");

    await screen.findByText("일반 답변입니다.");
    expect(screen.queryByRole("button", { name: /PDF 다운로드/ })).not.toBeInTheDocument();
  });

  it("report_available 필드가 아예 없는 응답에서도 버튼 없이 동작한다", async () => {
    mockFetchOnce("구버전 백엔드 응답");
    render(<Chat />);
    await sendMessage("안녕");

    await screen.findByText("구버전 백엔드 응답");
    expect(screen.queryByRole("button", { name: /PDF 다운로드/ })).not.toBeInTheDocument();
  });

  it("report_available이 true면 해당 메시지 아래에 버튼을 노출한다", async () => {
    mockChatThenPdf("| 월 | 매출 |\n| --- | --- |\n| 1월 | 100 |", true);
    render(<Chat />);
    await sendMessage("월별 매출 표로 보여줘");

    expect(await screen.findByRole("button", { name: /PDF 다운로드/ })).toBeInTheDocument();
  });

  it("버튼 클릭 시 content와 직전 user 질문을 /api/report/pdf로 전송한다", async () => {
    const reply = "표 응답입니다.";
    const fetchMock = mockChatThenPdf(reply, true, okPdfResponse());
    render(<Chat />);
    await sendMessage("월별 매출 알려줘");

    fireEvent.click(await screen.findByRole("button", { name: /PDF 다운로드/ }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/report/pdf", expect.anything());
    });
    const call = fetchMock.mock.calls.find((c) => String(c[0]).includes("/api/report/pdf"))!;
    const body = JSON.parse((call[1] as RequestInit).body as string);
    expect(body).toEqual({ content: reply, question: "월별 매출 알려줘" });
    // tables/charts는 중복 렌더링을 유발하므로 보내지 않는다.
    expect(body).not.toHaveProperty("tables");
    expect(body).not.toHaveProperty("charts");

    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock");
  });

  it("Content-Disposition의 UTF-8 파일명을 다운로드 파일명으로 사용한다", async () => {
    const disposition =
      "attachment; filename=\"report.pdf\"; filename*=UTF-8''%EB%A7%A4%EC%B6%9C.pdf";
    mockChatThenPdf("표 응답", true, okPdfResponse(disposition));
    const anchors: HTMLAnchorElement[] = [];
    const origCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = origCreate(tag);
      if (tag === "a") anchors.push(el as HTMLAnchorElement);
      return el;
    });

    render(<Chat />);
    await sendMessage("질문");
    fireEvent.click(await screen.findByRole("button", { name: /PDF 다운로드/ }));

    await waitFor(() => expect(anchors[0]?.download).toBe("매출.pdf"));
  });

  it("생성 중에는 버튼이 비활성화되고 진행 상태를 보여준다", async () => {
    let resolvePdf: (value: unknown) => void = () => {};
    const pending = new Promise((resolve) => {
      resolvePdf = resolve;
    });
    mockChatThenPdf("표 응답", true, pending);

    render(<Chat />);
    await sendMessage("질문");
    fireEvent.click(await screen.findByRole("button", { name: /PDF 다운로드/ }));

    const busy = await screen.findByRole("button", { name: /PDF 만드는 중/ });
    expect(busy).toBeDisabled();

    resolvePdf(okPdfResponse());
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /PDF 다운로드/ })).toBeEnabled();
    });
  });

  it("500 응답이면 detail 메시지를 에러로 표시한다", async () => {
    mockChatThenPdf("표 응답", true, {
      ok: false,
      status: 500,
      json: async () => ({ detail: "PDF 생성에 실패했습니다." }),
    });

    render(<Chat />);
    await sendMessage("질문");
    fireEvent.click(await screen.findByRole("button", { name: /PDF 다운로드/ }));

    expect(await screen.findByText("PDF 생성에 실패했습니다.")).toBeInTheDocument();
    // 실패해도 다시 시도할 수 있어야 한다.
    expect(screen.getByRole("button", { name: /PDF 다운로드/ })).toBeEnabled();
  });

  it("네트워크 오류에도 크래시하지 않고 에러 메시지를 표시한다", async () => {
    mockChatThenPdf("표 응답", true, new Error("network down"));

    render(<Chat />);
    await sendMessage("질문");
    fireEvent.click(await screen.findByRole("button", { name: /PDF 다운로드/ }));

    expect(await screen.findByText("network down")).toBeInTheDocument();
  });
});

/**
 * /api/chat은 report_available과 함께 응답하고, /api/report/email/presets는 presets를,
 * /api/report/email은 emailResponse로 응답한다.
 */
function mockChatThenEmail(
  reply: string,
  reportAvailable: boolean,
  emailResponse?: unknown,
  presets: string[] = []
) {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    if (String(url).includes("/api/report/email/presets")) {
      return Promise.resolve({ ok: true, json: async () => ({ presets }) });
    }
    if (String(url).includes("/api/report/email")) {
      if (emailResponse instanceof Error) return Promise.reject(emailResponse);
      return Promise.resolve(emailResponse);
    }
    return Promise.resolve({
      json: async () => ({ reply, tool_calls: [], report_available: reportAvailable }),
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function okEmailResponse(to: string[] = ["user@company.com"]) {
  return {
    ok: true,
    json: async () => ({ status: "sent", to }),
  };
}

describe("Chat - 이메일 발송 버튼", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("report_available이 true면 이메일로 보내기 버튼을 노출한다", async () => {
    mockChatThenEmail("표 응답입니다.", true);
    render(<Chat />);
    await sendMessage("월별 매출 표로 보여줘");

    expect(await screen.findByRole("button", { name: /이메일로 보내기/ })).toBeInTheDocument();
  });

  it("report_available이 false면 버튼을 노출하지 않는다", async () => {
    mockChatThenEmail("일반 답변입니다.", false);
    render(<Chat />);
    await sendMessage("안녕");

    await screen.findByText("일반 답변입니다.");
    expect(screen.queryByRole("button", { name: /이메일로 보내기/ })).not.toBeInTheDocument();
  });

  it("버튼 클릭 → 입력창 노출 → 이메일 입력 → 발송 클릭 시 /api/report/email로 올바른 바디를 보낸다", async () => {
    const reply = "표 응답입니다.";
    const fetchMock = mockChatThenEmail(reply, true, okEmailResponse());
    render(<Chat />);
    await sendMessage("월별 매출 알려줘");

    fireEvent.click(await screen.findByRole("button", { name: /이메일로 보내기/ }));

    const input = await screen.findByPlaceholderText("받는 사람 이메일");
    fireEvent.change(input, { target: { value: "user@company.com" } });
    fireEvent.click(screen.getByRole("button", { name: /발송/ }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/report/email", expect.anything());
    });
    const call = fetchMock.mock.calls.find((c) => String(c[0]) === "/api/report/email")!;
    const body = JSON.parse((call[1] as RequestInit).body as string);
    expect(body).toEqual({ content: reply, question: "월별 매출 알려줘", to: ["user@company.com"] });
  });

  it("200 성공 시 성공 상태로 전환된다", async () => {
    mockChatThenEmail("표 응답", true, okEmailResponse());
    render(<Chat />);
    await sendMessage("질문");

    fireEvent.click(await screen.findByRole("button", { name: /이메일로 보내기/ }));
    const input = await screen.findByPlaceholderText("받는 사람 이메일");
    fireEvent.change(input, { target: { value: "user@company.com" } });
    fireEvent.click(screen.getByRole("button", { name: /발송/ }));

    expect(await screen.findByText(/메일 발송됨/)).toBeInTheDocument();
  });

  it("403 오류 응답의 detail을 화면에 표시한다", async () => {
    mockChatThenEmail("표 응답", true, {
      ok: false,
      status: 403,
      json: async () => ({ detail: "허용되지 않은 이메일 도메인입니다: evil.com" }),
    });
    render(<Chat />);
    await sendMessage("질문");

    fireEvent.click(await screen.findByRole("button", { name: /이메일로 보내기/ }));
    const input = await screen.findByPlaceholderText("받는 사람 이메일");
    fireEvent.change(input, { target: { value: "user@evil.com" } });
    fireEvent.click(screen.getByRole("button", { name: /발송/ }));

    expect(
      await screen.findByText("허용되지 않은 이메일 도메인입니다: evil.com")
    ).toBeInTheDocument();
    // 실패해도 폼은 유지되어 다시 시도할 수 있어야 한다.
    expect(screen.getByPlaceholderText("받는 사람 이메일")).toBeInTheDocument();
  });

  it("503 오류 시 기능 미설정 안내 메시지를 표시한다", async () => {
    mockChatThenEmail("표 응답", true, {
      ok: false,
      status: 503,
      json: async () => ({ detail: "이메일 발송 기능이 설정되지 않았습니다." }),
    });
    render(<Chat />);
    await sendMessage("질문");

    fireEvent.click(await screen.findByRole("button", { name: /이메일로 보내기/ }));
    const input = await screen.findByPlaceholderText("받는 사람 이메일");
    fireEvent.change(input, { target: { value: "user@company.com" } });
    fireEvent.click(screen.getByRole("button", { name: /발송/ }));

    expect(
      await screen.findByText("이메일 발송 기능이 설정되지 않았습니다.")
    ).toBeInTheDocument();
  });

  it("네트워크 오류(fetch reject)에도 크래시하지 않고 기본 오류 문구로 폴백한다", async () => {
    mockChatThenEmail("표 응답", true, new Error("network down"));
    render(<Chat />);
    await sendMessage("질문");

    fireEvent.click(await screen.findByRole("button", { name: /이메일로 보내기/ }));
    const input = await screen.findByPlaceholderText("받는 사람 이메일");
    fireEvent.change(input, { target: { value: "user@company.com" } });
    fireEvent.click(screen.getByRole("button", { name: /발송/ }));

    expect(await screen.findByText("network down")).toBeInTheDocument();
  });
});

describe("Chat - 이메일 수신자 프리셋", () => {
  const PRESETS = ["sales@company.com", "manager@company.com"];

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** 이메일 폼을 펼치고 입력창을 돌려준다. */
  async function expandEmailForm() {
    fireEvent.click(await screen.findByRole("button", { name: /이메일로 보내기/ }));
    return screen.findByPlaceholderText("받는 사람 이메일");
  }

  function bodyOfEmailPost(fetchMock: ReturnType<typeof vi.fn>) {
    const call = fetchMock.mock.calls.find((c) => String(c[0]) === "/api/report/email")!;
    return JSON.parse((call[1] as RequestInit).body as string);
  }

  it("확장 시 프리셋을 조회하고 드롭다운 버튼을 노출한다", async () => {
    const fetchMock = mockChatThenEmail("표 응답", true, okEmailResponse(), PRESETS);
    render(<Chat />);
    await sendMessage("질문");
    await expandEmailForm();

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/report/email/presets");
    });
    expect(await screen.findByRole("button", { name: /자주 쓰는 수신자/ })).toBeInTheDocument();
  });

  it("프리셋이 0개면 드롭다운 없이 텍스트 입력만 보인다 (하위 호환)", async () => {
    mockChatThenEmail("표 응답", true, okEmailResponse(), []);
    render(<Chat />);
    await sendMessage("질문");
    await expandEmailForm();

    expect(screen.getByPlaceholderText("받는 사람 이메일")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /자주 쓰는 수신자/ })).not.toBeInTheDocument();
    });
  });

  it("프리셋 여러 개를 동시에 체크해 다중 수신자로 발송한다", async () => {
    const fetchMock = mockChatThenEmail("표 응답", true, okEmailResponse(PRESETS), PRESETS);
    render(<Chat />);
    await sendMessage("질문");
    await expandEmailForm();

    fireEvent.click(await screen.findByRole("button", { name: /자주 쓰는 수신자/ }));
    const sales = await screen.findByLabelText("sales@company.com");
    const manager = screen.getByLabelText("manager@company.com");
    fireEvent.click(sales);
    fireEvent.click(manager);
    expect(sales).toBeChecked();
    expect(manager).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: /^발송$/ }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/report/email", expect.anything())
    );
    expect(bodyOfEmailPost(fetchMock).to).toEqual(PRESETS);
  });

  it("프리셋 선택 + 직접 입력(콤마 구분)을 합치고 중복을 제거한다", async () => {
    const fetchMock = mockChatThenEmail("표 응답", true, okEmailResponse(), PRESETS);
    render(<Chat />);
    await sendMessage("질문");
    const input = await expandEmailForm();

    fireEvent.click(await screen.findByRole("button", { name: /자주 쓰는 수신자/ }));
    fireEvent.click(await screen.findByLabelText("sales@company.com"));
    // 직접 입력에 프리셋과 겹치는 주소(대소문자 다름)와 새 주소를 함께 넣는다.
    fireEvent.change(input, { target: { value: "Sales@Company.com, ceo@company.com" } });
    fireEvent.click(screen.getByRole("button", { name: /^발송$/ }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/report/email", expect.anything())
    );
    expect(bodyOfEmailPost(fetchMock).to).toEqual(["sales@company.com", "ceo@company.com"]);
  });

  it("체크 해제하면 수신자 목록에서 빠진다", async () => {
    const fetchMock = mockChatThenEmail("표 응답", true, okEmailResponse(), PRESETS);
    render(<Chat />);
    await sendMessage("질문");
    await expandEmailForm();

    fireEvent.click(await screen.findByRole("button", { name: /자주 쓰는 수신자/ }));
    const sales = await screen.findByLabelText("sales@company.com");
    const manager = screen.getByLabelText("manager@company.com");
    fireEvent.click(sales);
    fireEvent.click(manager);
    fireEvent.click(sales); // 해제
    expect(sales).not.toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: /^발송$/ }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/report/email", expect.anything())
    );
    expect(bodyOfEmailPost(fetchMock).to).toEqual(["manager@company.com"]);
  });

  it("프리셋도 직접 입력도 없으면 발송하지 않고 안내 메시지를 표시한다", async () => {
    const fetchMock = mockChatThenEmail("표 응답", true, okEmailResponse(), PRESETS);
    render(<Chat />);
    await sendMessage("질문");
    await expandEmailForm();

    fireEvent.click(screen.getByRole("button", { name: /^발송$/ }));

    expect(await screen.findByText("받는 사람 이메일을 입력해 주세요.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some((c) => String(c[0]) === "/api/report/email")).toBe(false);
  });

  it("성공 메시지에 실제 전송된 수신자 전체 목록을 보여준다", async () => {
    mockChatThenEmail("표 응답", true, okEmailResponse(PRESETS), PRESETS);
    render(<Chat />);
    await sendMessage("질문");
    const input = await expandEmailForm();

    fireEvent.click(await screen.findByRole("button", { name: /자주 쓰는 수신자/ }));
    fireEvent.click(await screen.findByLabelText("manager@company.com"));
    fireEvent.change(input, { target: { value: "ceo@company.com" } });
    fireEvent.click(screen.getByRole("button", { name: /^발송$/ }));

    expect(
      await screen.findByText("메일 발송됨 (manager@company.com, ceo@company.com)")
    ).toBeInTheDocument();
  });

  it("프리셋 주소라도 서버가 403을 주면 에러를 표시한다", async () => {
    mockChatThenEmail(
      "표 응답",
      true,
      {
        ok: false,
        status: 403,
        json: async () => ({ detail: "허용되지 않은 이메일 도메인입니다: company.com" }),
      },
      PRESETS
    );
    render(<Chat />);
    await sendMessage("질문");
    await expandEmailForm();

    fireEvent.click(await screen.findByRole("button", { name: /자주 쓰는 수신자/ }));
    fireEvent.click(await screen.findByLabelText("sales@company.com"));
    fireEvent.click(screen.getByRole("button", { name: /^발송$/ }));

    expect(
      await screen.findByText("허용되지 않은 이메일 도메인입니다: company.com")
    ).toBeInTheDocument();
    // 실패해도 폼은 유지되어 다시 시도할 수 있어야 한다.
    expect(screen.getByPlaceholderText("받는 사람 이메일")).toBeInTheDocument();
  });

  it("프리셋 조회가 실패해도 크래시 없이 직접 입력으로 발송할 수 있다", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/report/email/presets")) {
        return Promise.reject(new Error("presets down"));
      }
      if (String(url).includes("/api/report/email")) return Promise.resolve(okEmailResponse());
      return Promise.resolve({
        json: async () => ({ reply: "표 응답", tool_calls: [], report_available: true }),
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await sendMessage("질문");
    const input = await expandEmailForm();

    expect(screen.queryByRole("button", { name: /자주 쓰는 수신자/ })).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: "user@company.com" } });
    fireEvent.click(screen.getByRole("button", { name: /^발송$/ }));

    expect(await screen.findByText(/메일 발송됨 \(user@company\.com\)/)).toBeInTheDocument();
  });
});
