/** @type {import('tailwindcss').Config} */
const tokens = ['bg', 'surface', 'surface2', 'line', 'fg', 'fg2', 'fg3', 'accent', 'accentsoft', 'onaccent',
  'ok', 'oksoft', 'warn', 'warnsoft', 'hot', 'hotsoft', 'acet', 'acetsoft', 'ibu', 'ibusoft',
  'mom', 'momsoft', 'dad', 'dadsoft', 'rx', 'rxsoft', 'onrx'];
const cssVar = { surface2: 'surface-2', fg2: 'fg-2', fg3: 'fg-3', accentsoft: 'accent-soft', onaccent: 'on-accent',
  oksoft: 'ok-soft', warnsoft: 'warn-soft', hotsoft: 'hot-soft', acetsoft: 'acet-soft', ibusoft: 'ibu-soft',
  momsoft: 'mom-soft', dadsoft: 'dad-soft', rxsoft: 'rx-soft', onrx: 'on-rx' };

module.exports = {
  content: ['../templates/**/*.html', '../sicklog/**/*.py', '../static/js/**/*.js'],
  // 템플릿에서 {{ color }}soft 처럼 조합하는 색 클래스
  safelist: [{ pattern: /^(bg|text|border)-(ok|warn|hot|acet|ibu|mom|dad|accent)(soft)?$/ }],
  theme: {
    extend: {
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Apple SD Gothic Neo"', '"Pretendard Variable"', 'Pretendard',
          'system-ui', 'sans-serif'],
      },
      colors: Object.fromEntries(tokens.map(t => [t, `var(--${cssVar[t] || t})`])),
    },
  },
};
