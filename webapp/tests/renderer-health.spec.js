const {_electron: electron} = require('playwright');
const {strict: assert} = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');


const webappRoot = path.resolve(__dirname, '..');
const rendererIndex = path.join(webappRoot, 'packages', 'renderer', 'dist', 'index.html');
const harnessPath = path.join(__dirname, 'renderer-harness');


(async () => {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'alas-renderer-'));
  let electronApp;
  try {
    electronApp = await electron.launch({
      args: [harnessPath, `--user-data-dir=${userData}`],
      cwd: webappRoot,
      env: {...process.env, ALAS_RENDERER_INDEX: rendererIndex},
      timeout: 30000,
    });

    const page = await electronApp.firstWindow();
    const pageErrors = [];
    const consoleErrors = [];
    page.on('pageerror', error => pageErrors.push(String(error)));
    page.on('console', message => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });

    await page.reload({waitUntil: 'load'});
    await page.waitForTimeout(250);
    const state = await page.evaluate(() => ({
      appHtml: document.querySelector('#app')?.innerHTML.trim() || '',
      iframeSrc: document.querySelector('iframe')?.getAttribute('src') || '',
      hasHeader: document.querySelector('.app-header') !== null,
    }));

    assert.strictEqual(
      pageErrors.length,
      0,
      `Renderer page errors:\n${pageErrors.join('\n')}\nConsole errors:\n${consoleErrors.join('\n')}`,
    );
    assert.ok(
      state.appHtml,
      `Renderer root #app is empty (white GUI). Console errors:\n${consoleErrors.join('\n')}`,
    );
    assert.ok(state.hasHeader, 'Renderer did not create the Electron window header');
    assert.strictEqual(
      state.iframeSrc,
      'http://127.0.0.1:22267',
      'Renderer did not create the configured WebUI iframe',
    );

    console.log('PASS: packaged Electron renderer is not blank');
  } finally {
    if (electronApp) await electronApp.close();
    for (let attempt = 0; attempt < 5; attempt += 1) {
      try {
        fs.rmSync(userData, {recursive: true, force: true});
        break;
      } catch (error) {
        if (attempt === 4) {
          console.warn(`Unable to remove temporary Electron user data: ${error}`);
          break;
        }
        await new Promise(resolve => setTimeout(resolve, 200));
      }
    }
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
