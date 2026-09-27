interface ImportMetaEnv {
	readonly VITE_API_BASE_URL?: string;
	readonly VITE_MAP_STYLE_URL?: string;
	readonly VITE_API_TOKEN?: string;
	readonly VITE_SATELLITE_TILES_URL?: string;
}

interface ImportMeta {
	readonly env: ImportMetaEnv;
}
