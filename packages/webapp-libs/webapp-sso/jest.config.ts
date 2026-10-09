export default {
  displayName: 'webapp-sso',
  preset: '../../../jest.preset.js',
  transform: {
    '^(?!.*\\.(js|jsx|ts|tsx|css|json)$)': '@nx/react/plugins/jest',
    '^.+\\.[tj]sx?$': ['babel-jest', { presets: ['@nx/react/babel'] }],
  },
  transformIgnorePatterns: ['/node_modules/(?!(@iconify-icons|react-markdown)/)'],
  globals: {
    'ts-jest': {
      tsconfig: '<rootDir>/tsconfig.spec.json',
    },
  },
  // pnpm doesn't hoist react-markdown to the root node_modules, so use webapp-core's mocks like the
  // other libraries do.
  moduleNameMapper: {
    'react-markdown': '<rootDir>/../webapp-core/src/tests/mocks/reactMarkdown.tsx',
    'remark-gfm': '<rootDir>/../webapp-core/src/tests/mocks/remarkGfm.ts',
  },
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx'],
  coverageReporters: ['lcov'],
  coveragePathIgnorePatterns: ['/node_modules/', '.*.svg'],
  setupFilesAfterEnv: ['./src/tests/setupTests.ts'],
  watchPlugins: ['jest-watch-typeahead/filename', 'jest-watch-typeahead/testname'],
};

