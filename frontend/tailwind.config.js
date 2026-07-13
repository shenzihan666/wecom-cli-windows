/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{vue,js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        wecom: {
          primary: "#1AAD19",
          secondary: "#07C160",
          dark: "#0D1117",
          darker: "#010409",
          surface: "#161B22",
          border: "#30363D",
          text: "#C9D1D9",
          muted: "#8B949E",
          accent: "#58A6FF",
        },
      },
      fontFamily: {
        sans: ["JetBrains Mono", "SF Mono", "Menlo", "monospace"],
        display: ["Space Grotesk", "system-ui", "sans-serif"],
      },
      animation: {
        "fade-in": "fadeIn 0.2s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { transform: "translateY(10px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
      },
    },
  },
  plugins: [],
};
