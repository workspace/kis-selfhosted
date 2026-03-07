import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // P2: Frontend 3001, Backend 8002
  output: process.env.NEXT_BUILD_STANDALONE ? 'standalone' : undefined,
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || '',
  trailingSlash: true,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.BACKEND_URL || 'http://localhost:8002'}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
