const fs = require('fs');
const path = require('path');


function isAlasRoot(candidate: string): boolean {
  return fs.existsSync(path.join(candidate, 'config', 'deploy.yaml'))
    && fs.existsSync(path.join(candidate, 'gui.py'));
}


function findAlasRoot(start: string): string | undefined {
  let candidate = path.resolve(start);
  while (true) {
    if (isAlasRoot(candidate)) return candidate;
    const parent = path.dirname(candidate);
    if (parent === candidate) return undefined;
    candidate = parent;
  }
}


export function resolveAlasPath(
  executable: string = process.execPath,
  workingDirectory: string = process.cwd(),
): string {
  const fromExecutable = findAlasRoot(path.dirname(executable));
  if (fromExecutable !== undefined) return fromExecutable;

  const fromWorkingDirectory = findAlasRoot(workingDirectory);
  if (fromWorkingDirectory !== undefined) return fromWorkingDirectory;

  throw new Error(
    `Unable to locate the ALAS root from executable ${executable} or working directory ${workingDirectory}`,
  );
}
