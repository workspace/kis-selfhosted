import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // P1: Frontend 3000, Backend 8000
  output: process.env.NEXT_BUILD_STANDALONE ? 'standalone' : undefined,
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || '',
  trailingSlash: true,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.BACKEND_URL || 'http://localhost:8000'}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
