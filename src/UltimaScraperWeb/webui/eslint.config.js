import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
  {
    // Behind the WebUI server each backend lives under /b/{connection}; a bare
    // '/api/...' would always reach the default backend instead.
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/api/http.ts', 'src/api/webui.ts', '**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "CallExpression[callee.name=/^(fetch|authFetch)$/] > Literal.arguments:first-child[value=/^\\/(api|ws)\\//]",
          message: 'Wrap backend paths in apiUrl() so they reach the active backend.',
        },
        {
          selector: "CallExpression[callee.name=/^(fetch|authFetch)$/] > TemplateLiteral.arguments:first-child > TemplateElement:first-child[value.raw=/^\\/(api|ws)\\//]",
          message: 'Wrap backend paths in apiUrl() so they reach the active backend.',
        },
      ],
    },
  },
  {
    files: ['src/hooks/**/*.{ts,tsx}', 'src/app/bootstrap/**/*.{ts,tsx}'],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
])
