const childProcess = require('child_process');

const originalExec = childProcess.exec;

childProcess.exec = function exec(command, options, callback) {
  const cmd = typeof command === 'string' ? command.trim().toLowerCase() : '';
  if (cmd === 'net use') {
    const cb = typeof options === 'function' ? options : callback;
    if (typeof cb === 'function') {
      process.nextTick(() => cb(null, '', ''));
    }
    return {
      pid: 0,
      stdout: null,
      stderr: null,
      on() {},
      kill() {},
    };
  }
  return originalExec.apply(this, arguments);
};
