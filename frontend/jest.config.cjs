/**
 * Jest configuration.
 *
 * - ts-jest compiles TypeScript with `tsconfig.jest.json` (CommonJS for Jest).
 * - `@/api/client` is redirected to a lightweight mock because the real module
 *   reads `import.meta.env`, which is not available under CommonJS.
 * - MUI/Emotion render fine under jsdom; `@testing-library/jest-dom` adds the
 *   custom matchers.
 *
 * @type {import('jest').Config}
 */
module.exports = {
  testEnvironment: 'jsdom',
  roots: ['<rootDir>/src'],
  testMatch: ['<rootDir>/src/**/*.test.ts', '<rootDir>/src/**/*.test.tsx'],
  setupFilesAfterEnv: ['<rootDir>/src/test/setup.ts'],
  transform: {
    '^.+\\.(t|j)sx?$': [
      'ts-jest',
      {
        tsconfig: '<rootDir>/tsconfig.jest.json',
        diagnostics: { warnOnly: false },
      },
    ],
  },
  moduleNameMapper: {
    '^@/api/client$': '<rootDir>/src/test/mocks/client.ts',
    '^@/(.*)$': '<rootDir>/src/$1',
    '\\.(css|less|scss|sass)$': 'identity-obj-proxy',
  },
  clearMocks: true,
  restoreMocks: true,
  collectCoverageFrom: [
    'src/**/*.{ts,tsx}',
    '!src/**/*.d.ts',
    '!src/main.tsx',
    '!src/test/**',
  ],
  coverageDirectory: 'coverage',
};
