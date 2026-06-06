const electron = require('electron');
console.log("Electron:", Object.keys(electron));
console.log("App:", electron.app);
if (electron.app) {
  electron.app.whenReady().then(() => {
    console.log("Ready!");
    electron.app.quit();
  });
} else {
  console.log("No app object found!");
  process.exit(1);
}
