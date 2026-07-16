"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type ThemeSetting = "system" | "light" | "dark";
type ResolvedTheme = "light" | "dark";

const ThemeContext = createContext<{
  theme: ThemeSetting;
  resolvedTheme: ResolvedTheme;
  setTheme: (t: ThemeSetting) => void;
} | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeSetting>("system");
  const [systemDark, setSystemDark] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem("theme");
    if (stored === "light" || stored === "dark" || stored === "system") {
      setThemeState(stored);
    }
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setSystemDark(mq.matches);
    const onChange = () => setSystemDark(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const resolvedTheme: ResolvedTheme = theme === "system" ? (systemDark ? "dark" : "light") : theme;

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolvedTheme);
  }, [resolvedTheme]);

  function setTheme(t: ThemeSetting) {
    setThemeState(t);
    localStorage.setItem("theme", t);
  }

  return <ThemeContext.Provider value={{ theme, resolvedTheme, setTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
