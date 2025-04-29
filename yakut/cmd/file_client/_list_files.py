from __future__ import annotations
import dataclasses
import enum
from typing import Sequence, TYPE_CHECKING, Callable
import bisect
import yakut
from ruamel.yaml import YAML
from ._file_error import FileError

yaml = YAML()

if TYPE_CHECKING:
    import pycyphal.application

@yaml.register_class
@dataclasses.dataclass
class FileInfo:
    size: int
    timestamp: int
    is_file_not_directory: bool
    is_link: bool
    is_readable: bool
    is_writable: bool

@yaml.register_class
@dataclasses.dataclass
class FileResult:
    name: str
    info: FileInfo | FileError | None

@dataclasses.dataclass
class Result:
    files_per_node: dict[int, list[FileResult] | None] = dataclasses.field(default_factory=dict)
    errors: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)


async def list_files(
    local_node: "pycyphal.application.Node",
    progress: Callable[[str], None],
    node_ids: Sequence[int],
    path: str,
    *,
    optional_service: bool,
    get_info: bool,
    timeout: float,
) -> Result:
    res = Result()
    for nid, names in (await _impl_list_files(local_node, progress, node_ids, path, timeout=timeout)).items():
        _logger.debug("File names @%r: %r", nid, names)
        if isinstance(names, _NoService):
            res.files_per_node[nid] = None
            if optional_service:
                res.warnings.append(f"File list service is not accessible at node {nid}, ignoring as requested")
            else:
                res.errors.append(f"File list service is not accessible at node {nid}")
        else:
            lst = res.files_per_node.setdefault(nid, [])
            assert isinstance(lst, list)
            for idx, n in enumerate(names):
                if isinstance(n, _Timeout):
                    res.errors.append(f"Request #{idx} to node {nid} has timed out, data incomplete")
                else:
                    lst.append(FileResult(name=n, info=None))
            if get_info:
                finfo = await _impl_get_info(
                    local_node,
                    progress,
                    nid,
                    path,
                    [f.name for f in lst],
                    timeout=timeout,
                )
                if isinstance(finfo, _NoService):
                    if optional_service:
                        res.warnings.append(f"File info service is not accessible at node {nid}, ignoring as requested")
                    else:
                        res.errors.append(f"File info service is not accessible at node {nid}")
                else:
                    for file, info in zip(lst, finfo):
                        if isinstance(info, _Timeout):
                            res.errors.append(f"GetInfo for file #{file.name} to node {nid} has timed out, data incomplete")
                        elif isinstance(info, FileError):
                            res.errors.append(f"GetInfo error {info} for file {file.name} at node {nid}")
                        else:
                            file.info = info
    return res


class _NoService:
    pass


class _Timeout:
    pass


async def _impl_list_files(
    local_node: "pycyphal.application.Node",
    progress: Callable[[str], None],
    node_ids: Sequence[int],
    path: str,
    *,
    timeout: float,
) -> dict[int, list[str | _Timeout] | _NoService]:
    from uavcan.file import List_0_2
    from uavcan.file import Path_2_0

    out: dict[int, list[str | _Timeout] | _NoService] = {}
    for nid in node_ids:
        cln = local_node.make_client(List_0_2, nid)
        try:
            cln.response_timeout = timeout
            name_list: list[str | _Timeout] | _NoService = []
            for idx in range(2**16):
                progress(f"List {nid: 5}: {idx: 5}")
                resp = await cln(List_0_2.Request(entry_index=idx, directory_path=Path_2_0(path=path)))
                assert isinstance(name_list, list)
                if resp is None:
                    if 0 == idx:  # First request timed out, assume service not supported or node is offline
                        name_list = _NoService()
                    else:  # Non-first request has timed out, assume network error
                        name_list.append(_Timeout())
                    break
                assert isinstance(resp, List_0_2.Response)
                name = resp.entry_base_name.path.tobytes().decode(errors="replace")
                if not name:
                    break
                name_list.append(name)
        finally:
            cln.close()
        _logger.debug("File names fetched from node %r: %r", nid, name_list)
        out[nid] = name_list
    return out

async def _impl_get_info(
    local_node: "pycyphal.application.Node",
    progress: Callable[[str], None],
    node_id: int,
    path: str,
    files: Sequence[str],
    *,
    timeout: float,
) -> list[FileInfo | _Timeout | None] | _NoService:
    from uavcan.file import GetInfo_0_2
    from uavcan.file import Path_2_0
    from uavcan.file import Error_1_0

    out: list[FileInfo | _Timeout | None] | _NoService = []
    cln = local_node.make_client(GetInfo_0_2, node_id)
    for idx, file in enumerate(files):
        cln.response_timeout = timeout
        progress(f"GetInfo {node_id:5}: {file:5}")
        if path != "":
            filepath = chr(Path_2_0.SEPARATOR).join([path, file])
        else:
            filepath = file
        resp = await cln(GetInfo_0_2.Request(path=Path_2_0(path=filepath)))
        if resp is None:
            if 0 == idx:  # First request timed out, assume service not supported or node is offline
                out = _NoService()
            else:  # Non-first request has timed out, assume network error
                out.append(_Timeout())
            break
        assert isinstance(resp, GetInfo_0_2.Response)
        if resp.error.value != Error_1_0.OK:
            out.append(FileError(resp.error.value))
            continue
        out.append(FileInfo(
            size = resp.size,
            timestamp=resp.unix_timestamp_of_last_modification,
            is_file_not_directory=resp.is_file_not_directory,
            is_link=resp.is_link,
            is_readable=resp.is_readable,
            is_writable=resp.is_writeable
        ))
    cln.close()
    _logger.debug("File info fetched from node %r: %r", node_id, out)
    return out

_logger = yakut.get_logger(__name__)
