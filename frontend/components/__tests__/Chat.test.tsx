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
