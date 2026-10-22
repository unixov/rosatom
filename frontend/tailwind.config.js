export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#080d18',
        panel: '#0d1422',
        cyan: '#48d9ec',
        violet: '#9a80ff',
        success: '#55d7a0',
      },
      fontFamily: {
        sans: ['DM Sans', 'sans-serif'],
        mono: ['DM Mono', 'monospace'],
        display: ['Manrope', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
