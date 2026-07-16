import type { ReactNode } from "react";
import { ThemeProvider } from "../components/ThemeProvider";

export const metadata = {
  title: "ERP 매출 분석 챗봇",
  description: "사내 ERP 매출 뷰 데이터를 분석하는 대화형 어시스턴트",
};

// Applies the stored theme before paint to avoid a flash of the wrong theme.
const themeInitScript = `
(function() {
  try {
    var t = localStorage.getItem('theme') || 'system';
    var dark = t === 'dark' || (t === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
        <style>{`
          :root {
            --bg: #262624;
            --bubble: #33322f;
            --border: #3a3935;
            --text: #e8e6e1;
            --muted: #8c8a85;
            --accent: #c96442;
          }
          :root[data-theme="light"] {
            --bg: #faf9f5;
            --bubble: #eeece6;
            --border: #dedcd3;
            --text: #1f1e1d;
            --muted: #726e69;
            --accent: #c96442;
          }
          :root[data-theme="dark"] {
            --bg: #262624;
            --bubble: #33322f;
            --border: #3a3935;
            --text: #e8e6e1;
            --muted: #8c8a85;
            --accent: #c96442;
          }
        `}</style>
      </head>
      <body
        style={{
          margin: 0,
          fontFamily: "system-ui, sans-serif",
          background: "var(--bg)",
          height: "100vh",
          overflow: "hidden",
        }}
      >
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
