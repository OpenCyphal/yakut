# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

# pylint: disable=too-many-locals

from __future__ import annotations
import sys
import functools
from typing import TYPE_CHECKING, Optional, Callable, Any, AbstractSet, TypeVar
from collections import defaultdict
import numpy as np
import pyuavcan
import yakut
from ._model import N_NODES, N_SUBJECTS, N_SERVICES, NodeState
from ._ui import Style, Color, Canvas, TableRenderer

if TYPE_CHECKING:
    from numpy.typing import NDArray
    from scipy.sparse import spmatrix
    import uavcan.node


S_DEFAULT = Style(fg=Color.WHITE, salience=1)
S_FAILURE = Style(fg=Color.WHITE, bg=Color.RED, salience=2)
S_MUTED = Style(salience=-1)
S_ADVISORY = Style(fg=Color.MAGENTA, salience=1)
S_CAUTION = Style(fg=Color.YELLOW, salience=1)
S_WARNING = Style(fg=Color.RED, salience=1)
S_NOTICE = Style(fg=Color.CYAN, salience=1)

S_NICE = Style(fg=Color.GREEN, salience=1)
S_POOR = Style(fg=Color.YELLOW, salience=1)


class View:
    _CONNECTIVITY_MATRIX_CELL_WIDTH = 5

    def __init__(self) -> None:
        self._fragments: list[str] = []

        self._node_table_renderer = TableRenderer(map(len, View._NODE_TABLE_HEADER), separate_columns=True)
        self._connectivity_matrix_renderer = TableRenderer(
            (View._CONNECTIVITY_MATRIX_CELL_WIDTH for _ in range(N_NODES + 1)),
            separate_columns=False,
        )

        legend_canvas = Canvas()
        row = 0
        col = legend_canvas.put(row, 0, "APPLICATION LAYER CONNECTIVITY MATRIX [t/s=transfer/second] Colors: ")
        col = legend_canvas.put(
            row, col, "pub/cln", style=get_matrix_cell_style(tx=True, rx=False, recently_active=False)
        )
        col = legend_canvas.put(row, col, "│")
        col = legend_canvas.put(
            row, col, "sub/srv", style=get_matrix_cell_style(tx=False, rx=True, recently_active=False)
        )
        col = legend_canvas.put(row, col, "│")
        col = legend_canvas.put(
            row,
            col,
            "(pub+sub)/(cln+srv)",
            style=get_matrix_cell_style(tx=True, rx=True, recently_active=False),
        )
        col = legend_canvas.put(row, col, "│")
        col = legend_canvas.put(
            row, col, "activity", style=get_matrix_cell_style(tx=False, rx=False, recently_active=True)
        )
        col = legend_canvas.put(row, col, "│uavcan.node.port.List is ")
        col = legend_canvas.put(row, col, "published", style=S_NICE)
        col = legend_canvas.put(row, col, "/")
        col = legend_canvas.put(row, col, "not", style=S_POOR)
        legend_canvas.put(row, col, "│")

        self._connectivity_matrix_legend = legend_canvas.flip_buffer()

    def flip_buffer(self) -> str:
        out = "\n".join(self._fragments)
        self._fragments = []
        return out

    def render(
        self,
        states: dict[Optional[int], NodeState],
        xfer_deltas: spmatrix,
        xfer_rates: spmatrix,
        byte_rates: spmatrix,
        total_transport_errors: int,
        fir_window_duration: float,
    ) -> None:
        self._fragments.append(self._render_node_table(states))

        self._fragments.append(self._connectivity_matrix_legend)
        self._fragments.append(self._render_connectivity_matrix(states, xfer_deltas, xfer_rates, byte_rates))

        annotation_canvas = Canvas()
        col = annotation_canvas.put(0, 0, "Total transport layer errors:")
        col = annotation_canvas.put(
            0,
            col,
            f"{total_transport_errors:9d}",
            style=S_POOR if total_transport_errors > 0 else S_NICE,
        )
        col += 9
        col = annotation_canvas.put(0, col, f"Values averaged over {fir_window_duration:.1f} sec")
        _ = col
        self._fragments.append(annotation_canvas.flip_buffer())

    # noinspection SpellCheckingInspection
    _NODE_TABLE_HEADER = [
        "NodID",
        "Mode",
        "Health",
        "VSSC",
        "Uptime".ljust(14),
        "VProtcl",
        "VHardwr",
        "VSoftware(major.minor.vcs.crc)".ljust(41),
        "Unique-ID".ljust(32),
        "Name",
    ]

    def _render_node_table(self, states: dict[Optional[int], NodeState]) -> str:
        for idx, s in enumerate(View._NODE_TABLE_HEADER):
            self._node_table_renderer[0, idx] = s

        for idx, (node_id, ss) in enumerate(states.items()):
            col = 0

            def put(data: Any, style: Optional[Style]) -> None:
                nonlocal col
                self._node_table_renderer[idx + 1, col] = data, (  # pylint: disable=cell-var-from-loop
                    style or S_DEFAULT
                )
                col += 1

            if node_id is not None:
                if not ss.online:
                    put(node_id, S_MUTED)
                else:
                    put(node_id, None)
            else:
                put("anon", None if ss.online else S_MUTED)

            if ss.heartbeat:
                if node_id is None and ss.online:
                    sty_override: Optional[Style] = S_FAILURE  # Anonymous nodes shall not publish heartbeat.
                elif not ss.online:
                    sty_override = S_MUTED
                else:
                    sty_override = None
                txt, sty = render_mode(ss.heartbeat.mode)
                put(txt, sty_override or sty)
                txt, sty = render_health(ss.heartbeat.health)
                put(txt, sty_override or sty)
                put(ss.heartbeat.vendor_specific_status_code, sty_override)
            else:
                put("?", S_MUTED)
                put("?", S_MUTED)
                put("?", S_MUTED)

            if ss.online:
                if ss.heartbeat is None:
                    if node_id is not None:
                        put("zombie", S_FAILURE)
                    else:
                        put("online", None)
                else:
                    put(render_uptime(ss.heartbeat.uptime), None)
            else:
                put("offline", S_MUTED)

            if ss.info:
                sty = None if ss.online and ss.heartbeat else S_MUTED
                put(
                    render_version(ss.info.protocol_version),
                    sty if ss.info.protocol_version.major == pyuavcan.UAVCAN_SPECIFICATION_VERSION[0] else S_FAILURE,
                )
                put(render_version(ss.info.hardware_version), sty)
                put(
                    render_full_software_version(
                        ss.info.software_version,
                        ss.info.software_vcs_revision_id,
                        int(ss.info.software_image_crc[0]) if len(ss.info.software_image_crc) > 0 else None,
                    ),
                    sty,
                )
                put(ss.info.unique_id.tobytes().hex(), sty)
                # Best effort to display bad names
                put("".join(ss.info.name.tobytes().decode(errors="ignore").split()), sty)
            else:
                for _ in range(5):
                    put("?", S_MUTED)

        return self._node_table_renderer.flip_buffer()

    # noinspection SpellCheckingInspection
    def _render_connectivity_matrix(
        self,
        states: dict[Optional[int], NodeState],
        xfer_delta: spmatrix,
        xfer_rates: spmatrix,
        byte_rates: spmatrix,
    ) -> str:
        tbl = self._connectivity_matrix_renderer
        online_states: dict[Optional[int], NodeState] = {k: v for k, v in states.items() if v.online}

        # This part took some time to get right to avoid accidental dense matrix operations, which are super slow.
        xfer_rates_by_ds = xfer_rates.sum(axis=0)
        assert xfer_rates_by_ds.size == N_SUBJECTS + N_SERVICES * 2
        xfer_delta_by_ds = xfer_delta.sum(axis=0)
        byte_rates_by_ds = byte_rates.sum(axis=0)

        # Consider a port existing if either holds:
        #   - there have been recent transfers, even if the source nodes have gone offline
        #   - if the port was recently reported via uavcan.node.port.List, even if the node is currently offline
        all_subjects: set[int] = set()
        all_services: set[int] = set()
        for y in xfer_rates_by_ds.nonzero()[1]:
            y = int(y)
            if y < N_SUBJECTS:
                all_subjects.add(y)
            else:
                all_services.add((y - N_SUBJECTS) % N_SERVICES)
        for node_id, state in states.items():
            if state.ports is not None:
                all_subjects |= state.ports.pub
                # Subjects that are only subscribed to by supersubscribers are only shown if there are other nodes
                # utilizing these.
                if len(state.ports.sub) < N_SUBJECTS:
                    all_subjects |= state.ports.sub
                all_services |= state.ports.cln
                all_services |= state.ports.srv

        # HEADER ROWS AND COLUMNS
        num_nodes = len(online_states)
        num_subjects = len(all_subjects)
        num_services = len(all_services)
        row_subject = 0
        row_service = row_subject + num_subjects + 3
        row_total = row_service + num_services + 3

        tbl[row_subject, 0] = "MESSG", S_MUTED
        tbl[row_service, 0] = "RQ+RS", S_MUTED
        tbl[row_total, 0] = "TOTAL", S_MUTED

        for row in (row_subject + num_subjects + 1, row_service + num_services + 1):
            tbl[row + 0, num_nodes + 3] = "↖ t/s", S_MUTED
            tbl[row + 1, num_nodes + 3] = "", S_MUTED

        for row in (row_subject, row_service, row_total):  # Row of node-IDs and per-port totals.
            for ii, (node_id, state) in enumerate(online_states.items()):
                sty = S_POOR if state.ports is None else S_NICE
                if node_id is not None:
                    tbl[row, ii + 1] = node_id, sty
                else:
                    tbl[row, ii + 1] = " anon", sty
            tbl[row, num_nodes + 1] = " ∑t/s"
            tbl[row, num_nodes + 2] = " ∑B/s"

        for row in (row_subject + num_subjects, row_service + num_services, row_total):  # Per-node totals.
            tbl[row + 1, 0] = "∑t/s"
            tbl[row + 2, 0] = "∑B/s"

        for ii, sid in enumerate(sorted(all_subjects)):  # Subject-ID and Service-ID.
            for col in (0, num_nodes + 3):
                tbl[row_subject + ii + 1, col] = sid, S_DEFAULT
        for ii, sid in enumerate(sorted(all_services)):
            for col in (0, num_nodes + 3):
                tbl[row_service + ii + 1, col] = sid, S_DEFAULT

        # CONTENTS
        View._render_subject_matrix_contents(
            lambda row, col, data, style: tbl.set_cell(row + row_subject + 1, col + 1, data, style=style),
            states=online_states,
            subjects=all_subjects,
            xfer_delta=xfer_delta,
            xfer_rates=xfer_rates,
            byte_rates=byte_rates,
            xfer_delta_by_port=xfer_delta_by_ds,
            xfer_rates_by_port=xfer_rates_by_ds,
            byte_rates_by_port=byte_rates_by_ds,
        )

        def slice_req_rsp(m: _T) -> tuple[_T, _T]:
            a = N_SUBJECTS + N_SERVICES * 0
            b = N_SUBJECTS + N_SERVICES * 1
            c = N_SUBJECTS + N_SERVICES * 2
            return (m[:, a:b], m[:, b:c])  # type: ignore

        View._render_service_matrix_contents(
            lambda row, col, data, style: tbl.set_cell(row + row_service + 1, col + 1, data, style=style),
            states=online_states,
            services=all_services,
            xfer_delta=slice_req_rsp(xfer_delta),
            xfer_rates=slice_req_rsp(xfer_rates),
            byte_rates=slice_req_rsp(byte_rates),
            xfer_delta_by_port=slice_req_rsp(xfer_delta_by_ds),
            xfer_rates_by_port=slice_req_rsp(xfer_rates_by_ds),
            byte_rates_by_port=slice_req_rsp(byte_rates_by_ds),
        )

        # TOTAL DATA RATE
        xfer_delta_by_node = xfer_delta.sum(axis=1)
        xfer_rates_by_node = xfer_rates.sum(axis=1)
        byte_rates_by_node = byte_rates.sum(axis=1)
        for ii, node_id in enumerate(online_states):
            x = node_id if node_id is not None else N_NODES
            sty = get_matrix_cell_style(None, None, int(xfer_delta_by_node[x]) > 0)
            tbl[row_total + 1, ii + 1] = render_xfer_rate(float(xfer_rates_by_node[x])), sty
            tbl[row_total + 2, ii + 1] = render_xfer_rate(float(byte_rates_by_node[x])), sty

        # Sum the DS-wise vectors because they are usually faster due to being smaller.
        sty = get_matrix_cell_style(None, None, int(xfer_delta_by_ds.sum()) > 0)
        tbl[row_total + 1, num_nodes + 1] = render_xfer_rate(float(xfer_rates_by_ds.sum())), sty
        tbl[row_total + 2, num_nodes + 2] = render_byte_rate(float(byte_rates_by_ds.sum())), sty

        tbl[row_total + 1, num_nodes + 3] = ""
        tbl[row_total + 2, num_nodes + 3] = ""

        return tbl.flip_buffer()

    @staticmethod
    def _render_subject_matrix_contents(
        put: Callable[[int, int, Any, Style], None],
        states: dict[Optional[int], NodeState],
        subjects: AbstractSet[int],
        xfer_delta: spmatrix,
        xfer_rates: spmatrix,
        byte_rates: spmatrix,
        xfer_delta_by_port: NDArray[np.int_],
        xfer_rates_by_port: NDArray[np.float_],
        byte_rates_by_port: NDArray[np.float_],
    ) -> None:
        recent_by_node: dict[Optional[int], bool] = defaultdict(bool)
        xfer_rate_by_node: dict[Optional[int], float] = defaultdict(float)
        byte_rate_by_node: dict[Optional[int], float] = defaultdict(float)
        for row, subject_id in enumerate(sorted(subjects)):
            for col, (node_id, state) in enumerate(states.items()):
                x = node_id if node_id is not None else N_NODES
                recent = int(xfer_delta[x, subject_id]) > 0
                rate = float(xfer_rates[x, subject_id])
                if state.ports is not None:
                    pub = subject_id in state.ports.pub
                    sub = subject_id in state.ports.sub
                    sty = get_matrix_cell_style(pub, sub, recent)
                    text = render_xfer_rate(rate) if pub or (rate > EPSILON) else ""
                else:
                    sty = get_matrix_cell_style(None, None, recent)
                    text = render_xfer_rate(rate) if rate > EPSILON else ""
                put(row, col, text, sty)

                recent_by_node[node_id] |= recent
                xfer_rate_by_node[node_id] += rate
                byte_rate_by_node[node_id] += byte_rates[x, subject_id]

            recent = xfer_delta_by_port[0, subject_id] > 0
            sty = get_matrix_cell_style(None, None, recent)
            put(row, len(states) + 0, render_xfer_rate(xfer_rates_by_port[0, subject_id]), sty)
            put(row, len(states) + 1, render_byte_rate(byte_rates_by_port[0, subject_id]), sty)

        row = len(subjects)
        for col, node_id in enumerate(states):
            sty = get_matrix_cell_style(None, None, recent_by_node[node_id])
            put(row + 0, col, render_xfer_rate(xfer_rate_by_node[node_id]), sty)
            put(row + 1, col, render_byte_rate(byte_rate_by_node[node_id]), sty)

        sty = get_matrix_cell_style(None, None, sum(recent_by_node.values()) > 0)
        put(row + 0, len(states) + 0, render_xfer_rate(sum(xfer_rate_by_node.values())), sty)
        put(row + 1, len(states) + 1, render_byte_rate(sum(byte_rate_by_node.values())), sty)

    @staticmethod
    def _render_service_matrix_contents(
        put: Callable[[int, int, Any, Style], None],
        states: dict[Optional[int], NodeState],
        services: AbstractSet[int],
        xfer_delta: tuple[spmatrix, spmatrix],
        xfer_rates: tuple[spmatrix, spmatrix],
        byte_rates: tuple[spmatrix, spmatrix],
        xfer_delta_by_port: tuple[NDArray[np.int_], NDArray[np.int_]],
        xfer_rates_by_port: tuple[NDArray[np.float_], NDArray[np.float_]],
        byte_rates_by_port: tuple[NDArray[np.float_], NDArray[np.float_]],
    ) -> None:
        # We used to display two rows per service: separate request and response. It is very informative but a bit
        # expensive in terms of the screen space, which is very limited when large networks are involved.
        # So while the data provided to this method is sufficient to build a super-detailed representation,
        # currently we collapse it into one service per row such that request and response states are joined together.
        # We may change it later shall the need arise.
        xfer_delta_uni: spmatrix = sum(xfer_delta)
        byte_rates_uni: spmatrix = sum(byte_rates)
        xfer_delta_by_port_uni: NDArray[np.int_] = sum(xfer_delta_by_port)  # type: ignore
        xfer_rates_by_port_uni: NDArray[np.float_] = sum(xfer_rates_by_port)  # type: ignore
        byte_rates_by_port_uni: NDArray[np.float_] = sum(byte_rates_by_port)  # type: ignore

        recent_by_node: dict[Optional[int], bool] = defaultdict(bool)
        xfer_rate_by_node: dict[Optional[int], float] = defaultdict(float)
        byte_rate_by_node: dict[Optional[int], float] = defaultdict(float)

        for row, service_id in enumerate(sorted(services)):
            for col, (node_id, state) in enumerate(states.items()):
                x = node_id if node_id is not None else N_NODES
                recent = int(xfer_delta_uni[x, service_id]) > 0
                rate_req = float(xfer_rates[0][x, service_id])
                rate_rsp = float(xfer_rates[1][x, service_id])
                rate_total = rate_req + rate_rsp
                if state.ports is not None:
                    cln = service_id in state.ports.cln
                    srv = service_id in state.ports.srv
                    sty = get_matrix_cell_style(tx=cln, rx=srv, recently_active=recent)
                    text = render_xfer_rate(rate_total) if cln or srv or (rate_total > EPSILON) else ""
                else:
                    sty = get_matrix_cell_style(None, None, recent)
                    text = render_xfer_rate(rate_total) if rate_total > EPSILON else ""

                put(row, col, text, sty)

                recent_by_node[node_id] |= recent
                xfer_rate_by_node[node_id] += rate_total
                byte_rate_by_node[node_id] += byte_rates_uni[x, service_id]

            recent = int(xfer_delta_by_port_uni[0, service_id]) > 0
            sty = get_matrix_cell_style(None, None, recent)
            put(row, len(states) + 0, render_xfer_rate(xfer_rates_by_port_uni[0, service_id]), sty)
            put(row, len(states) + 1, render_byte_rate(byte_rates_by_port_uni[0, service_id]), sty)

        total_recent = False
        total_xfer_rate = 0.0
        total_byte_rate = 0.0

        row = len(services)
        for col, node_id in enumerate(states):
            recent = recent_by_node[node_id] > 0
            xfer_rate = xfer_rate_by_node[node_id]
            byte_rate = byte_rate_by_node[node_id]

            total_recent = total_recent or recent
            total_xfer_rate += xfer_rate
            total_byte_rate += byte_rate

            sty = get_matrix_cell_style(None, None, recent)
            put(row + 0, col, render_xfer_rate(xfer_rate), sty)
            put(row + 1, col, render_byte_rate(byte_rate), sty)

        sty = get_matrix_cell_style(None, None, total_recent)
        put(row + 0, len(states) + 0, render_xfer_rate(total_xfer_rate), sty)
        put(row + 1, len(states) + 1, render_byte_rate(total_byte_rate), sty)


@functools.lru_cache(None)
def get_matrix_cell_style(tx: Optional[bool], rx: Optional[bool], recently_active: bool) -> Style:
    salience = 1 if recently_active else -1
    fg = Color.RED if recently_active else Color.WHITE
    if tx and rx:
        return Style(fg=fg, bg=Color.CYAN, salience=salience)
    if tx:
        return Style(fg=fg, bg=Color.BLUE, salience=salience)
    if rx:
        return Style(fg=fg, bg=Color.GREEN, salience=salience)
    return Style(fg=fg, salience=salience)


# noinspection SpellCheckingInspection
def render_mode(val: uavcan.node.Mode_1_0) -> tuple[str, Optional[Style]]:
    if val.value == val.OPERATIONAL:
        return "oper", None
    if val.value == val.INITIALIZATION:
        return "init", S_NOTICE
    if val.value == val.MAINTENANCE:
        return "mntn", S_ADVISORY
    if val.value == val.SOFTWARE_UPDATE:
        return "swup", S_CAUTION
    return str(val.value), S_FAILURE  # pragma: no cover


# noinspection SpellCheckingInspection
def render_health(val: uavcan.node.Health_1_0) -> tuple[str, Optional[Style]]:
    if val.value == val.NOMINAL:
        return "nomina", None
    if val.value == val.ADVISORY:
        return "adviso", S_ADVISORY
    if val.value == val.CAUTION:
        return "cautio", S_CAUTION
    if val.value == val.WARNING:
        return "warnin", S_WARNING
    return str(val.value), S_FAILURE  # pragma: no cover


def render_uptime(val: int) -> str:
    return f"{val // (3600 * 24):5d}d{(val // 3600) % 24:02d}:{(val // 60) % 60:02d}:{val % 60:02d}"


def render_version(val: uavcan.node.Version_1_0) -> str:
    return "% 3d.%-3d" % (val.major, val.minor)  # pylint: disable=consider-using-f-string


def render_full_software_version(version: uavcan.node.Version_1_0, vcs_revision_id: int, crc: Optional[int]) -> str:
    out = f"{version.major:3d}.{version.minor}"
    if vcs_revision_id != 0 or crc is not None:
        out += f".{vcs_revision_id:016x}"
    if crc is not None:
        out += f".{crc:016x}"
    return out.ljust(41)


def render_xfer_rate(x: float) -> str:
    x = max(x, 0.0)  # The value may be slightly negative due to accumulated floating point error
    if x < 1e3:
        return f"{x:4.0f} "
    if x < 1e6:
        return f"{x / 1e3:4.0f}k"
    return f"{x / 1e6:4.0f}M"


def render_byte_rate(x: float) -> str:
    x = max(x, 0.0)  # The value may be slightly negative due to accumulated floating point error
    if x < 1024:
        return f"{x:4.0f} "
    if x < 1024 * 1024:
        return f"{x / 1024:4.0f}K"
    return f"{x / (1024 * 1024):4.0f}M"


EPSILON = sys.float_info.epsilon

_T = TypeVar("_T")

_logger = yakut.get_logger(__name__)
