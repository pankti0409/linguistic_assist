import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.sampark.app',
  appName: 'SAMPARK',
  webDir: 'dist',
  server: {
    url: 'http://10.181.9.214:5173',
    cleartext: true,
  },
};

export default config;
