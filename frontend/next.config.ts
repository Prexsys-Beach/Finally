import type { NextConfig } from "next";

const dev = process.env.NODE_ENV === "development";

const config: NextConfig = {
  // Production is a static export served by FastAPI. `next dev` proxies to it.
  output: dev ? undefined : "export",
  images: { unoptimized: true },
  ...(dev && {
    rewrites: async () => [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }],
  }),
};

export default config;
