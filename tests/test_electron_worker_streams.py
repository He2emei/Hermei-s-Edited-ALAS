import os
import sys
import unittest

from module.webui.process_manager import ProcessManager
from module.webui.fake_pil_module import remove_fake_pil_module


# process_manager intentionally installs a lightweight PIL shim for WebUI
# startup. Do not leak that import-side effect into unrelated tests.
remove_fake_pil_module()


class InvalidStream:
    def write(self, text):
        raise OSError(22, 'Invalid argument')

    def flush(self):
        raise OSError(22, 'Invalid argument')


class ElectronWorkerStreamsTest(unittest.TestCase):
    def test_worker_replaces_inherited_invalid_standard_streams(self):
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        redirected_stdout = None
        redirected_stderr = None
        try:
            sys.stdout = InvalidStream()
            sys.stderr = InvalidStream()

            ProcessManager.redirect_standard_streams()
            redirected_stdout = sys.stdout
            redirected_stderr = sys.stderr

            self.assertEqual(redirected_stdout.name, os.devnull)
            self.assertEqual(redirected_stderr.name, os.devnull)
            print('read: ./config/alas.json')
            sys.stderr.write('worker stderr remains writable\n')
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            if redirected_stdout is not None:
                redirected_stdout.close()
            if redirected_stderr is not None:
                redirected_stderr.close()


if __name__ == '__main__':
    unittest.main()
