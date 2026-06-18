/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          50:  '#e6f2ff',
          100: '#bfddff',
          200: '#80bbff',
          300: '#4099ff',
          400: '#0080FF',
          500: '#0080FF',
          600: '#0061CC',
          700: '#004899',
        },
        'do-blue':   '#0080FF',
        'do-navy':   '#1B2A4A',
        'do-navy-light': '#243556',
        'do-grey-100': '#F6F8FA',
        'do-grey-200': '#EAECEF',
        'do-grey-400': '#8F9BB3',
        'do-grey-700': '#3D4F6B',
        'do-green':  '#1AAB5F',
        'do-red':    '#C43227',
        'do-yellow': '#FFCB00',
        'do-purple': '#6B4FBB',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        DEFAULT: '6px',
        md: '8px',
        lg: '12px',
      },
    },
  },
  plugins: [],
}
