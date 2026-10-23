export default {
  displayName: 'webapp-whatsapp',
  preset: '../../../jest.preset.js',
  testEnvironment: 'jsdom',
  transform: {
    '^(?!.*\\.(js|jsx|ts|tsx|css|json)$)': '@nx/react/plugins/jest',
    '^.+\\.[tj]sx?$': ['babel-jest', { presets: ['@nx/react/babel'] }],
  },
  transformIgnorePatterns: ['/node_modules/(?!(@iconify-icons|react-markdown)/)'],
  // Same mocks as the other libraries: pnpm doesn't put react-markdown where Jest can load it.
  moduleNameMapper: {
    'react-markdown': '<rootDir>/../webapp-core/src/tests/mocks/reactMarkdown.tsx',
    'remark-gfm': '<rootDir>/../webapp-core/src/tests/mocks/remarkGfm.ts',
  },
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx'],
  coverageDirectory: '../../../coverage/packages/webapp-libs/webapp-whatsapp',
  setupFilesAfterEnv: ['./src/tests/setupTests.ts'],
};
