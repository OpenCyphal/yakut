# Copyright (c) 2022 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
from typing import Any, Callable
import pycyphal
import yakut
from yakut.subject_resolver import SubjectResolver as SubjectResolver
from yakut import dtype_loader


class SubjectSpecifierProcessingError(RuntimeError):
    pass


class BadSpecifierError(SubjectSpecifierProcessingError):
    pass


class NoFixedPortIDError(SubjectSpecifierProcessingError):
    pass


class NetworkDiscoveryError(SubjectSpecifierProcessingError):
    pass


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
    if specifier.count(":") == 1:  # The simplest case -- full information is given explicitly.
        sp_sbj_id, sp_dty = specifier.split(":")
        _logger.info("Subject specifier interpreted as explicit: %r", (sp_sbj_id, sp_dty))
        subject_id = _parse_subject_id(sp_sbj_id)
        if not subject_id:
            raise BadSpecifierError(f"{subject_id} is not a valid subject-ID")
        return subject_id, dtype_loader.load_dtype(sp_dty)

    subject_id = _parse_subject_id(specifier)
    if subject_id is None:
        _logger.debug(
            "Subject specifier is not a valid subject-ID, assume it is dtype name with fixed port-ID: %r", specifier
        )
        dtype = dtype_loader.load_dtype(specifier)
        subject_id = pycyphal.dsdl.get_fixed_port_id(dtype)
        _logger.debug("Loaded dtype %s with fixed port-ID %r", dtype, subject_id)
        if subject_id is None:
            raise NoFixedPortIDError(
                f"Type specified as {specifier!r} is found but it has no fixed port-ID. "
                f"Consider specifying the subject-ID manually? The syntax is like 1234:{specifier}"
            )
        return subject_id, dtype

    _logger.info("Subject specifier is a number (%r), using network resolver (this may take a few seconds)", subject_id)
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
        raise NetworkDiscoveryError(
            f"Automatic network discovery did not return suitable dtypes for subject {subject_id}. "
            f"Either the subject-ID is incorrect, or the nodes that utilize it are currently offline, "
            f"or they do not support the introspection services required for automatic discovery. "
            f"Consider specifying the data type manually? The syntax is like {subject_id}:namespace.DataType"
        ) from None
    _logger.debug("Network discovery for subject %s done with dtype %s", subject_id, dtype)
    assert isinstance(dtype, type)
    return subject_id, dtype


def _parse_subject_id(spec: str) -> int | None:
    try:
        val = int(spec)
    except ValueError:
        return None
    if 0 <= val <= pycyphal.transport.MessageDataSpecifier.SUBJECT_ID_MASK:
        return val
    return None


_logger = yakut.get_logger(__name__)
