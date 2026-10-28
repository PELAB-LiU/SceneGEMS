import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Setup for the `*.dom.test.tsx` files only (see the `dom` project in vite.config.ts). Testing Library
// cleans up on its own only when vitest globals are on, which they are not here.
afterEach(() => {
  cleanup()
  window.localStorage.clear()
})
