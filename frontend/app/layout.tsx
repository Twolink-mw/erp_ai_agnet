import type { ReactNode } from "react";

export const metadata = {
  title: "ERP 매출 분석 챗봇",
  description: "사내 ERP 매출 뷰 데이터를 분석하는 대화형 어시스턴트",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif", background: "#f5f6f8" }}>
        {children}
      </body>
    </html>
  );
}
