const {strict: assert} = require('assert');
const {spawnSync} = require('child_process');
const fs = require('fs');
const Module = require('module');
const path = require('path');
const typescript = require('typescript');
const yaml = require('yaml');


function requireTypeScript(filename) {
  const source = fs.readFileSync(filename, 'utf8');
  const compiled = typescript.transpileModule(source, {
    compilerOptions: {
      esModuleInterop: true,
      module: typescript.ModuleKind.CommonJS,
      target: typescript.ScriptTarget.ES2020,
    },
    fileName: filename,
  });
  const loaded = new Module(filename, module);
  loaded.filename = filename;
  loaded.paths = Module._nodeModulePaths(path.dirname(filename));
  loaded._compile(compiled.outputText, filename);
  return loaded.exports;
}


const pythonEnvModule = path.resolve(__dirname, '../packages/main/src/python-env.ts');
const {buildPythonEnv} = requireTypeScript(pythonEnvModule);
const alasPathModule = path.resolve(__dirname, '../packages/main/src/alas-path.ts');
const {resolveAlasPath} = requireTypeScript(alasPathModule);


function replacePath(env, value) {
  const result = {...env};
  for (const key of Object.keys(result)) {
    if (key.toLowerCase() === 'path') delete result[key];
  }
  result.PATH = value;
  return result;
}


const repoRoot = path.resolve(__dirname, '..', '..');
const packagedExecutable = path.join(repoRoot, 'webapp', 'dist', 'win-unpacked', 'alas.exe');
const packagedWorkingDirectory = path.dirname(packagedExecutable);
assert.strictEqual(
  resolveAlasPath(packagedExecutable, packagedWorkingDirectory),
  repoRoot,
  'A directly launched packaged executable must locate the repository root without relying on cwd',
);

const deploy = yaml.parse(fs.readFileSync(path.join(repoRoot, 'config', 'deploy.yaml'), 'utf8'));
const configuredPython = deploy.Deploy.Python.PythonExecutable;
const pythonPath = path.isAbsolute(configuredPython)
  ? configuredPython
  : path.resolve(repoRoot, configuredPython);
const pythonRoot = path.dirname(pythonPath);

const minimalPath = process.platform === 'win32'
  ? path.join(process.env.SystemRoot || 'C:\\Windows', 'System32')
  : '/usr/bin:/bin';
const cleanEnv = replacePath(process.env, minimalPath);
const fixedEnv = buildPythonEnv(pythonPath, cleanEnv);
const fixedPath = fixedEnv.PATH.split(path.delimiter);

assert.deepStrictEqual(
  fixedPath.slice(0, 3).map(item => path.normalize(item)),
  [
    pythonRoot,
    path.join(pythonRoot, 'Scripts'),
    path.join(pythonRoot, 'Library', 'bin'),
  ].map(item => path.normalize(item)),
  'Python runtime directories must be prepended in dependency-search order',
);
assert.strictEqual(fixedPath[3], minimalPath, 'The existing process PATH must be preserved');

if (process.platform === 'win32' && fs.existsSync(pythonPath)) {
  const args = ['-c', 'import ssl; import uvicorn; import pywebio; print("IMPORT_OK")'];
  const raw = spawnSync(pythonPath, args, {cwd: repoRoot, env: cleanEnv, encoding: 'utf8'});
  assert.notStrictEqual(raw.status, 0, 'The clean Explorer-like PATH must reproduce the broken startup fixture');

  const fixed = spawnSync(pythonPath, args, {cwd: repoRoot, env: fixedEnv, encoding: 'utf8'});
  assert.strictEqual(fixed.status, 0, `Electron child environment failed: ${fixed.stderr}`);
  assert.match(fixed.stdout, /IMPORT_OK/);
}

console.log('PASS: Electron child environment initializes the configured Python runtime');
