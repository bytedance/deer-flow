export default {
  testEnvironment: 'jsdom',
  roots: ['<rootDir>'],
  testMatch: [
    '**/tests/**/*.test.ts',
    '**/tests/**/*.test.tsx',
  ],
  testPathIgnorePatterns: ['/node_modules/', '/.next/'],
  moduleNameMapper: {
    '^~/env$': '<rootDir>/tests/__mocks__/env-mock.ts',
    '^~(.*)$': '<rootDir>/src$1',
    '\\.(css|less|scss|sass)$': 'identity-obj-proxy',
    '\\.(jpg|jpeg|png|gif|svg)$': '<rootDir>/tests/__mocks__/fileMock.js',
    '^~/core/store/store$': '<rootDir>/tests/__mocks__/store-mock.ts',
  },
  collectCoverageFrom: [
    'src/**/*.{ts,tsx}',
    '!src/**/*.d.ts',
    '!src/**/*.stories.tsx',
    '!src/**/index.{ts,tsx}',
  ],
  setupFilesAfterEnv: [],
  transform: {
    '^.+\\.tsx?$': ['ts-jest', {
      useESM: true,
      tsconfig: {
        jsx: 'react-jsx',
        esModuleInterop: true,
        allowSyntheticDefaultImports: true,
      },
    }],
  },
  // The following packages are ESM-only or otherwise require transformation by Jest.
  // If you encounter "SyntaxError: Cannot use import statement outside a module" or similar errors
  // for a dependency, add it to this list. See: https://jestjs.io/docs/configuration#transformignorepatterns-arraystring
  // 
  // Packages included:
  // - framer-motion: ESM-only
  // - nanoid: ESM-only
  // - @tiptap: ESM-only
  // - lowlight: ESM-only
  // - highlight.js: ESM-only
  // - zustand: ESM-only
  // - sonner: ESM-only
  // - next-intl: ESM-only
  // - immer: ESM-only
  // - use-debounce: ESM-only
  // - use-stick-to-bottom: ESM-only
  transformIgnorePatterns: [
    'node_modules/(?!(framer-motion|nanoid|@tiptap|lowlight|highlight\\.js|zustand|sonner|next-intl|immer|use-debounce|use-stick-to-bottom)/)',
  ],
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx'],
  extensionsToTreatAsEsm: ['.ts', '.tsx'],
};
