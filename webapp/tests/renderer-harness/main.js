const {app, BrowserWindow} = require('electron');


const rendererIndex = process.env.ALAS_RENDERER_INDEX;
if (!rendererIndex) throw new Error('ALAS_RENDERER_INDEX is required');

app.disableHardwareAcceleration();
app.whenReady().then(() => {
  const window = new BrowserWindow({
    show: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
    },
  });
  window.loadFile(rendererIndex);
});

app.on('window-all-closed', () => app.quit());
