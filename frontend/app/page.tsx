import Chat from "../components/Chat";

export default function Page() {
  return (
    <main style={{ maxWidth: 860, margin: "0 auto", padding: "24px 16px" }}>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>ERP 매출 분석 챗봇</h1>
      <p style={{ color: "#666", marginTop: 0, marginBottom: 20, fontSize: 14 }}>
        매출 관련 뷰 데이터에 한해 질문할 수 있습니다. 예) "지난달 대비 이번달 매출 증감을 고객별로 보여줘"
      </p>
      <Chat />
    </main>
  );
}
