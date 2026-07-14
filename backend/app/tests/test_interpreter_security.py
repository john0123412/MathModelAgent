"""Fail-closed tests for model-generated code execution."""

import os
import tempfile
import unittest
from unittest import mock

from app.config.setting import settings
from app.schemas.response import ResultModel
from app.tools.e2b_interpreter import E2BCodeInterpreter
from app.tools.interpreter_factory import create_interpreter
from app.tools.local_interpreter import (
    LocalCodeInterpreter,
    _UnprivilegedKernelManager,
    _drop_kernel_privileges,
)
from app.tools.notebook_serializer import NotebookSerializer


class TestInterpreterSecurity(unittest.IsolatedAsyncioTestCase):
    async def test_remote_mode_does_not_fall_back_to_local_without_e2b(self):
        with tempfile.TemporaryDirectory() as work_dir, mock.patch.object(
            settings, "CODE_INTERPRETER_KIND", "remote"
        ), mock.patch.object(settings, "E2B_API_KEY", None):
            with self.assertRaisesRegex(RuntimeError, "不会自动降级"):
                await create_interpreter(
                    task_id="task-1",
                    work_dir=work_dir,
                    notebook_serializer=NotebookSerializer(work_dir=work_dir),
                )

    async def test_local_mode_requires_explicit_trust_opt_in(self):
        with tempfile.TemporaryDirectory() as work_dir, mock.patch.object(
            settings, "CODE_INTERPRETER_KIND", "local"
        ), mock.patch.object(settings, "ALLOW_LOCAL_CODE_EXECUTION", False):
            with self.assertRaisesRegex(RuntimeError, "本地代码执行默认禁用"):
                await create_interpreter(
                    task_id="task-1",
                    work_dir=work_dir,
                    notebook_serializer=NotebookSerializer(work_dir=work_dir),
                )

    async def test_auto_mode_requires_explicit_trust_opt_in_without_e2b(self):
        with tempfile.TemporaryDirectory() as work_dir, mock.patch.object(
            settings, "CODE_INTERPRETER_KIND", "auto"
        ), mock.patch.object(settings, "E2B_API_KEY", None), mock.patch.object(
            settings, "ALLOW_LOCAL_CODE_EXECUTION", False
        ):
            with self.assertRaisesRegex(RuntimeError, "ALLOW_LOCAL_CODE_EXECUTION"):
                await create_interpreter(
                    task_id="task-1",
                    work_dir=work_dir,
                    notebook_serializer=NotebookSerializer(work_dir=work_dir),
                )

    async def test_auto_mode_uses_local_only_after_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as work_dir, mock.patch.object(
            settings, "CODE_INTERPRETER_KIND", "auto"
        ), mock.patch.object(settings, "E2B_API_KEY", None), mock.patch.object(
            settings, "ALLOW_LOCAL_CODE_EXECUTION", True
        ), mock.patch.object(
            LocalCodeInterpreter, "initialize", new=mock.AsyncMock()
        ) as initialize:
            interpreter = await create_interpreter(
                task_id="task-1",
                work_dir=work_dir,
                notebook_serializer=NotebookSerializer(work_dir=work_dir),
            )

        self.assertIsInstance(interpreter, LocalCodeInterpreter)
        initialize.assert_awaited_once()

    async def test_auto_mode_prefers_remote_when_e2b_is_configured(self):
        with tempfile.TemporaryDirectory() as work_dir, mock.patch.object(
            settings, "CODE_INTERPRETER_KIND", "auto"
        ), mock.patch.object(settings, "E2B_API_KEY", "test-e2b-key"), mock.patch.object(
            settings, "ALLOW_LOCAL_CODE_EXECUTION", True
        ), mock.patch.object(
            E2BCodeInterpreter, "create", new=mock.AsyncMock()
        ) as create:
            interpreter = mock.Mock()
            interpreter.initialize = mock.AsyncMock()
            create.return_value = interpreter
            result = await create_interpreter(
                task_id="task-1",
                work_dir=work_dir,
                notebook_serializer=NotebookSerializer(work_dir=work_dir),
            )

        self.assertIs(result, interpreter)
        create.assert_awaited_once()
        interpreter.initialize.assert_awaited_once()

    async def test_local_kernel_refuses_to_start_without_proc_protection(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = LocalCodeInterpreter(
                task_id="task-1",
                work_dir=work_dir,
                notebook_serializer=NotebookSerializer(work_dir=work_dir),
            )
            with mock.patch(
                "app.tools.local_interpreter._disable_parent_process_dumpability",
                side_effect=RuntimeError("protection unavailable"),
            ), mock.patch(
                "app.tools.local_interpreter._UnprivilegedKernelManager"
            ) as kernel_manager:
                with self.assertRaisesRegex(RuntimeError, "protection unavailable"):
                    await interpreter.initialize()

        kernel_manager.assert_not_called()

    async def test_local_kernel_starts_with_unprivileged_preexec(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = LocalCodeInterpreter(
                task_id="task-1",
                work_dir=work_dir,
                notebook_serializer=NotebookSerializer(work_dir=work_dir),
            )
            with mock.patch(
                "app.tools.local_interpreter._disable_parent_process_dumpability"
            ), mock.patch.object(interpreter, "_prepare_kernel_work_dir"), mock.patch.object(
                interpreter, "_strip_sensitive_parent_environment"
            ), mock.patch.object(
                interpreter, "_build_kernel_env", return_value={}
            ), mock.patch.object(
                interpreter,
                "_create_kernel_connection_file",
                return_value="/tmp/mathmodelagent-kernel-connections/kernel-test/kernel.json",
            ), mock.patch.object(interpreter, "_pre_execute_code"), mock.patch(
                "app.tools.local_interpreter._UnprivilegedKernelManager"
            ) as kernel_manager:
                manager = kernel_manager.return_value
                manager.client.return_value = mock.Mock()
                await interpreter.initialize()

        self.assertIs(manager.start_kernel.call_args.kwargs["preexec_fn"], _drop_kernel_privileges)
        self.assertIn(
            "mathmodelagent-kernel-connections",
            kernel_manager.call_args.kwargs["connection_file"],
        )

    async def test_timeout_discards_kernel_and_reports_snapshot_recovery(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = LocalCodeInterpreter(
                task_id="task-1",
                work_dir=work_dir,
                notebook_serializer=NotebookSerializer(work_dir=work_dir),
            )
            interpreter.execute_code_ = mock.Mock(
                return_value=[("error", "本地代码执行超过 120 秒，已中断")]
            )

            with mock.patch(
                "app.tools.local_interpreter.redis_manager.publish_message",
                new=mock.AsyncMock(),
            ), mock.patch.object(
                interpreter, "_push_to_websocket", new=mock.AsyncMock()
            ), mock.patch.object(
                interpreter,
                "_recover_kernel_after_timeout",
                new=mock.AsyncMock(return_value=True),
            ) as recover:
                _text, errored, error_message = await interpreter.execute_code("x = 1")

        self.assertTrue(errored)
        self.assertIn("已重启", error_message)
        recover.assert_awaited_once()


class TestLocalInterpreterIsolation(unittest.TestCase):
    def test_kernel_preexec_drops_to_dedicated_uid(self):
        with mock.patch("app.tools.local_interpreter.os.name", "posix"), mock.patch(
            "app.tools.local_interpreter.os.geteuid",
            side_effect=[0, 10001],
            create=True,
        ), mock.patch(
            "app.tools.local_interpreter.os.getegid", return_value=10001, create=True
        ), mock.patch(
            "app.tools.local_interpreter.os.setgroups", create=True
        ) as setgroups, mock.patch(
            "app.tools.local_interpreter.os.setgid", create=True
        ) as setgid, mock.patch(
            "app.tools.local_interpreter.os.setuid", create=True
        ) as setuid:
            _drop_kernel_privileges()

        setgroups.assert_called_once_with([])
        setgid.assert_called_once_with(10001)
        setuid.assert_called_once_with(10001)

    def test_kernel_preexec_rejects_nonroot_backend(self):
        with mock.patch("app.tools.local_interpreter.os.name", "posix"), mock.patch(
            "app.tools.local_interpreter.os.geteuid", return_value=1000, create=True
        ):
            with self.assertRaisesRegex(RuntimeError, "root 后端进程"):
                _drop_kernel_privileges()

    def test_kernel_manager_assigns_connection_file_to_unprivileged_uid(self):
        manager = _UnprivilegedKernelManager(
            kernel_name="python3",
            connection_file="/tmp/kernel-test.json",
        )
        with mock.patch(
            "app.tools.local_interpreter.jupyter_client.KernelManager.write_connection_file"
        ), mock.patch("app.tools.local_interpreter.os.chown", create=True) as chown, mock.patch(
            "app.tools.local_interpreter.os.chmod", create=True
        ) as chmod:
            manager.write_connection_file()

        chmod.assert_called_once_with("/tmp/kernel-test.json", 0o440)
        chown.assert_called_once_with("/tmp/kernel-test.json", 10001, 0)

    def test_kernel_work_dir_is_assigned_to_unprivileged_account(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "input.csv"), "w", encoding="utf-8") as f:
                f.write("x\n1\n")
            os.mkdir(os.path.join(work_dir, "nested"))
            interpreter = LocalCodeInterpreter(
                task_id="task-1",
                work_dir=work_dir,
                notebook_serializer=NotebookSerializer(work_dir=work_dir),
            )
            with mock.patch("app.tools.local_interpreter.os.name", "posix"), mock.patch(
                "app.tools.local_interpreter.os.geteuid", return_value=0, create=True
            ), mock.patch(
                "app.tools.local_interpreter.os.chown", create=True
            ) as chown:
                interpreter._prepare_kernel_work_dir()

        self.assertGreaterEqual(chown.call_count, 5)
        self.assertTrue(
            all(call.args[1:] == (10001, 10001) for call in chown.call_args_list)
        )

    def test_proc_protection_sets_pr_set_dumpable(self):
        fake_libc = mock.Mock()
        fake_libc.prctl.return_value = 0

        with mock.patch("app.tools.local_interpreter.os.name", "posix"), mock.patch(
            "app.tools.local_interpreter.ctypes.CDLL", return_value=fake_libc
        ):
            from app.tools.local_interpreter import _disable_parent_process_dumpability

            _disable_parent_process_dumpability()

        fake_libc.prctl.assert_called_once_with(4, 0, 0, 0, 0)

    def test_kernel_environment_excludes_credentials_and_uses_task_home(self):
        with tempfile.TemporaryDirectory() as work_dir, mock.patch.dict(
            os.environ,
            {
                "PATH": "/usr/local/bin:/usr/bin",
                "LANG": "C.UTF-8",
                "COORDINATOR_API_KEY": "test-only-value",
                "ANTHROPIC_AUTH_TOKEN": "test-only-value",
            },
            clear=True,
        ):
            interpreter = LocalCodeInterpreter(
                task_id="task-1",
                work_dir=work_dir,
                notebook_serializer=NotebookSerializer(work_dir=work_dir),
            )
            interpreter._strip_sensitive_parent_environment()
            kernel_env = interpreter._build_kernel_env()

            self.assertNotIn("COORDINATOR_API_KEY", os.environ)
            self.assertNotIn("ANTHROPIC_AUTH_TOKEN", kernel_env)
            self.assertEqual(kernel_env["HOME"], os.path.abspath(work_dir))
            self.assertEqual(kernel_env["PYTHONNOUSERSITE"], "1")

    def test_local_execution_timeout_interrupts_kernel(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = LocalCodeInterpreter(
                task_id="task-1",
                work_dir=work_dir,
                notebook_serializer=NotebookSerializer(work_dir=work_dir),
                execution_timeout=0,
            )
            interpreter.km = mock.Mock()
            interpreter.kc = mock.Mock()

            output = interpreter.execute_code_("1 + 1")

        self.assertEqual(output[0][0], "error")
        self.assertIn("已中断", output[0][1])
        interpreter.km.interrupt_kernel.assert_called_once()

    def test_watchdog_timeout_returns_when_iopub_is_stalled(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = LocalCodeInterpreter(
                task_id="task-1",
                work_dir=work_dir,
                notebook_serializer=NotebookSerializer(work_dir=work_dir),
                execution_timeout=5,
            )
            interpreter.km = mock.Mock()
            interpreter.kc = mock.Mock()
            timers = []

            class ImmediateTimer:
                daemon = False

                def __init__(self, _seconds, callback):
                    self.callback = callback
                    self.cancelled = False
                    timers.append(self)

                def start(self):
                    self.callback()

                def cancel(self):
                    self.cancelled = True

            with mock.patch(
                "app.tools.local_interpreter.threading.Timer", ImmediateTimer
            ):
                output = interpreter.execute_code_("while True: pass")

        self.assertEqual(output[0][0], "error")
        self.assertIn("超过 5 秒", output[0][1])
        interpreter.km.interrupt_kernel.assert_called_once()
        self.assertTrue(timers[0].cancelled)

    def test_posix_watchdog_uses_kernel_process_and_is_cleaned_up(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = LocalCodeInterpreter(
                task_id="task-1",
                work_dir=work_dir,
                notebook_serializer=NotebookSerializer(work_dir=work_dir),
                execution_timeout=5,
            )
            interpreter.km = mock.Mock()
            interpreter.km.provisioner.pid = 4321
            interpreter.kc = mock.Mock()
            interpreter.kc.get_iopub_msg.return_value = {
                "msg_type": "status",
                "content": {"execution_state": "idle"},
            }
            watchdog = mock.Mock()
            watchdog.poll.return_value = None

            with mock.patch("app.tools.local_interpreter.os.name", "posix"), mock.patch(
                "app.tools.local_interpreter.subprocess.Popen", return_value=watchdog
            ) as popen:
                interpreter.execute_code_("1 + 1")

        self.assertIn("kill -INT 4321", popen.call_args.args[0][2])
        watchdog.terminate.assert_called_once()

    def test_restart_cleans_connection_files_when_shutdown_fails(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = LocalCodeInterpreter(
                task_id="task-1",
                work_dir=work_dir,
                notebook_serializer=NotebookSerializer(work_dir=work_dir),
            )
            interpreter.kc = mock.Mock()
            interpreter.km = mock.Mock()
            interpreter.km.shutdown_kernel.side_effect = RuntimeError("stop")

            with mock.patch.object(
                interpreter, "_cleanup_kernel_connection_file"
            ) as cleanup, mock.patch.object(interpreter, "_start_kernel") as start:
                with self.assertRaisesRegex(RuntimeError, "stop"):
                    interpreter.restart_jupyter_kernel()

        cleanup.assert_called_once()
        start.assert_not_called()
        self.assertIsNone(interpreter.km)
        self.assertIsNone(interpreter.kc)

    def test_local_execution_log_omits_code_contents(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = LocalCodeInterpreter(
                task_id="task-1",
                work_dir=work_dir,
                notebook_serializer=NotebookSerializer(work_dir=work_dir),
                execution_timeout=0,
            )
            interpreter.km = mock.Mock()
            interpreter.kc = mock.Mock()
            code = "sensitive-code-marker"

            with mock.patch("app.tools.local_interpreter.logger.info") as log_info:
                interpreter.execute_code_(code)

        logged_text = " ".join(
            str(call.args[0]) for call in log_info.call_args_list if call.args
        )
        self.assertNotIn(code, logged_text)
        self.assertIn(f"chars={len(code)}", logged_text)

    def test_websocket_log_omits_result_payload(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = LocalCodeInterpreter(
                task_id="task-1",
                work_dir=work_dir,
                notebook_serializer=NotebookSerializer(work_dir=work_dir),
            )
            marker = "sensitive-result-marker"

            with mock.patch(
                "app.tools.base_interpreter.logger.debug"
            ) as log_debug, mock.patch(
                "app.tools.base_interpreter.redis_manager.publish_message",
                new=mock.AsyncMock(),
            ):
                import asyncio

                asyncio.run(
                    interpreter._push_to_websocket(
                        [ResultModel(res_type="result", format="text", msg=marker)]
                    )
                )

        logged_text = " ".join(
            str(call.args[0]) for call in log_debug.call_args_list if call.args
        )
        self.assertNotIn(marker, logged_text)
        self.assertIn("output_items=1", logged_text)
