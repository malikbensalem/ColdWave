// craco.config.js
const path = require("path");
require("dotenv").config();

// Check if we're in development/preview mode (not production build)
// Craco sets NODE_ENV=development for start, NODE_ENV=production for build
const isDevServer = process.env.NODE_ENV !== "production";

// Environment variable overrides
const config = {
  enableHealthCheck: process.env.ENABLE_HEALTH_CHECK === "true",
};

// Conditionally load health check modules only if enabled
let WebpackHealthPlugin;
let setupHealthEndpoints;
let healthPluginInstance;

if (config.enableHealthCheck) {
  WebpackHealthPlugin = require("./plugins/health-check/webpack-health-plugin");
  setupHealthEndpoints = require("./plugins/health-check/health-endpoints");
  healthPluginInstance = new WebpackHealthPlugin();
}

let webpackConfig = {
  eslint: {
    configure: {
      extends: ["plugin:react-hooks/recommended"],
      rules: {
        "react-hooks/rules-of-hooks": "error",
        "react-hooks/exhaustive-deps": "warn",
      },
    },
  },
  webpack: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
    configure: (webpackConfig) => {

      // Add ignored patterns to reduce watched directories
        webpackConfig.watchOptions = {
          ...webpackConfig.watchOptions,
          ignored: [
            '**/node_modules/**',
            '**/.git/**',
            '**/build/**',
            '**/dist/**',
            '**/coverage/**',
            '**/public/**',
        ],
      };

      // Add health check plugin to webpack if enabled
      if (config.enableHealthCheck && healthPluginInstance) {
        webpackConfig.plugins.push(healthPluginInstance);
      }
      return webpackConfig;
    },
  },
};

webpackConfig.devServer = (devServerConfig) => {
  // react-scripts 5 emits a webpack-dev-server v4 options object, but v5 is installed
  // (pinned via resolutions). Translate the renamed/removed keys to the v5 schema.
  const legacyBefore = devServerConfig.onBeforeSetupMiddleware;
  const legacyAfter = devServerConfig.onAfterSetupMiddleware;
  const originalSetupMiddlewares = devServerConfig.setupMiddlewares;

  if ("https" in devServerConfig) {
    if (devServerConfig.https) devServerConfig.server = "https";
    delete devServerConfig.https;
  }

  const VALID_KEYS = [
    "allowedHosts", "bonjour", "client", "compress", "devMiddleware", "headers",
    "historyApiFallback", "host", "hot", "ipc", "liveReload", "onListening", "open",
    "port", "proxy", "server", "app", "setupExitSignals", "setupMiddlewares",
    "static", "watchFiles", "webSocketServer",
  ];
  Object.keys(devServerConfig).forEach((k) => {
    if (!VALID_KEYS.includes(k)) delete devServerConfig[k];
  });

  devServerConfig.allowedHosts = "all";

  devServerConfig.setupMiddlewares = (middlewares, devServer) => {
    if (typeof legacyBefore === "function") legacyBefore(devServer);
    if (originalSetupMiddlewares) {
      middlewares = originalSetupMiddlewares(middlewares, devServer);
    }
    if (typeof legacyAfter === "function") legacyAfter(devServer);
    if (config.enableHealthCheck && setupHealthEndpoints && healthPluginInstance) {
      setupHealthEndpoints(devServer, healthPluginInstance);
    }
    return middlewares;
  };

  return devServerConfig;
};

// Wrap with visual edits (automatically adds babel plugin, dev server, and overlay in dev mode)
if (isDevServer) {
  try {
    const { withVisualEdits } = require("@emergentbase/visual-edits/craco");
    webpackConfig = withVisualEdits(webpackConfig);
  } catch (err) {
    if (err.code === 'MODULE_NOT_FOUND' && err.message.includes('@emergentbase/visual-edits/craco')) {
      console.warn(
        "[visual-edits] @emergentbase/visual-edits not installed — visual editing disabled."
      );
    } else {
      throw err;
    }
  }
}

module.exports = webpackConfig;
