import {alasPath, pythonPath} from '/@/config';
import {buildPythonEnv} from '/@/python-env';

const {PythonShell} = require('python-shell');
const treeKill = require('tree-kill');


export class PyShell extends PythonShell {
  constructor(script: string, args: Array<string> = []) {
    const options = {
      mode: 'text',
      args: args,
      pythonPath: pythonPath,
      scriptPath: alasPath,
      env: buildPythonEnv(pythonPath),
    };
    super(script, options);
  }

  on(event: string, listener: (...args: any[]) => void): this {
    this.removeAllListeners(event);
    super.on(event, listener);
    return this;
  }

  kill(callback: (...args: any[]) => void): this {
    const pid = this.childProcess?.pid;
    if (pid === undefined) {
      callback();
      return this;
    }
    treeKill(pid, 'SIGTERM', callback);
    return this;
  }
}
