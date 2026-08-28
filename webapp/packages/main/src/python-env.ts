import * as path from 'path';


export type ChildEnvironment = Record<string, string | undefined>;


function samePath(left: string, right: string): boolean {
  return process.platform === 'win32'
    ? left.toLowerCase() === right.toLowerCase()
    : left === right;
}


export function buildPythonEnv(
  pythonExecutable: string,
  baseEnv: ChildEnvironment = process.env,
): NodeJS.ProcessEnv {
  const result: NodeJS.ProcessEnv = {...baseEnv};
  for (const key of Object.keys(result)) {
    if (key.toLowerCase() === 'path') delete result[key];
  }

  const pythonRoot = path.dirname(pythonExecutable);
  const required = [
    pythonRoot,
    path.join(pythonRoot, 'Scripts'),
    path.join(pythonRoot, 'Library', 'bin'),
  ];
  const existing = String(
    Object.entries(baseEnv).find(([key]) => key.toLowerCase() === 'path')?.[1] || '',
  ).split(path.delimiter).filter(Boolean);
  const combined: string[] = [];
  for (const candidate of [...required, ...existing]) {
    if (!combined.some(item => samePath(item, candidate))) combined.push(candidate);
  }
  result.PATH = combined.join(path.delimiter);
  return result;
}
