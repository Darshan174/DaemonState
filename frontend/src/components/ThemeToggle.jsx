import { useLayoutEffect, useState } from "react";
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
      className="relative flex h-9 w-9 items-center justify-center rounded-md
        border border-[#d9d9d0] dark:border-[#292925]
        bg-[#fbfbf6] dark:bg-[#141411]
        text-[#68685f] dark:text-[#b3b3a9]
        hover:border-[#68685f] hover:text-[#171713] dark:hover:border-[#77776e] dark:hover:text-[#f4f4ec]
        transition-all duration-300 ease-in-out
        focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#f7f7f2] dark:focus-visible:ring-offset-[#0d0d0b]"
    >
      <svg
        className={`absolute w-[18px] h-[18px] transition-all duration-500 ease-[cubic-bezier(0.34,1.56,0.64,1)] ${
          isDark
            ? "opacity-0 rotate-90 scale-0"
            : "opacity-100 rotate-0 scale-100"
        }`}
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="12" cy="12" r="5" />
        <line x1="12" y1="1" x2="12" y2="3" />
        <line x1="12" y1="21" x2="12" y2="23" />
        <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
        <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
        <line x1="1" y1="12" x2="3" y2="12" />
        <line x1="21" y1="12" x2="23" y2="12" />
        <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
        <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
      </svg>

      <svg
        className={`absolute w-[18px] h-[18px] transition-all duration-500 ease-[cubic-bezier(0.34,1.56,0.64,1)] ${
          isDark
            ? "opacity-100 rotate-0 scale-100"
            : "opacity-0 -rotate-90 scale-0"
        }`}
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
      </svg>
    </button>
  );
}
