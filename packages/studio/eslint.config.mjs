import config from "../../apps/web/eslint.config.mjs";
export default [...config, { settings: { next: { rootDir: "../../apps/web/" } } }];
