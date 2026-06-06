const { app } = require('electron');
console.log("App is:", app);
if (app) {
  app.whenReady().then(() => {
    console.log("Ready!");
    app.quit();
  });
} else {
  console.log("App is undefined!");
  process.exit(1);
}
