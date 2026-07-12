import path from "node:path";
import vue from "@vitejs/plugin-vue";
import autoprefixer from "autoprefixer";
import tailwind from "tailwindcss";
import { defineConfig } from "vite";

export default defineConfig({
	css: {
		postcss: {
			plugins: [tailwind(), autoprefixer()],
		},
	},
	plugins: [vue()],
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "./src"),
		},
	},
	server: {
		host: "0.0.0.0",
		port: 5173,
		allowedHosts: ["localhost", "127.0.0.1"],
		headers: {
			"Content-Security-Policy":
				"default-src 'self'; base-uri 'self'; connect-src 'self' ws: wss:; font-src 'self' data:; frame-ancestors 'none'; img-src 'self' data: blob:; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'",
			"Referrer-Policy": "no-referrer",
			"X-Content-Type-Options": "nosniff",
			"X-Frame-Options": "DENY",
		},
		proxy: {
			"/api": {
				target: "http://backend:8000",
				changeOrigin: true,
				rewrite: (path) => path.replace(/^\/api/, ""),
			},
			"/ws": {
				target: "ws://backend:8000",
				ws: true,
				changeOrigin: true,
				rewrite: (path) => path.replace(/^\/ws/, ""),
			},
		},
	},
});
