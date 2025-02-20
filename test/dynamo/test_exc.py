# Owner(s): ["module: dynamo"]

import logging
import unittest

import torch
import torch._dynamo
import torch._dynamo.config
import torch._dynamo.test_case
from torch._dynamo.comptime import comptime
from torch._dynamo.exc import Unsupported
from torch.testing._internal.common_utils import munge_exc
from torch.testing._internal.logging_utils import LoggingTestCase, make_logging_test


class ExcTests(LoggingTestCase):
    maxDiff = None

    def assertExpectedInlineMunged(
        self, exc_type, callable, expect, *, suppress_suffix=True
    ):
        try:
            callable()
        except exc_type as e:
            self.assertExpectedInline(
                munge_exc(e, suppress_suffix=suppress_suffix), expect, skip=1
            )
            return
        self.fail(msg="Did not raise when expected to")

    def test_unsupported_real_stack(self):
        # exercise Unsupported constructor and augment_exc_message
        def fn002(x):
            torch._dynamo.graph_break()

        def fn001(x):
            x = x + 1
            fn002(x)

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn001, backend="eager", fullgraph=True)(
                torch.randn(1)
            ),
            """\
call_function graph_break in skip_files _dynamo/decorators.py

from user code:
   File "test_exc.py", line N, in fn001
    fn002(x)
  File "test_exc.py", line N, in fn002
    torch._dynamo.graph_break()
""",
        )

    @torch._dynamo.config.patch(verbose=True, suppress_errors=True)
    @make_logging_test()
    def test_internal_error_suppress_errors(self, records):
        def fn001(x):
            def f(ctx):
                raise AssertionError()

            comptime(f)

        torch.compile(fn001, backend="eager")(torch.randn(1))

        record = self.getRecord(records, "WON'T CONVERT")

        self.assertExpectedInline(
            munge_exc(record.getMessage()),
            """\
WON'T CONVERT fn001 test_exc.py line N
========== TorchDynamo Stack Trace ==========
Traceback (most recent call last):
  File "test_exc.py", line N, in f
    raise AssertionError()
AssertionError:

from user code:
   File "test_exc.py", line N, in fn001
    comptime(f)


========== The above exception occurred while processing the following code ==========

  File "test_exc.py", line N, in test_internal_error_suppress_errors
    torch.compile(fn001, backend="eager")(torch.randn(1))
  File "test_exc.py", line N, in fn001
    comptime(f)

==========""",
        )

    @make_logging_test()
    def test_not_implemented_error(self, records):
        def fn001(x):
            def f(ctx):
                raise NotImplementedError()

            # Ensure graph break is not possible
            for i in range(3):
                comptime(f)

        torch.compile(fn001, backend="eager")(torch.randn(1))

        record = self.getRecord(records, "WON'T CONVERT")

        self.assertExpectedInline(
            munge_exc(record.getMessage()),
            """\
WON'T CONVERT fn001 test_exc.py line N
due to:
Traceback (most recent call last):
  File "test_exc.py", line N, in f
    raise NotImplementedError()
torch._dynamo.exc.InternalTorchDynamoError:

from user code:
   File "test_exc.py", line N, in fn001
    comptime(f)
""",
        )

    @unittest.expectedFailure
    @torch._dynamo.config.patch(inject_BUILD_SET_unimplemented_TESTING_ONLY=True)
    @make_logging_test(dynamo=logging.DEBUG)
    def test_unsupported_error(self, records):
        def fn001(x):
            return {1, 2}

        torch.compile(fn001, backend="eager")(torch.randn(1))

        # TODO: There is no graph break log!  This is because the graph break
        # logging is not in a centralized location; unsupported
        # instruction bypasses it
        self.getRecord(records, "Graph break:")

    @torch._dynamo.config.patch(suppress_errors=False)
    def test_internal_error_no_suppress(self):
        def fn001(x):
            # NB: avoid decorator, as 3.11 changed the line number attributed
            # in this situation
            def f(ctx):
                raise AssertionError()

            comptime(f)

        # NB: OK for user code to be truncated here, because the regular
        # exception backtrace has the rest of the crumbs
        self.assertExpectedInlineMunged(
            AssertionError,
            lambda: torch.compile(fn001, backend="eager")(torch.randn(1)),
            """\


from user code:
   File "test_exc.py", line N, in fn001
    comptime(f)
""",
        )

    @make_logging_test(graph_breaks=True)
    def test_graph_break_log(self, records):
        def fn002(x):
            x = x + 1
            torch._dynamo.graph_break()
            x = x + 1
            return x

        def fn001(x):
            return fn002(x)

        torch.compile(fn001, backend="eager")(torch.randn(1))

        record = self.getRecord(records, "Graph break:")

        # TODO: This should also report the enclosing frames; need to plumb
        # frame object to it
        self.assertExpectedInline(
            munge_exc(record.getMessage()),
            """\
Graph break: call_function graph_break in skip_files _dynamo/decorators.py from user code at:
  File "test_exc.py", line N, in fn001
    return fn002(x)
  File "test_exc.py", line N, in fn002
    torch._dynamo.graph_break()
""",
        )

    @torch._dynamo.config.patch(suppress_errors=False)
    def test_backend_suppress_line(self):
        def fn001(x):
            x = torch.relu(x)
            return x + 1

        # Do NOT let this get attributed to x + 1
        self.assertExpectedInlineMunged(
            torch._dynamo.exc.BackendCompilerFailed,
            lambda: torch.compile(fn001, backend="relu_compile_error_TESTING_ONLY")(
                torch.randn(1)
            ),
            """\
backend='relu_compile_error_TESTING_ONLY' raised:
ReluCompileError:
""",
        )


if __name__ == "__main__":
    from torch._dynamo.test_case import run_tests

    run_tests()
