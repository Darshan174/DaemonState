/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Archivo Variable", "Archivo", "system-ui", "-apple-system", "BlinkMacSystemFont", "Helvetica Neue", "Arial", "sans-serif"],
      },
      colors: {
        slate: {
          50: "#f7f7f2",
          100: "#f2f2eb",
          200: "#e1e1d8",
          300: "#bdbdb4",
          400: "#8a8a80",
          500: "#68685f",
          600: "#5c5c54",
          700: "#45453f",
          800: "#2a2a25",
          900: "#171713",
          950: "#0d0d0b",
        },
        brand: {
          50: "#fbfff0",
          100: "#f3ffc9",
          200: "#e8ff9c",
          300: "#d9ff68",
          400: "#c3ea4d",
          500: "#686d35",
          600: "#171713",
          700: "#2a2a21",
          800: "#3d3d33",
          900: "#545449",
        },
      },
      animation: {
        shimmer: "shimmer 2.5s linear infinite",
        "float": "float 6s ease-in-out infinite",
        "pulse-slow": "pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "blob": "blob 7s infinite",
        "marquee": "marquee 52s linear infinite",
      },
      keyframes: {
        shimmer: {
          from: { backgroundPosition: "0 0" },
          to: { backgroundPosition: "-200% 0" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-10px)" },
        },
        blob: {
          "0%": { transform: "translate(0px, 0px) scale(1)" },
          "33%": { transform: "translate(30px, -50px) scale(1.1)" },
          "66%": { transform: "translate(-20px, 20px) scale(0.9)" },
          "100%": { transform: "translate(0px, 0px) scale(1)" },
        },
        marquee: {
          "0%": { transform: "translate3d(0, 0, 0)" },
          "100%": { transform: "translate3d(-50%, 0, 0)" },
        }
      },
    },
  },
  plugins: [],
};
