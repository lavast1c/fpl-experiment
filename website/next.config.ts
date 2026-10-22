import path from "node:path";
import type { NextConfig } from "next";

const config: NextConfig = {
  // The website lives in a subfolder of the experiment repo; trace files from here.
  outputFileTracingRoot: path.join(__dirname),
};

export default config;
