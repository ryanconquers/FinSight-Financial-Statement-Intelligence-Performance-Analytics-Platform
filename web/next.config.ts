import type { NextConfig } from "next";

const isGitHubPagesBuild = process.env.GITHUB_PAGES === "true";
const repositoryName = "FinSight-Financial-Statement-Intelligence-Performance-Analytics-Platform";

const nextConfig: NextConfig = {
  ...(isGitHubPagesBuild
    ? { output: "export" as const, basePath: `/${repositoryName}`, trailingSlash: true }
    : {}),
};

export default nextConfig;
