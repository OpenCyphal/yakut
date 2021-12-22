# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from __future__ import annotations
from typing import Iterable, Callable, Any, Type, Optional, TYPE_CHECKING
import time
import asyncio
import pyuavcan
import yakut

if TYPE_CHECKING:
    import pyuavcan.application  # pylint: disable=ungrouped-imports
    from ._controller import ControllerReader, Sample
    from yakut.yaml import EvaluableLoader  # pylint: disable=ungrouped-imports


_logger = yakut.get_logger(__name__)


class Executor:
    SYM_INDEX = "n"
    SYM_TIME = "t"
    SYM_CTRL_AXIS = "A"
    SYM_CTRL_BUTTON = "B"
    SYM_CTRL_TOGGLE = "T"
    SYM_DTYPE = "dtype"

    def __init__(
        self,
        node: pyuavcan.application.Node,
        loader: EvaluableLoader,
        publications: Iterable[Publication],
    ) -> None:
        self._node = node
        self._ctl: Optional[ControllerReader] = None
        self._publications = list(publications)

        self._loader = loader
        self._loader.evaluation_context[Executor.SYM_CTRL_AXIS] = lambda s, i: self._sample_controller(s).axis[i]
        self._loader.evaluation_context[Executor.SYM_CTRL_BUTTON] = lambda s, i: self._sample_controller(s).button[i]
        self._loader.evaluation_context[Executor.SYM_CTRL_TOGGLE] = lambda s, i: self._sample_controller(s).toggle[i]

    async def run(self, count: int, period: float) -> None:
        self._node.start()

        started_at: Optional[float] = None
        for index in range(count):
            # Update the expression states. Notice that the controls are sampled once atomically.
            self._loader.evaluation_context[Executor.SYM_INDEX] = index
            self._loader.evaluation_context[Executor.SYM_TIME] = period * index
            if self._ctl:
                self._ctl.sample_and_hold()

            # Compute new messages. The first cycle may be slow to compute due to lazy initialization.
            for pub in self._publications:
                pub.construct_next_message()

            # Run the publication. We initialize the time late to ensure that lazy init doesn't cause phase distortion.
            if started_at is None:
                started_at = asyncio.get_event_loop().time()
            out = await asyncio.gather(*[p.publish() for p in self._publications])
            assert len(out) == len(self._publications) and all(isinstance(x, bool) for x in out)
            if not all(out):
                timed_out = [self._publications[idx] for idx, res in enumerate(out) if not res]
                _logger.error("The following publications have timed out:\n%s", "\n".join(map(str, timed_out)))

            # Sleep until the next publication cycle.
            sleep_duration = (started_at + period * (index + 1)) - asyncio.get_event_loop().time()
            _logger.info("Published group %6d of %6d; sleeping for %.3f seconds", index + 1, count, sleep_duration)
            await asyncio.sleep(sleep_duration)

    def close(self) -> None:
        self._node.close()
        if self._ctl:
            self._ctl.close()

    def _sample_controller(self, selector: Any) -> Sample:
        if not self._ctl:
            from ._controller import ControllerReader

            _logger.debug("Constructing the controller reader...")
            started_at = time.monotonic()
            self._ctl = ControllerReader()
            _logger.debug("Done in %.3f sec: %s", time.monotonic() - started_at, self._ctl)
        return self._ctl.read(selector)


class Publication:
    def __init__(
        self,
        subject_id: int,
        dtype: Type[pyuavcan.dsdl.CompositeObject],
        evaluator: Callable[..., Any],
        presentation: pyuavcan.presentation.Presentation,
        priority: pyuavcan.transport.Priority,
        send_timeout: float,
    ):
        self._dtype = dtype
        self._evaluator = evaluator
        self._publisher = presentation.make_publisher(self._dtype, subject_id)
        self._publisher.priority = priority
        self._publisher.send_timeout = send_timeout
        self._next_message: Optional[pyuavcan.dsdl.CompositeObject] = None
        self._evaluation_context = {
            Executor.SYM_DTYPE: self._dtype,
        }

    def construct_next_message(self) -> None:
        """
        Message construction may take a considerable amount of time depending on the complexity of the expressions.
        This is why they it has to be done separately to keep the publication phase more accurate.
        """
        started_at = time.monotonic()
        # We could make the evaluated expression call a specific function to conditionally cancel publication.
        content = self._evaluator(**self._evaluation_context)
        self._next_message = pyuavcan.dsdl.update_from_builtin(self._dtype(), content if content is not None else {})
        _logger.info(
            "%s: Next message (constructed in %.3f sec) shown on the next line:\n%s",
            self,
            time.monotonic() - started_at,
            self._next_message,
        )

    async def publish(self) -> bool:
        if self._next_message is not None:
            msg, self._next_message = self._next_message, None
            out = await self._publisher.publish(msg)
            assert isinstance(out, bool)
            return out
        return True

    def __repr__(self) -> str:
        out = pyuavcan.util.repr_attributes(self, self._publisher)
        assert isinstance(out, str)
        return out
