import type { Plugin } from "vite";

/** Dev-only Vite plugin: start Docusaurus on the first request to /docs. */
export default function lazyDocusaurus(): Plugin;
