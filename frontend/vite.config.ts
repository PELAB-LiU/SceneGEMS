import { lezer } from '@lezer/generator/rollup'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import lazyDocusaurus from './scripts/vite-plugin-lazy-docusaurus.mjs'

// https://vite.dev/config/
export default defineConfig({
  plugins: [lezer(), react(), lazyDocusaurus()],
  server: {
    host: true,
  },
  test: {
    // Two projects: the pure tests keep the node environment, only `*.dom.test.tsx` files get a DOM.
    projects: [
      {
        extends: true,
        test: {
          name: 'node',
          environment: 'node',
          include: ['src/**/*.test.{ts,tsx}'],
          exclude: ['src/**/*.dom.test.tsx'],
        },
      },
      {
        extends: true,
        test: {
          name: 'dom',
          environment: 'jsdom',
          include: ['src/**/*.dom.test.tsx'],
          setupFiles: ['src/test/domSetup.ts'],
        },
      },
    ],
  },
})
