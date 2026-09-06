const base = require('./playwright.config');
module.exports = {
  ...base,
  reporter: [['list']],
  projects: base.projects.map((project) => ({
    ...project,
    use: {
      ...project.use,
      launchOptions: {
        ...(project.use && project.use.launchOptions ? project.use.launchOptions : {}),
        executablePath: '/usr/bin/chromium-browser',
      },
    },
  })),
};
