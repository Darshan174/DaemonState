import { createContext, useContext, useLayoutEffect, useMemo, useState } from "react";

const ThemeContext = createContext();
const THEME_STORAGE_KEY = "ce-theme";

function isTheme(value) {
  return value === "light" || value === "dark";
}

function getInitialTheme() {
  if (typeof window === "undefined") return "dark";

  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (isTheme(stored)) return stored;
  } catch {
    return "dark";
  }

  return "dark";
}

function applyTheme(nextTheme) {
  if (typeof document === "undefined") return;

  const resolvedTheme = isTheme(nextTheme) ? nextTheme : "light";
  const root = document.documentElement;

  root.classList.toggle("dark", resolvedTheme === "dark");
  root.style.colorScheme = resolvedTheme;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", resolvedTheme === "dark" ? "#000000" : "#ffffff");

  try {
    localStorage.setItem(THEME_STORAGE_KEY, resolvedTheme);
  } catch {
    // The current page still receives the theme class if storage is blocked.
  }
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(getInitialTheme);

  useLayoutEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const value = useMemo(() => {
    const setResolvedTheme = (nextTheme) => {
      const resolvedTheme = isTheme(nextTheme) ? nextTheme : "light";
      applyTheme(resolvedTheme);
      setTheme(resolvedTheme);
    };

    const toggleTheme = () => {
      const currentTheme =
        typeof document !== "undefined" && document.documentElement.classList.contains("dark")
          ? "dark"
          : theme;
      setResolvedTheme(currentTheme === "dark" ? "light" : "dark");
    };

    return { theme, setTheme: setResolvedTheme, toggleTheme };
  }, [theme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}
