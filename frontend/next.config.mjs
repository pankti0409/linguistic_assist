/** @type {import('next').NextConfig} */
const BACKEND = (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8765').replace(/\/$/, '')

const nextConfig = {
  images: { unoptimized: true },
  // Same-origin proxy to the local backend, which deliberately sends no CORS headers.
  async rewrites() {
    return [{ source: '/backend/:path*', destination: `${BACKEND}/:path*` }]
  },
}

export default nextConfig
