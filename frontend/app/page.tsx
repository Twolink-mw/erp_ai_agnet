import Chat from "../components/Chat";

export default function Page() {
  return (
    <main
      style={{
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        background: "var(--bg)",
        overflow: "hidden",
      }}
    >
      <Chat />
    </main>
  );
}
