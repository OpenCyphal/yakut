# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
from typing import Any, Callable
import click
import pycyphal
import yakut
from yakut.subject_resolver import SubjectResolver as SubjectResolver
from yakut import dtype_loader


async def process_subject_specifier(
    specifier: str,
    resolver_provider: Callable[[], SubjectResolver],
) -> tuple[int, Any]:
    """
    Given the specifier string from the user return the subject-ID and the dtype for use with it.
    The resolver factory will be invoked if the user is asking us to perform automatic discovery through the network.
    If the specifier is complete (provides both subject-ID and dtype), the resolver will not be needed.
    This enables lazy construction of the local node and stuff, which is desirable as it may be very costly.
    The caller is responsible for closing the resolver afterwards (unless it was not needed).
    """
    specs = specifier.split(":")
    if not (1 <= len(specs) <= 2):
        click.BadParameter(f"Subject specifier invalid: {specifier!r}")
    if len(specs) == 2:  # The simplest case -- full information is given explicitly.
        _logger.info("Subject specifier interpreted as explicit: %r", specs)
        return int(specs[0]), dtype_loader.load_dtype(specs[1])

    (spec,) = specs
    del specs
    try:
        subject_id: int | None = int(spec)
    except ValueError:
        subject_id = None
    else:
        assert isinstance(subject_id, int)
        if not (0 <= subject_id <= pycyphal.transport.MessageDataSpecifier.SUBJECT_ID_MASK):
            raise click.BadParameter(f"{subject_id} is not a valid subject-ID")

    if subject_id is None:
        _logger.debug("Subject specifier is not a number, assume it is dtype name with fixed port-ID: %r", spec)
        dtype = dtype_loader.load_dtype(spec)
        subject_id = pycyphal.dsdl.get_fixed_port_id(dtype)
        _logger.debug("Loaded dtype %s with fixed port-ID %r", dtype, subject_id)
        if subject_id is None:
            raise click.ClickException(
                f"Type specified as {spec!r} is found but it has no fixed port-ID. "
                f"Consider specifying the subject-ID manually? The syntax is like 1234:{spec}"
            )
        return subject_id, dtype

    _logger.debug("Subject specifier is a number, will resolve dtype using network discovery: %r", subject_id)
    assert isinstance(subject_id, int)
    resolver = resolver_provider()
    # Sorting to bubble newer types higher up. This should be natural sort.
    type_names = list(sorted(await resolver.dtypes_by_id(subject_id), reverse=True))
    _logger.debug("Dtype names found by the network resolver for subject-ID %s: %s", subject_id, type_names)
    try:
        dtype = next(
            dtype
            for dtype in (dtype_loader.load_dtype(tn, allow_minor_version_mismatch=True) for tn in type_names)
            if dtype is not None and pycyphal.dsdl.is_message_type(dtype) and not pycyphal.dsdl.is_service_type(dtype)
        )
    except StopIteration:
        raise click.ClickException(
            f"Automatic network discovery did not return suitable dtypes for subject {subject_id}. "
            f"Either the subject-ID is incorrect, or the nodes that utilize it are currently offline, "
            f"or they do not support the introspection services required for automatic discovery. "
            f"Consider specifying the data type manually? The syntax is like {subject_id}:namespace.DataType"
        ) from None
    _logger.debug("Network discovery for subject %s done with dtype %s", subject_id, dtype)
    assert isinstance(dtype, type)
    return subject_id, dtype


_logger = yakut.get_logger(__name__)
