module.exports = {
  async onPreBuild({ netlifyConfig }) {
    const { configureProxy } = await import("../prepare-netlify.mjs");
    configureProxy(netlifyConfig);
  },
};
