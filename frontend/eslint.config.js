// Only the two React-hooks rules for now (P13.60): the point is to see stale closures and
// missing effect dependencies, not to restyle the code. `npm run lint` reports; nothing is
// auto-fixed — changing an effect's dependencies changes when it runs, so fix them one by one.
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'

export default [
  { ignores: ['dist/**', 'node_modules/**'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: { parser: tseslint.parser, parserOptions: { ecmaFeatures: { jsx: true } } },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
]
