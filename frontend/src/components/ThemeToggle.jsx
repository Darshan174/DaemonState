import { useLayoutEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "../context/ThemeContext";

const THEME_STORAGE_KEY = "ce-theme";

function getDocumentTheme(fallback) {
  if (typeof document === "undefined") return fallback;
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function forceDocumentTheme(nextTheme) {
  if (typeof document === "undefined") return;

  const resolvedTheme = nextTheme === "dark" ? "dark" : "light";
  document.documentElement.classList.toggle("dark", resolvedTheme === "dark");
  document.documentElement.style.colorScheme = resolvedTheme;

  try {
    localStorage.setItem(THEME_STORAGE_KEY, resolvedTheme);
  } catch {
    // Keep the visual state even if storage is unavailable.
  }
}

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [resolvedTheme, setResolvedTheme] = useState(() => getDocumentTheme(theme));
  const isDark = resolvedTheme === "dark";

  useLayoutEffect(() => {
    setResolvedTheme(getDocumentTheme(theme));
  }, [theme]);

  const handleToggle = (event) => {
    event.preventDefault();
    event.stopPropagation();

    const nextTheme = getDocumentTheme(theme) === "dark" ? "light" : "dark";
    forceDocumentTheme(nextTheme);
    setResolvedTheme(nextTheme);
    setTheme(nextTheme);
  };

  return (
    <button
      id="theme-toggle-btn"
      type="button"
      onClick={handleToggle}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      data-theme={resolvedTheme}
      className="icon-button relative overflow-hidden"
    >
      <Sun
        className={`absolute h-[17px] w-[17px] transition-all duration-500 ease-[cubic-bezier(0.34,1.56,0.64,1)] ${
          isDark
            ? "opacity-0 rotate-90 scale-0"
            : "opacity-100 rotate-0 scale-100"
        }`}
      />

      <Moon
        className={`absolute h-[17px] w-[17px] transition-all duration-500 ease-[cubic-bezier(0.34,1.56,0.64,1)] ${
          isDark
            ? "opacity-100 rotate-0 scale-100"
            : "opacity-0 -rotate-90 scale-0"
        }`}
      />
    </button>
  );
}
